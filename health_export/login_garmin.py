"""One-off script to log in to Garmin Connect and save tokens."""

import os
import sys
from pathlib import Path

from garminconnect import Garmin

TOKENSTORE = Path.home() / ".garmin_tokens"


def main():
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")

    if not email or not password:
        print("Set GARMIN_EMAIL and GARMIN_PASSWORD env vars first")
        sys.exit(1)

    print(f"Logging in as {email}...")
    sys.stdout.flush()

    client = Garmin(email=email, password=password, prompt_mfa=lambda: input("MFA code: "))
    client.login()

    TOKENSTORE.mkdir(parents=True, exist_ok=True)
    client.garth.dump(str(TOKENSTORE))
    print(f"Tokens saved to {TOKENSTORE}")


if __name__ == "__main__":
    main()
