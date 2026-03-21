#!/usr/bin/env python3
"""
Fetch full-resolution workout data from the HealthKit Exporter iOS app
and save as JSON for the FIT converter.
"""

import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


def fetch_json(url, timeout=60):
    """Fetch JSON from a URL."""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.152"
    port = sys.argv[2] if len(sys.argv) > 2 else "8080"
    base = f"http://{host}:{port}"
    output_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("apple_health_export")
    output_dir.mkdir(exist_ok=True)

    print(f"Fetching workouts from {base}...")
    workouts = fetch_json(f"{base}/workouts")
    print(f"Found {len(workouts)} total workouts")

    # Filter to Apple Watch workouts
    aw_workouts = [
        w for w in workouts
        if 'Apple Watch' in w.get('source', '') or 'Bharat' in w.get('source', '')
    ]
    print(f"Apple Watch workouts: {len(aw_workouts)}")

    # Save workout list
    with open(output_dir / "workouts.json", "w") as f:
        json.dump(aw_workouts, f, indent=2)

    # Fetch metrics for each workout
    failed = []
    for i, workout in enumerate(aw_workouts):
        idx = workout['index']
        date = workout['start_date'][:10]
        activity = workout.get('activity_type', 'unknown')
        label = f"{date}_{activity}"

        print(f"[{i+1}/{len(aw_workouts)}] Fetching metrics for {label} (index {idx})...", end=" ", flush=True)

        try:
            # Metrics response includes route data
            data = fetch_json(f"{base}/workouts/{idx}", timeout=120)
            route = data.pop('route', [])
            workout_file = output_dir / f"{label}_{idx}.json"
            with open(workout_file, "w") as f:
                json.dump({
                    "workout": workout,
                    "metrics": data,
                    "route": route,
                }, f)

            total_points = sum(len(v) for v in data.values() if isinstance(v, list))
            print(f"{total_points} metric points, {len(route)} GPS points")
        except Exception as e:
            print(f"FAILED: {e}")
            failed.append((idx, label, str(e)))

        # Small delay to not overwhelm the phone
        time.sleep(0.1)

    print(f"\nDone. Saved {len(aw_workouts) - len(failed)} workouts to {output_dir}/")
    if failed:
        print(f"Failed: {len(failed)}")
        for idx, label, err in failed:
            print(f"  {label} (index {idx}): {err}")


if __name__ == "__main__":
    main()
