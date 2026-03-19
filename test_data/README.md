# Test Data

This directory contains sample Apple Health export data for testing the converter.

## Files

- **`export.xml`** - Sample Apple Health export with 4 workouts:
  - Running workout (2024-01-15) with heart rate data ✅
  - Walking workout (2024-01-16) without heart rate data ⚠️
  - Cycling workout (2024-02-10) with heart rate data ✅
  - Strava workout (ignored by converter) ❌

- **`workout-routes/`** - Sample GPX files with GPS trackpoints:
  - `route_2024-01-15_10.00am.gpx` - 10 trackpoints for running workout
  - `route_2024-01-16_1.15pm.gpx` - 6 trackpoints for walking workout  
  - `route_2024-02-10_10.00am.gpx` - 8 trackpoints for cycling workout

## Usage

To test the converter with this sample data:

```bash
python3 convert_to_tcx.py test_data/
```

Expected output:
- 2 workouts WITH heart rate → converted to TCX
- 1 workout WITHOUT heart rate → converted to separate folder
- 1 non-Apple Watch workout → ignored

## Data Structure

The test data mimics real Apple Health exports:
- Realistic GPS coordinates (Bristol, UK area)
- Proper elevation changes and speeds
- Heart rate statistics (avg, min, max)
- Distance, calories, and duration data
- Apple Watch device metadata
- Workout route references to GPX files