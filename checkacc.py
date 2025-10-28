import asyncio
import aiohttp
import aiofiles
import random
import time
from colorama import Fore, Style
from aiohttp_socks import ProxyConnector
from urllib.parse import urlparse

input_file = "accounts.txt"
output_file = "registered.txt"
proxies_file = "proxies.txt"
api_url = "https://spclient.wg.spotify.com/signup/public/v1/account?validate=1&email={}"

file_lock = asyncio.Lock()

proxy_status = {}
MAX_PROXY_FAILURES = 3
COOLDOWN_DURATION = 60

async def load_proxies():
    try:
        async with aiofiles.open(proxies_file, 'r') as f:
            lines = await f.readlines()
            proxies = [line.strip() for line in lines if line.strip()]
        print(f"{Fore.CYAN}Loaded {len(proxies)} proxies{Style.RESET_ALL}")
        return proxies
    except FileNotFoundError:
        print(f"{Fore.RED}[ERROR] Proxy file {proxies_file} not found. Running without proxies.{Style.RESET_ALL}")
        return []

def update_proxy_failure(proxy, cooldown=COOLDOWN_DURATION):
    now = time.monotonic()
    if proxy not in proxy_status:
        proxy_status[proxy] = {"failures": 1, "cooldown_until": now + cooldown}
    else:
        proxy_status[proxy]["failures"] += 1
        proxy_status[proxy]["cooldown_until"] = now + cooldown
    print(f"{Fore.YELLOW}[INFO] Updated proxy {proxy} failure count to {proxy_status[proxy]['failures']} with cooldown until {proxy_status[proxy]['cooldown_until']}{Style.RESET_ALL}")

def reset_proxy_status(proxy):
    if proxy in proxy_status:
        proxy_status[proxy]["failures"] = 0
        proxy_status[proxy]["cooldown_until"] = 0

def select_proxy(proxy_list):
    now = time.monotonic()
    if not proxy_list:
        return None

    working_proxies = []
    for p in proxy_list:
        status = proxy_status.get(p, {"failures": 0, "cooldown_until": 0})
        if status["failures"] < MAX_PROXY_FAILURES and status["cooldown_until"] <= now:
            working_proxies.append(p)

    if not working_proxies:
        print(f"{Fore.RED}[WARNING] No proxies available without cooldown. Resetting cooldowns for all proxies.{Style.RESET_ALL}")

        for p in proxy_list:
            if p in proxy_status:
                proxy_status[p]["cooldown_until"] = 0
        working_proxies = proxy_list.copy()

    selected = random.choice(working_proxies)
    return selected

async def create_session(proxy=None):
    if not proxy:
        return aiohttp.ClientSession()

    try:
        parsed = urlparse(proxy)
        protocol = parsed.scheme
        if protocol.startswith('socks'):
            connector = ProxyConnector.from_url(proxy)
            return aiohttp.ClientSession(connector=connector)
        else:
            return aiohttp.ClientSession(proxy=proxy)
    except Exception as e:
        update_proxy_failure(proxy)
        print(f"{Fore.RED}[ERROR] Failed to create session with proxy {proxy}: {e}{Style.RESET_ALL}")
        return aiohttp.ClientSession()

async def check_email(proxy_list, account, max_retries=3):
    email = account.split(':')[0]
    retries = 0
    used_proxies = set()

    while retries < max_retries:
        now = time.monotonic()

        working_proxies = [
            p for p in proxy_list
            if proxy_status.get(p, {"failures": 0, "cooldown_until": 0})["failures"] < MAX_PROXY_FAILURES and
               proxy_status.get(p, {"cooldown_until": 0})["cooldown_until"] <= now
        ]
        available_proxies = [p for p in working_proxies if p not in used_proxies]
        proxy = random.choice(available_proxies) if available_proxies else select_proxy(proxy_list)
        proxy_info = f"using {proxy}" if proxy else "without proxy"
        if proxy:
            used_proxies.add(proxy)

        try:
            async with await create_session(proxy) as session:
                async with session.get(api_url.format(email), timeout=10) as response:
                    if response.status == 429:
                        data = await response.json()
                        error_msg = data.get('errors', {}).get('username', 'Too many attempts')
                        print(f"{Fore.YELLOW}[RATE LIMITED] {email} ({proxy_info}): {error_msg}{Style.RESET_ALL}")
                        if proxy:
                            update_proxy_failure(proxy)
                        retries += 1
                        continue

                    if response.status != 200:
                        print(f"{Fore.RED}[ERROR] {email} ({proxy_info}): HTTP {response.status}{Style.RESET_ALL}")
                        if proxy:
                            update_proxy_failure(proxy)
                        retries += 1
                        continue

                    if proxy:
                        reset_proxy_status(proxy)

                    data = await response.json()
                    status_code = data.get("status")
                    if status_code == 20:
                        print(f"{Fore.GREEN}[REGISTERED] {email} ({proxy_info}){Style.RESET_ALL}")
                        return account
                    elif status_code == 1:
                        print(f"{Fore.RED}[NOT REGISTERED] {email} ({proxy_info}){Style.RESET_ALL}")
                        return None
                    else:
                        print(f"{Fore.YELLOW}[UNKNOWN STATUS] {email} ({proxy_info}): {status_code}{Style.RESET_ALL}")

                        if retries < max_retries - 1:
                            print(f"{Fore.CYAN}[INFO] Retrying {email} with a different proxy due to unknown status...{Style.RESET_ALL}")
                            retries += 1
                            continue
                        break
        except Exception as e:
            print(f"{Fore.RED}[ERROR] {email} ({proxy_info}): {e}{Style.RESET_ALL}")
            if proxy:
                update_proxy_failure(proxy)
            retries += 1
            await asyncio.sleep(1)
    return None

async def process_batch(accounts, proxy_list, batch_size=50, delay=1):
    registered_accounts = []

    for i in range(0, len(accounts), batch_size):
        batch = accounts[i:i+batch_size]
        tasks = [check_email(proxy_list, account) for account in batch]
        results = await asyncio.gather(*tasks)
        valid_results = [account for account in results if account]
        registered_accounts.extend(valid_results)

        if valid_results:
            async with file_lock:
                async with aiofiles.open(output_file, "a") as outfile:
                    for account in valid_results:
                        await outfile.write(account + "\n")
                    await outfile.flush()

        working_proxies = [
            p for p in proxy_list
            if proxy_status.get(p, {"failures": 0, "cooldown_until": 0})["failures"] < MAX_PROXY_FAILURES
            and proxy_status.get(p, {"cooldown_until": 0})["cooldown_until"] <= time.monotonic()
        ]
        print(f"{Fore.CYAN}Processed {i+len(batch)}/{len(accounts)} accounts. Found {len(registered_accounts)} registered so far. Working proxies: {len(working_proxies)}/{len(proxy_list)}{Style.RESET_ALL}")

        if delay > 0:
            await asyncio.sleep(delay)

    return registered_accounts

async def main():
    try:
        proxy_list = await load_proxies()

        async with aiofiles.open(input_file, "r") as infile:
            content = await infile.read()
            accounts = [line.strip() for line in content.splitlines() if line.strip()]

        async with aiofiles.open(output_file, "w") as outfile:
            await outfile.write("")

        print(f"{Fore.CYAN}Checking {len(accounts)} accounts with {len(proxy_list)} proxies...{Style.RESET_ALL}")
        registered_accounts = await process_batch(accounts, proxy_list)

        dead_proxies = [
            p for p in proxy_list
            if proxy_status.get(p, {"failures": 0})["failures"] >= MAX_PROXY_FAILURES
        ]
        print(f"\n{Fore.CYAN}Proxy statistics:{Style.RESET_ALL}")
        print(f"{Fore.GREEN}Total proxies: {len(proxy_list)}{Style.RESET_ALL}")
        print(f"{Fore.RED}Dead proxies: {len(dead_proxies)}{Style.RESET_ALL}")

        print(f"\n{Fore.CYAN}Check completed. Found {len(registered_accounts)} registered accounts. Results saved to {output_file}.{Style.RESET_ALL}")
    except FileNotFoundError:
        print(f"{Fore.RED}[ERROR] File {input_file} not found.{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}[ERROR] An unexpected error occurred: {e}{Style.RESET_ALL}")

if __name__ == "__main__":
    asyncio.run(main())