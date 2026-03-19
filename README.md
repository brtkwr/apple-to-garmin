# Apple Health to Garmin Converter

Convert Apple Watch workouts from Apple Health export to **FIT** or **TCX** format for importing to Garmin Connect, Strava, TrainingPeaks, and other fitness platforms.

## Features

- Converts to FIT (recommended) or TCX format
- Preserves per-second heart rate, GPS routes, and workout statistics
- FIT output includes running power, stride length, vertical oscillation, and ground contact time
- Organises workouts by year/month
- Supports running, walking, cycling, hiking, swimming, and other workout types

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (for FIT format — manages dependencies automatically)
- Apple Health export data

## How to Export Apple Health Data

1. Open the **Apple Health** app on your iPhone
2. Tap your **profile picture** (top right corner)
3. Scroll down and tap **"Export All Health Data"**
4. Tap **"Export"** to confirm
5. **AirDrop or email** the ZIP to your Mac
6. Extract the ZIP — you'll get a folder containing:
   - `export.xml` — main health data including workout statistics and per-second metrics
   - `workout-routes/` — GPX files with GPS trackpoints for each workout

## Usage

### FIT format (recommended)

FIT is Garmin's native binary format and preserves the most data — heart rate, running power, stride length, vertical oscillation, and ground contact time.

```bash
git clone https://github.com/brtkwr/apple-to-garmin.git
cd apple-to-garmin
uv run convert_to_fit.py /path/to/apple_health_export
```

Filter by activity type:
```bash
uv run convert_to_fit.py /path/to/export --activity running
```

Specify output directory:
```bash
uv run convert_to_fit.py /path/to/export --output /path/to/fit/files
```

### TCX format (zero dependencies)

TCX is an XML-based format that works everywhere but only supports heart rate, GPS, altitude, distance, and calories. No running dynamics.

```bash
python3 convert_apple_workouts.py /path/to/apple_health_export
```

## Output Structure

```text
fit_files/                          # or tcx_files/
├── 2024/
│   ├── 01/
│   │   ├── 2024-01-02_183050_Running.fit
│   │   └── 2024-01-06_090528_Running.fit
│   └── 02/
│       └── 2024-02-20_182954_Running.fit
└── 2025/
    └── ...
```

TCX output also includes a `no_heart_rate/` subfolder for workouts without HR data.

## What Gets Converted

| Data | FIT | TCX |
|------|-----|-----|
| GPS coordinates | ✅ | ✅ |
| Heart rate (per-second) | ✅ | ✅ |
| Distance | ✅ | ✅ |
| Calories | ✅ | ✅ |
| Altitude | ✅ | ✅ |
| Running power | ✅ | ❌ |
| Stride length | ✅ | ❌ |
| Vertical oscillation | ✅ | ❌ |
| Ground contact time | ✅ | ❌ |
| Running speed | ✅ | ❌ |

## Heart Rate Data

Apple Health exports contain per-second heart rate records in `export.xml` as `HKQuantityTypeIdentifierHeartRate` entries. Both converters parse these and match them to GPS trackpoints using binary search, falling back to the workout average when no nearby reading exists.

## Importing to Garmin Connect

1. Go to [Garmin Connect](https://connect.garmin.com)
2. Click the **"+"** button → Import Data
3. Upload your FIT or TCX files (can select multiple)
4. Wait for processing — workouts will appear in your timeline

## Testing

```bash
# Using the test runner
python3 run_tests.py

# Or using unittest directly
python3 -m unittest test_convert_apple_workouts -v
```

Tests run automatically on GitHub Actions for Python 3.11-3.13.

## Troubleshooting

**"Found 0 Apple Watch workouts"**
- Make sure you've exported from the Apple Health app (not Apple Watch app)
- Verify the export folder contains `export.xml` and `workout-routes/`

**"No heart rate data"**
- Early Apple Watch workouts may not have recorded heart rate
- TCX converter saves these separately in `no_heart_rate/`

## License

MIT
