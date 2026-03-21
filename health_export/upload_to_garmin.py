"""Upload FIT files to Garmin Connect."""

import argparse
import os
import sys
import time
from pathlib import Path

from garminconnect import Garmin


TOKENSTORE = Path.home() / ".garmin_tokens"
DESCRIPTION = "Recorded on Apple Watch. Converted from HealthKit data."


def get_client(email: str | None, password: str | None) -> Garmin:
    """Authenticate with Garmin Connect, reusing saved tokens if available."""
    client = Garmin(email=email, password=password, prompt_mfa=lambda: input("MFA code: "))

    if TOKENSTORE.exists():
        try:
            client.login(tokenstore=str(TOKENSTORE))
            print(f"Logged in using saved tokens from {TOKENSTORE}")
            return client
        except Exception:
            print("Saved tokens expired, logging in with credentials...")

    if not email or not password:
        print("No saved tokens found. Provide --email and --password (or set GARMIN_EMAIL / GARMIN_PASSWORD).")
        sys.exit(1)

    client.login()
    TOKENSTORE.mkdir(parents=True, exist_ok=True)
    client.garth.dump(str(TOKENSTORE))
    print(f"Logged in and saved tokens to {TOKENSTORE}")
    return client


def find_fit_files(directory: Path) -> list[Path]:
    """Find all .fit files recursively, sorted by name."""
    return sorted(directory.rglob("*.fit"))


def upload(client: Garmin, fit_files: list[Path], dry_run: bool = False) -> None:
    """Upload FIT files to Garmin Connect with progress."""
    total = len(fit_files)
    success = 0
    skipped = 0
    failed = []

    for i, path in enumerate(fit_files, 1):
        name = path.relative_to(path.parents[2]) if len(path.parents) > 2 else path.name
        prefix = f"[{i}/{total}]"

        if dry_run:
            print(f"{prefix} Would upload: {name}")
            success += 1
            continue

        try:
            client.upload_activity(str(path))
            print(f"{prefix} Uploaded: {name}")
            success += 1
        except Exception as e:
            error = str(e)
            if "409" in error or "duplicate" in error.lower() or "already exists" in error.lower():
                print(f"{prefix} Skipped (duplicate): {name}")
                skipped += 1
            else:
                print(f"{prefix} FAILED: {name} — {error}")
                failed.append((name, error))

        # Brief pause between uploads to avoid rate limiting
        if not dry_run and i < total:
            time.sleep(0.5)

    print(f"\nDone: {success} uploaded, {skipped} duplicates, {len(failed)} failed")
    if failed:
        print("\nFailed uploads:")
        for name, error in failed:
            print(f"  {name}: {error}")


def main():
    parser = argparse.ArgumentParser(description="Upload FIT files to Garmin Connect")
    parser.add_argument("directory", nargs="?", default="fit_files", help="Directory containing FIT files (default: fit_files)")
    parser.add_argument("--email", default=os.environ.get("GARMIN_EMAIL"), help="Garmin Connect email (or set GARMIN_EMAIL)")
    parser.add_argument("--password", default=os.environ.get("GARMIN_PASSWORD"), help="Garmin Connect password (or set GARMIN_PASSWORD)")
    parser.add_argument("--dry-run", action="store_true", help="List files without uploading")
    args = parser.parse_args()

    directory = Path(args.directory)
    if not directory.exists():
        print(f"Directory not found: {directory}")
        sys.exit(1)

    fit_files = find_fit_files(directory)
    if not fit_files:
        print(f"No .fit files found in {directory}")
        sys.exit(1)

    print(f"Found {len(fit_files)} FIT files in {directory}")

    if args.dry_run:
        upload(None, fit_files, dry_run=True)
        return

    client = get_client(args.email, args.password)
    upload(client, fit_files)


if __name__ == "__main__":
    main()
