import asyncio
import aiohttp
import aiofiles
import random
from colorama import Fore, Style
from aiohttp_socks import ProxyConnector
from urllib.parse import urlparse

input_file = "accounts.txt"
output_file = "registered.txt"
proxies_file = "proxies.txt"

api_url = "https://spclient.wg.spotify.com/signup/public/v1/account?validate=1&email={}"

file_lock = asyncio.Lock()

proxy_attempts = {}
MAX_PROXY_FAILURES = 3

async def load_proxies():
    try:
        with open(proxies_file, 'r') as f:
            proxies = [line.strip() for line in f if line.strip()]
        print(f"{Fore.CYAN}Loaded {len(proxies)} proxies{Style.RESET_ALL}")
        return proxies
    except FileNotFoundError:
        print(f"{Fore.RED}[ERROR] Proxy file {proxies_file} not found. Running without proxies.{Style.RESET_ALL}")
        return []

def select_proxy(proxy_list):
    if not proxy_list:
        return None

    working_proxies = [p for p in proxy_list if proxy_attempts.get(p, 0) < MAX_PROXY_FAILURES]

    if not working_proxies:
        print(f"{Fore.RED}[WARNING] All proxies have failed too many times. Resetting failure counts.{Style.RESET_ALL}")

        for proxy in proxy_list:
            proxy_attempts[proxy] = 0
        return random.choice(proxy_list)

    return random.choice(working_proxies)

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

        proxy_attempts[proxy] = proxy_attempts.get(proxy, 0) + 1
        print(f"{Fore.RED}[ERROR] Failed to create session with proxy {proxy}: {e}{Style.RESET_ALL}")
        return aiohttp.ClientSession()

async def check_email(proxy_list, account, max_retries=3):
    email_parts = account.split(':')
    email = email_parts[0]
    retries = 0

    while retries < max_retries:

        proxy = select_proxy(proxy_list)
        proxy_info = f"using {proxy}" if proxy else "without proxy"

        try:
            async with await create_session(proxy) as session:
                async with session.get(api_url.format(email), timeout=10) as response:
                    if response.status == 429:
                        data = await response.json()
                        print(f"{Fore.YELLOW}[RATE LIMITED] {email} ({proxy_info}): {data.get('errors', {}).get('username', 'Too many attempts')}{Style.RESET_ALL}")

                        if proxy:
                            proxy_attempts[proxy] = proxy_attempts.get(proxy, 0) + 1
                        retries += 1

                        continue

                    if response.status != 200:
                        print(f"{Fore.RED}[ERROR] {email} ({proxy_info}): HTTP {response.status}{Style.RESET_ALL}")

                        if proxy:
                            proxy_attempts[proxy] = proxy_attempts.get(proxy, 0) + 1
                        retries += 1
                        continue

                    if proxy:
                        proxy_attempts[proxy] = 0

                    data = await response.json()
                    if data.get("status") == 20:
                        print(f"{Fore.GREEN}[REGISTERED] {email} ({proxy_info}){Style.RESET_ALL}")
                        return account
                    elif data.get("status") == 1:
                        print(f"{Fore.RED}[NOT REGISTERED] {email} ({proxy_info}){Style.RESET_ALL}")
                    else:
                        print(f"{Fore.YELLOW}[UNKNOWN STATUS] {email} ({proxy_info}): {data.get('status')}{Style.RESET_ALL}")

                    break
        except Exception as e:
            print(f"{Fore.RED}[ERROR] {email} ({proxy_info}): {e}{Style.RESET_ALL}")

            if proxy:
                proxy_attempts[proxy] = proxy_attempts.get(proxy, 0) + 1

                if proxy_attempts[proxy] >= MAX_PROXY_FAILURES:
                    print(f"{Fore.RED}[DEAD PROXY] {proxy} has failed {MAX_PROXY_FAILURES} times and will be skipped{Style.RESET_ALL}")

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

        working_proxies = [p for p in proxy_list if proxy_attempts.get(p, 0) < MAX_PROXY_FAILURES]
        print(f"{Fore.CYAN}Processed {i+len(batch)}/{len(accounts)} accounts. Found {len(registered_accounts)} registered so far. Working proxies: {len(working_proxies)}/{len(proxy_list)}{Style.RESET_ALL}")

        if delay > 0:
            await asyncio.sleep(delay)

    return registered_accounts

async def main():
    try:

        proxy_list = await load_proxies()

        with open(input_file, "r") as infile:
            accounts = [line.strip() for line in infile if line.strip()]

        with open(output_file, "w") as outfile:
            pass

        print(f"{Fore.CYAN}Checking {len(accounts)} accounts with {len(proxy_list)} proxies...{Style.RESET_ALL}")
        registered_accounts = await process_batch(accounts, proxy_list)

        dead_proxies = [p for p in proxy_list if proxy_attempts.get(p, 0) >= MAX_PROXY_FAILURES]
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