#!/usr/bin/env python3
"""
Convert HealthKit JSON export (from the HealthExport iOS app) to FIT files.
Uses full-resolution heart rate and running dynamics data.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
import argparse

from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.messages.device_info_message import DeviceInfoMessage
from fit_tool.profile.profile_type import Sport, Manufacturer, FileType, Event, EventType




SPORT_MAP = {
    'running': Sport.RUNNING,
    'walking': Sport.WALKING,
    'cycling': Sport.CYCLING,
    'hiking': Sport.HIKING,
    'swimming': Sport.SWIMMING,
    'yoga': Sport.TRAINING,
}


def to_fit_ts(dt):
    return int(dt.timestamp() * 1000)


def parse_iso(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


def create_fit(workout, metrics, trackpoints):
    """Create a FIT file from HealthKit JSON data and GPX trackpoints."""
    builder = FitFileBuilder()
    start = parse_iso(workout['start_date'])
    end = parse_iso(workout['end_date'])
    activity = workout.get('activity_type', 'other')
    sport = SPORT_MAP.get(activity, Sport.GENERIC)

    # File ID
    file_id = FileIdMessage()
    file_id.type = FileType.ACTIVITY
    file_id.manufacturer = Manufacturer.DEVELOPMENT
    file_id.product = 0
    file_id.serial_number = 0
    file_id.time_created = to_fit_ts(start)
    builder.add(file_id)

    # Device info
    device_info = DeviceInfoMessage()
    device_info.timestamp = to_fit_ts(start)
    device_info.manufacturer = Manufacturer.DEVELOPMENT
    device_info.product = 0
    device_info.device_index = 0
    device_info.product_name = 'Apple Watch'
    builder.add(device_info)

    # Timer start
    event = EventMessage()
    event.event = Event.TIMER
    event.event_type = EventType.START
    event.timestamp = to_fit_ts(start)
    builder.add(event)

    # Build per-second metric lookup from HealthKit streams
    # Key: integer unix timestamp -> dict of metric values
    metric_map = {
        'heart_rate': 'heart_rate',
        'running_power': 'power',
        'running_speed': 'speed',
        'vertical_oscillation': 'vertical_oscillation',
        'ground_contact_time': 'ground_contact_time',
        'stride_length': 'stride_length',
    }

    # Build sorted timestamp arrays per metric for nearest-neighbour lookup
    from bisect import bisect_left

    metric_streams = {}  # fit_key -> sorted list of (timestamp, value)
    for hk_key, fit_key in metric_map.items():
        points = metrics.get(hk_key, [])
        if points:
            metric_streams[fit_key] = sorted(
                [(int(p['timestamp']), p['value']) for p in points]
            )

    # Build GPS lookup by integer timestamp
    gps_lookup = {}
    for tp in trackpoints:
        ts_key = int(tp['time'].timestamp())
        gps_lookup[ts_key] = tp

    # Collect all unique timestamps from GPS and metrics
    all_metric_ts = set()
    for stream in metric_streams.values():
        all_metric_ts.update(ts for ts, _ in stream)
    all_timestamps = sorted(set(list(all_metric_ts) + list(gps_lookup.keys())))

    def interpolate(stream, ts_key):
        """Linearly interpolate between the two nearest points in a stream.

        Returns the exact value if the timestamp matches a data point,
        a linearly interpolated value if between two points, or the
        boundary value if before the first / after the last point.
        """
        if not stream:
            return None
        timestamps = [t for t, _ in stream]
        idx = bisect_left(timestamps, ts_key)

        # Exact match
        if idx < len(stream) and stream[idx][0] == ts_key:
            return stream[idx][1]

        # Before first or after last data point
        if idx == 0:
            return stream[0][1]
        if idx >= len(stream):
            return stream[-1][1]

        # Interpolate between stream[idx-1] and stream[idx]
        t0, v0 = stream[idx - 1]
        t1, v1 = stream[idx]
        frac = (ts_key - t0) / (t1 - t0)
        return v0 + (v1 - v0) * frac

    for ts_key in all_timestamps:
        record = RecordMessage()
        ts = datetime.fromtimestamp(ts_key, tz=timezone.utc)
        record.timestamp = to_fit_ts(ts)

        # GPS data
        if ts_key in gps_lookup:
            tp = gps_lookup[ts_key]
            record.position_lat = tp.get('lat') or tp.get('latitude')
            record.position_long = tp.get('lon') or tp.get('longitude')
            record.enhanced_altitude = tp.get('elevation') or tp.get('altitude', 0)

        # Apply interpolated metric values
        hr = interpolate(metric_streams.get('heart_rate', []), ts_key)
        if hr is not None:
            record.heart_rate = min(int(hr), 255)

        power = interpolate(metric_streams.get('power', []), ts_key)
        if power is not None:
            record.power = int(power)

        speed = interpolate(metric_streams.get('speed', []), ts_key)
        if speed is not None:
            record.enhanced_speed = speed

        vo = interpolate(metric_streams.get('vertical_oscillation', []), ts_key)
        if vo is not None:
            record.vertical_oscillation = vo * 10  # cm -> mm

        gct = interpolate(metric_streams.get('ground_contact_time', []), ts_key)
        if gct is not None:
            record.stance_time = gct  # already ms

        sl = interpolate(metric_streams.get('stride_length', []), ts_key)
        if sl is not None:
            record.step_length = sl * 1000  # m -> mm

        builder.add(record)

    # Timer stop
    event_stop = EventMessage()
    event_stop.event = Event.TIMER
    event_stop.event_type = EventType.STOP_ALL
    event_stop.timestamp = to_fit_ts(end)
    builder.add(event_stop)

    # Lap
    duration = workout.get('duration_seconds', (end - start).total_seconds())
    lap = LapMessage()
    lap.timestamp = to_fit_ts(end)
    lap.start_time = to_fit_ts(start)
    lap.total_elapsed_time = duration
    lap.total_timer_time = duration
    lap.sport = sport
    if workout.get('total_distance_metres'):
        lap.total_distance = workout['total_distance_metres']
    if workout.get('total_energy_kcal'):
        lap.total_calories = int(workout['total_energy_kcal'])
    builder.add(lap)

    # Session
    session = SessionMessage()
    session.timestamp = to_fit_ts(end)
    session.start_time = to_fit_ts(start)
    session.total_elapsed_time = duration
    session.total_timer_time = duration
    session.sport = sport
    session.first_lap_index = 0
    session.num_laps = 1
    if workout.get('total_distance_metres'):
        session.total_distance = workout['total_distance_metres']
    if workout.get('total_energy_kcal'):
        session.total_calories = int(workout['total_energy_kcal'])
    builder.add(session)

    # Activity
    activity_msg = ActivityMessage()
    activity_msg.timestamp = to_fit_ts(end)
    activity_msg.num_sessions = 1
    activity_msg.total_timer_time = duration
    builder.add(activity_msg)

    return builder.build()


def main():
    parser = argparse.ArgumentParser(
        description='Convert HealthKit JSON export to FIT for Garmin Connect')
    parser.add_argument('healthkit_dir', help='Path to apple_health_export directory')
    parser.add_argument('--output', '-o', help='Output directory for FIT files')
    parser.add_argument('--activity', '-a', help='Filter by activity type')
    args = parser.parse_args()

    hk_dir = Path(args.healthkit_dir)
    output_dir = Path(args.output) if args.output else Path('fit_files')
    output_dir.mkdir(exist_ok=True)

    # Load workout list
    workouts_file = hk_dir / 'workouts.json'
    if workouts_file.exists():
        workouts = json.load(open(workouts_file))
    else:
        workouts = []

    # Load individual workout files
    workout_files = sorted(hk_dir.glob('2*.json'))
    print(f"Found {len(workout_files)} workout files")

    converted = 0
    skipped = 0

    total = len(workout_files)
    for i, wf in enumerate(workout_files, 1):
        data = json.load(open(wf))
        workout = data['workout']
        metrics = data['metrics']
        activity = workout.get('activity_type', 'unknown')

        if args.activity and args.activity.lower() not in activity.lower():
            continue

        # Count total metric points
        total_points = sum(len(v) for v in metrics.values() if isinstance(v, list))
        if total_points == 0:
            skipped += 1
            print(f"[{i}/{total}] Skipped (no metrics): {wf.name}")
            continue

        # GPS data from HealthKit route
        trackpoints = []
        for pt in data.get('route', []):
            ts = datetime.fromtimestamp(pt['timestamp'], tz=timezone.utc)
            trackpoints.append({
                'time': ts,
                'lat': pt['latitude'],
                'lon': pt['longitude'],
                'elevation': pt['altitude'],
            })

        try:
            fit_file = create_fit(workout, metrics, trackpoints)

            start = parse_iso(workout['start_date'])
            year_month_dir = output_dir / str(start.year) / f"{start.month:02d}"
            year_month_dir.mkdir(parents=True, exist_ok=True)

            filename = f"{start.strftime('%Y-%m-%d_%H%M%S')}_{activity.title()}.fit"
            fit_file.to_file(str(year_month_dir / filename))

            hr_count = len(metrics.get('heart_rate', []))
            print(f"[{i}/{total}] {filename} ({total_points} points, {hr_count} HR, {len(trackpoints)} GPS)")
            converted += 1
        except Exception as e:
            print(f"[{i}/{total}] Error: {wf.name} — {e}")

    print(f"\nDone: {converted} converted, {skipped} skipped")
    print(f"Output: {output_dir}")


if __name__ == '__main__':
    main()
