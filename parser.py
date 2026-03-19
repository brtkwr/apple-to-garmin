#!/usr/bin/env python3
"""
Shared parsing logic for Apple Health export data.

Extracts workouts, per-second metric records, and GPX trackpoints from an
Apple Health export directory.  Uses only the standard library so that
downstream converters (e.g. TCX) remain zero-dependency.
"""

import xml.etree.ElementTree as ET
from bisect import bisect_left
from datetime import datetime
from pathlib import Path

# Apple Health quantity type identifiers we care about
METRIC_TYPES = {
    'HKQuantityTypeIdentifierHeartRate': 'heart_rate',
    'HKQuantityTypeIdentifierRunningPower': 'power',
    'HKQuantityTypeIdentifierRunningSpeed': 'speed',
    'HKQuantityTypeIdentifierRunningVerticalOscillation': 'vertical_oscillation',
    'HKQuantityTypeIdentifierRunningGroundContactTime': 'ground_contact_time',
    'HKQuantityTypeIdentifierRunningStrideLength': 'stride_length',
}

# Apple workout type -> human-readable sport name (used by both converters)
ACTIVITY_TYPE_MAP = {
    'HKWorkoutActivityTypeRunning': 'Running',
    'HKWorkoutActivityTypeWalking': 'Walking',
    'HKWorkoutActivityTypeCycling': 'Biking',
    'HKWorkoutActivityTypeHiking': 'Hiking',
    'HKWorkoutActivityTypeSwimming': 'Swimming',
}

# Sources we treat as "our" devices
SOURCE_KEYWORDS = ('Apple Watch', 'Bharat')


class MetricIndex:
    """Sorted time-series index for a single metric, with nearest-neighbour lookup."""

    def __init__(self):
        self.timestamps = []
        self.values = []

    def add(self, dt, value):
        self.timestamps.append(dt)
        self.values.append(value)

    def sort(self):
        pairs = sorted(zip(self.timestamps, self.values), key=lambda x: x[0])
        self.timestamps = [p[0] for p in pairs]
        self.values = [p[1] for p in pairs]

    def lookup(self, timestamp, max_gap_seconds=30):
        """Find the nearest value for a given timestamp."""
        if not self.timestamps:
            return None
        idx = bisect_left(self.timestamps, timestamp)
        candidates = []
        if idx < len(self.timestamps):
            candidates.append(idx)
        if idx > 0:
            candidates.append(idx - 1)
        best = min(candidates, key=lambda i: abs((self.timestamps[i] - timestamp).total_seconds()))
        gap = abs((self.timestamps[best] - timestamp).total_seconds())
        if gap <= max_gap_seconds:
            return self.values[best]
        return None

    def __len__(self):
        return len(self.timestamps)


def parse_gpx_file(gpx_file):
    """Parse a GPX file and return a list of trackpoint dicts.

    Each dict has keys: lat, lon, elevation, time, speed (or None).
    """
    if not gpx_file or not Path(gpx_file).exists():
        return []

    try:
        tree = ET.parse(gpx_file)
        root = tree.getroot()
        ns = {'gpx': 'http://www.topografix.com/GPX/1/1'}

        trackpoints = []
        for trkpt in root.findall('.//gpx:trkpt', ns):
            lat = float(trkpt.get('lat', 0))
            lon = float(trkpt.get('lon', 0))

            ele_elem = trkpt.find('./gpx:ele', ns)
            elevation = float(ele_elem.text) if ele_elem is not None and ele_elem.text else 0

            time_elem = trkpt.find('./gpx:time', ns)
            if time_elem is not None and time_elem.text:
                timestamp = datetime.fromisoformat(time_elem.text.replace('Z', '+00:00'))
            else:
                continue

            # Speed from extensions (optional)
            speed = None
            extensions = trkpt.find('./gpx:extensions', ns)
            if extensions is not None:
                speed_elem = extensions.find('./speed')
                if speed_elem is not None:
                    speed = float(speed_elem.text)

            trackpoints.append({
                'lat': lat,
                'lon': lon,
                'elevation': elevation,
                'time': timestamp,
                'speed': speed,
            })
        return trackpoints
    except Exception as e:
        print(f"Error parsing GPX file {gpx_file}: {e}")
        return []


def _is_our_source(source_name):
    """Return True if the source name matches one of our devices."""
    return any(kw in source_name for kw in SOURCE_KEYWORDS)


def _extract_workout(workout_elem, routes_dir):
    """Extract a normalised workout dict from a Workout XML element.

    Returns a dict with keys:
        sport, start_time, end_time, duration_seconds, heart_rate (dict or None),
        distance_km, calories, elevation_gain, gpx_file
    or None if essential data is missing.
    """
    activity_type = workout_elem.get('workoutActivityType', '')
    start_date = workout_elem.get('startDate', '')
    end_date = workout_elem.get('endDate', '')
    duration = float(workout_elem.get('duration', 0))

    if not start_date or not end_date:
        return None

    sport = ACTIVITY_TYPE_MAP.get(activity_type, 'Other')
    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date)

    workout = {
        'sport': sport,
        'start_time': start_dt,
        'end_time': end_dt,
        'duration_seconds': duration * 60,
        'heart_rate': None,
        'distance_km': None,
        'calories': None,
        'elevation_gain': None,
        'gpx_file': None,
    }

    for stat in workout_elem.findall('.//WorkoutStatistics'):
        stat_type = stat.get('type', '')
        if 'HeartRate' in stat_type:
            workout['heart_rate'] = {
                'avg': float(stat.get('average', 0)),
                'min': int(stat.get('minimum', 0)),
                'max': int(stat.get('maximum', 0)),
            }
        elif 'DistanceWalkingRunning' in stat_type or 'DistanceCycling' in stat_type:
            workout['distance_km'] = float(stat.get('sum', 0))
        elif 'ActiveEnergyBurned' in stat_type:
            workout['calories'] = float(stat.get('sum', 0))

    # Elevation gain
    elevation_elem = workout_elem.find('.//MetadataEntry[@key="HKElevationAscended"]')
    if elevation_elem is not None:
        elevation_str = elevation_elem.get('value', '0 cm')
        elevation_cm = float(elevation_str.replace(' cm', ''))
        workout['elevation_gain'] = elevation_cm / 100  # cm -> m

    # GPX route reference
    route_elem = workout_elem.find('.//WorkoutRoute/FileReference')
    if route_elem is not None:
        gpx_path = route_elem.get('path', '')
        if gpx_path.startswith('/workout-routes/'):
            gpx_filename = gpx_path.replace('/workout-routes/', '')
            workout['gpx_file'] = routes_dir / gpx_filename

    return workout


def parse_export(export_xml_path):
    """Parse an Apple Health export.xml file.

    Returns (workouts, metrics) where:
        workouts -- list of normalised workout dicts (only from our sources)
        metrics  -- dict of MetricIndex keyed by name
    """
    export_xml_path = Path(export_xml_path)
    routes_dir = export_xml_path.parent / "workout-routes"

    tree = ET.parse(export_xml_path)
    root = tree.getroot()

    # --- Parse metrics ---
    metrics = {name: MetricIndex() for name in METRIC_TYPES.values()}

    for record in root.findall('.//Record'):
        record_type = record.get('type', '')
        if record_type not in METRIC_TYPES:
            continue
        name = METRIC_TYPES[record_type]
        start_date = record.get('startDate', '')
        value = record.get('value', '')
        if not start_date or not value:
            continue
        try:
            dt = datetime.fromisoformat(start_date)
            metrics[name].add(dt, float(value))
        except (ValueError, TypeError):
            continue

    for name, index in metrics.items():
        index.sort()
        print(f"  {name}: {len(index)} records")

    # --- Parse workouts ---
    all_workouts = root.findall('.//Workout')
    print(f"Found {len(all_workouts)} total workouts")

    workouts = []
    apple_watch_count = 0
    for i, workout_elem in enumerate(all_workouts):
        source_name = workout_elem.get('sourceName', '')
        if i < 5:
            print(f"Workout {i}: source='{source_name}'")
        if _is_our_source(source_name):
            apple_watch_count += 1
            workout = _extract_workout(workout_elem, routes_dir)
            if workout:
                workouts.append(workout)

    print(f"Found {apple_watch_count} Apple Watch workouts")
    print(f"Successfully parsed {len(workouts)} workouts with data")

    return workouts, metrics
