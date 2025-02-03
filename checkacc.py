import requests
from colorama import Fore, Style

# Nama file input dan output
input_file = "result.txt"
output_file = "notLoggin.txt"

# URL API Spotify
api_url = "https://spclient.wg.spotify.com/signup/public/v1/account?validate=1&email={}"

def check_email(email):
    try:
        response = requests.get(api_url.format(email))
        response.raise_for_status()
        data = response.json()

        if data.get("status") == 20:
            print(f"{Fore.GREEN}[REGISTERED] {email}{Style.RESET_ALL}")
        elif data.get("status") == 1:
            print(f"{Fore.RED}[NOT REGISTERED] {email}{Style.RESET_ALL}")
            return email
        else:
            print(f"{Fore.YELLOW}[UNKNOWN STATUS] {email}: {data}{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}[ERROR] Could not check {email}: {e}{Style.RESET_ALL}")
    return None

def main():
    try:
        with open(input_file, "r") as infile, open(output_file, "w") as outfile:
            for line in infile:
                email = line.strip()
                if not email:
                    continue

                not_registered_email = check_email(email)

                if not_registered_email:
                    outfile.write(not_registered_email + "\n")

        print(f"\n{Fore.CYAN}Check completed. Results saved to {output_file}.{Style.RESET_ALL}")
    except FileNotFoundError:
        print(f"{Fore.RED}[ERROR] File {input_file} not found.{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}[ERROR] An unexpected error occurred: {e}{Style.RESET_ALL}")

if __name__ == "__main__":
    main()
