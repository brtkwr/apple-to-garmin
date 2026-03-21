#!/usr/bin/env python3
"""
Convert HealthKit JSON export (from the HealthKitExporter iOS app) to FIT files.
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
from fit_tool.profile.profile_type import Sport, Manufacturer, FileType, Event, EventType

from parser import parse_gpx_file

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

    # Timer start
    event = EventMessage()
    event.event = Event.TIMER
    event.event_type = EventType.START
    event.timestamp = to_fit_ts(start)
    builder.add(event)

    # Merge all streams into time-sorted records
    events = []

    # GPS trackpoints (from GPX or HealthKit route JSON)
    for tp in trackpoints:
        events.append((tp['time'], 'gps', tp))

    # HealthKit metric streams
    metric_map = {
        'heart_rate': 'heart_rate',
        'running_power': 'power',
        'running_speed': 'speed',
        'vertical_oscillation': 'vertical_oscillation',
        'ground_contact_time': 'ground_contact_time',
        'stride_length': 'stride_length',
    }

    for hk_key, fit_key in metric_map.items():
        for point in metrics.get(hk_key, []):
            ts = datetime.fromtimestamp(point['timestamp'], tz=timezone.utc)
            events.append((ts, fit_key, point['value']))

    events.sort(key=lambda e: e[0])

    for ts, source, data in events:
        record = RecordMessage()
        record.timestamp = to_fit_ts(ts)

        if source == 'gps':
            record.position_lat = data.get('lat') or data.get('latitude')
            record.position_long = data.get('lon') or data.get('longitude')
            record.enhanced_altitude = data.get('elevation') or data.get('altitude', 0)
        elif source == 'heart_rate':
            record.heart_rate = min(int(data), 255)
        elif source == 'power':
            record.power = int(data)
        elif source == 'speed':
            record.enhanced_speed = data  # already m/s
        elif source == 'vertical_oscillation':
            record.vertical_oscillation = data * 10  # cm -> mm
        elif source == 'ground_contact_time':
            record.stance_time = data  # already ms
        elif source == 'stride_length':
            record.step_length = data * 1000  # m -> mm

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


def find_gpx_file(workout, routes_dir):
    """Try to find a matching GPX file for a workout by date."""
    if not routes_dir or not routes_dir.exists():
        return None
    start = parse_iso(workout['start_date'])
    # GPX files are named like route_2024-01-02_7.30pm.gpx
    # Search by date prefix
    date_str = start.strftime('%Y-%m-%d')
    for gpx in routes_dir.glob(f'route_{date_str}*.gpx'):
        return gpx
    return None


def main():
    parser = argparse.ArgumentParser(
        description='Convert HealthKit JSON export to FIT for Garmin Connect')
    parser.add_argument('healthkit_dir', help='Path to healthkit_export directory')
    parser.add_argument('--gpx-dir', '-g', help='Path to workout-routes directory for GPS data')
    parser.add_argument('--output', '-o', help='Output directory for FIT files')
    parser.add_argument('--activity', '-a', help='Filter by activity type')
    args = parser.parse_args()

    hk_dir = Path(args.healthkit_dir)
    routes_dir = Path(args.gpx_dir) if args.gpx_dir else None
    output_dir = Path(args.output) if args.output else Path('fit_files_hk')
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

    for wf in workout_files:
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
            continue

        # GPS data — prefer HealthKit route, fall back to GPX files
        route_data = data.get('route', [])
        if route_data:
            trackpoints = []
            for pt in route_data:
                ts = datetime.fromtimestamp(pt['timestamp'], tz=timezone.utc)
                trackpoints.append({
                    'time': ts,
                    'lat': pt['latitude'],
                    'lon': pt['longitude'],
                    'elevation': pt['altitude'],
                })
        elif routes_dir:
            gpx_file = find_gpx_file(workout, routes_dir)
            trackpoints = parse_gpx_file(gpx_file) if gpx_file else []
        else:
            trackpoints = []

        try:
            fit_file = create_fit(workout, metrics, trackpoints)

            start = parse_iso(workout['start_date'])
            year_month_dir = output_dir / str(start.year) / f"{start.month:02d}"
            year_month_dir.mkdir(parents=True, exist_ok=True)

            filename = f"{start.strftime('%Y-%m-%d_%H%M%S')}_{activity.title()}.fit"
            fit_file.to_file(str(year_month_dir / filename))

            hr_count = len(metrics.get('heart_rate', []))
            print(f"Converted: {filename} ({total_points} points, {hr_count} HR, {len(trackpoints)} GPS)")
            converted += 1
        except Exception as e:
            print(f"Error converting {wf.name}: {e}")

    print(f"\nConverted {converted} workouts to {output_dir}")
    if skipped:
        print(f"Skipped {skipped} workouts with no metric data")


if __name__ == '__main__':
    main()
