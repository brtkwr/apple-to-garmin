#!/usr/bin/env python3
"""
Convert Apple Watch workouts from Apple Health export to FIT format for Garmin Connect.
Preserves per-second heart rate, running power, stride length, vertical oscillation,
ground contact time, and GPS data.
"""

import argparse
from pathlib import Path

from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.profile_type import Sport, Manufacturer, FileType, Event, EventType

from parser import MetricIndex, parse_gpx_file, parse_export, METRIC_TYPES, ACTIVITY_TYPE_MAP

# FIT-specific sport mapping (maps the human-readable name from parser to fit-tool Sport enum)
SPORT_MAP = {
    'Running': Sport.RUNNING,
    'Walking': Sport.WALKING,
    'Biking': Sport.CYCLING,
    'Hiking': Sport.HIKING,
    'Swimming': Sport.SWIMMING,
}

# Also expose the legacy Apple-type -> Sport mapping for backward compatibility in tests
APPLE_SPORT_MAP = {
    'HKWorkoutActivityTypeRunning': Sport.RUNNING,
    'HKWorkoutActivityTypeWalking': Sport.WALKING,
    'HKWorkoutActivityTypeCycling': Sport.CYCLING,
    'HKWorkoutActivityTypeHiking': Sport.HIKING,
    'HKWorkoutActivityTypeSwimming': Sport.SWIMMING,
}


def to_fit_ts(dt):
    """Convert datetime to milliseconds since Unix epoch (fit-tool's expected input)."""
    return int(dt.timestamp() * 1000)


class AppleToFitConverter:
    def __init__(self, export_dir):
        self.export_dir = Path(export_dir)
        self.export_xml = self.export_dir / "export.xml"
        self.routes_dir = self.export_dir / "workout-routes"
        self.metrics = {}

    def parse_gpx_file(self, gpx_file):
        """Parse GPX file and extract trackpoints."""
        return parse_gpx_file(gpx_file)

    def parse_metrics(self, root):
        """Parse per-second metric records from an already-parsed XML root.

        This method exists for backward compatibility with tests that call it directly.
        """
        from parser import METRIC_TYPES as _MT
        self.metrics = {name: MetricIndex() for name in _MT.values()}

        for record in root.findall('.//Record'):
            record_type = record.get('type', '')
            if record_type not in _MT:
                continue
            name = _MT[record_type]
            start_date = record.get('startDate', '')
            value = record.get('value', '')
            if not start_date or not value:
                continue
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(start_date)
                self.metrics[name].add(dt, float(value))
            except (ValueError, TypeError):
                continue

        for name, index in self.metrics.items():
            index.sort()
            print(f"  {name}: {len(index)} records")

    def extract_workout(self, workout_elem):
        """Extract workout metadata from XML element.

        Returns a dict compatible with create_fit (includes fit-tool Sport enum).
        """
        from parser import _extract_workout
        w = _extract_workout(workout_elem, self.routes_dir)
        if w is None:
            return None

        fit_sport = SPORT_MAP.get(w['sport'], Sport.GENERIC)
        return {
            'sport': fit_sport,
            'sport_name': w['sport'].lower(),
            'start_time': w['start_time'],
            'end_time': w['end_time'],
            'duration_seconds': w['duration_seconds'],
            'heart_rate_avg': w['heart_rate']['avg'] if w['heart_rate'] else None,
            'distance_km': w['distance_km'],
            'calories': w['calories'],
            'gpx_file': w['gpx_file'],
        }

    def create_fit(self, workout, trackpoints):
        """Create a FIT file for a single workout."""
        builder = FitFileBuilder()
        start = workout['start_time']
        end = workout['end_time']

        file_id = FileIdMessage()
        file_id.type = FileType.ACTIVITY
        file_id.manufacturer = Manufacturer.DEVELOPMENT
        file_id.product = 0
        file_id.serial_number = 0
        file_id.time_created = to_fit_ts(start)
        builder.add(file_id)

        event = EventMessage()
        event.event = Event.TIMER
        event.event_type = EventType.START
        event.timestamp = to_fit_ts(start)
        builder.add(event)

        # Merge all data streams into time-sorted FIT records.
        # Each source (GPS, HR, power, etc.) emits records at its own
        # natural timestamps rather than interpolating.
        events = []

        # GPS trackpoints
        for tp in trackpoints:
            events.append((tp['time'], 'gps', tp))

        # Metric records (HR, power, speed, etc.) within the workout window
        for name, index in self.metrics.items():
            for i, ts in enumerate(index.timestamps):
                if start <= ts <= end:
                    events.append((ts, name, index.values[i]))

        events.sort(key=lambda e: e[0])

        for ts, source, data in events:
            record = RecordMessage()
            record.timestamp = to_fit_ts(ts)

            if source == 'gps':
                record.position_lat = data['lat']
                record.position_long = data['lon']
                record.enhanced_altitude = data['elevation']
            elif source == 'heart_rate':
                record.heart_rate = min(int(data), 255)
            elif source == 'power':
                record.power = int(data)
            elif source == 'speed':
                record.enhanced_speed = data / 3.6  # km/h -> m/s
            elif source == 'vertical_oscillation':
                record.vertical_oscillation = data * 10  # cm -> mm
            elif source == 'ground_contact_time':
                record.stance_time = data  # ms
            elif source == 'stride_length':
                record.step_length = data * 1000  # m -> mm

            builder.add(record)

        event_stop = EventMessage()
        event_stop.event = Event.TIMER
        event_stop.event_type = EventType.STOP_ALL
        event_stop.timestamp = to_fit_ts(end)
        builder.add(event_stop)

        lap = LapMessage()
        lap.timestamp = to_fit_ts(end)
        lap.start_time = to_fit_ts(start)
        lap.total_elapsed_time = workout['duration_seconds']
        lap.total_timer_time = workout['duration_seconds']
        lap.sport = workout['sport']
        if workout['distance_km']:
            lap.total_distance = workout['distance_km'] * 1000
        if workout['calories']:
            lap.total_calories = int(workout['calories'])
        builder.add(lap)

        session = SessionMessage()
        session.timestamp = to_fit_ts(end)
        session.start_time = to_fit_ts(start)
        session.total_elapsed_time = workout['duration_seconds']
        session.total_timer_time = workout['duration_seconds']
        session.sport = workout['sport']
        session.first_lap_index = 0
        session.num_laps = 1
        if workout['distance_km']:
            session.total_distance = workout['distance_km'] * 1000
        if workout['calories']:
            session.total_calories = int(workout['calories'])
        builder.add(session)

        activity = ActivityMessage()
        activity.timestamp = to_fit_ts(end)
        activity.num_sessions = 1
        activity.total_timer_time = workout['duration_seconds']
        builder.add(activity)

        return builder.build()

    def convert_workouts(self, output_dir=None, activity_filter=None):
        """Convert all Apple Watch workouts to FIT files."""
        if output_dir is None:
            output_dir = self.export_dir / "fit_files"
        else:
            output_dir = Path(output_dir)
        output_dir.mkdir(exist_ok=True)

        print("Parsing export.xml...")
        workouts_raw, metrics = parse_export(self.export_xml)
        self.metrics = metrics

        # Convert parser workouts to FIT-specific shape
        workouts = []
        for w in workouts_raw:
            fit_sport = SPORT_MAP.get(w['sport'], Sport.GENERIC)
            workouts.append({
                'sport': fit_sport,
                'sport_name': w['sport'].lower(),
                'start_time': w['start_time'],
                'end_time': w['end_time'],
                'duration_seconds': w['duration_seconds'],
                'heart_rate_avg': w['heart_rate']['avg'] if w['heart_rate'] else None,
                'distance_km': w['distance_km'],
                'calories': w['calories'],
                'gpx_file': w['gpx_file'],
            })

        if activity_filter:
            workouts = [w for w in workouts if activity_filter.lower() in w['sport_name']]
            print(f"Filtered to {len(workouts)} {activity_filter} workouts")

        converted = 0
        for workout in workouts:
            trackpoints = parse_gpx_file(workout['gpx_file'])
            if not trackpoints:
                continue

            try:
                fit_file = self.create_fit(workout, trackpoints)

                start = workout['start_time']
                year_month_dir = output_dir / str(start.year) / f"{start.month:02d}"
                year_month_dir.mkdir(parents=True, exist_ok=True)

                filename = f"{start.strftime('%Y-%m-%d_%H%M%S')}_{workout['sport'].name.title()}.fit"
                output_file = year_month_dir / filename
                fit_file.to_file(str(output_file))

                print(f"Converted: {filename}")
                print(f"  Sport: {workout['sport_name']}")
                print(f"  Duration: {workout['duration_seconds'] / 60:.1f} min")
                print(f"  Trackpoints: {len(trackpoints)}")
                if workout['distance_km']:
                    print(f"  Distance: {workout['distance_km']:.2f} km")
                print()
                converted += 1
            except Exception as e:
                print(f"Error converting {workout['start_time']}: {e}")

        print(f"\nConverted {converted} workouts to {output_dir}")
        return converted


def main():
    parser = argparse.ArgumentParser(description='Convert Apple Watch workouts to FIT for Garmin Connect')
    parser.add_argument('export_dir', help='Path to Apple Health export directory')
    parser.add_argument('--output', '-o', help='Output directory for FIT files')
    parser.add_argument('--activity', '-a', help='Filter by activity type (running, walking, etc.)')
    args = parser.parse_args()

    converter = AppleToFitConverter(args.export_dir)
    converter.convert_workouts(args.output, args.activity)


if __name__ == '__main__':
    main()
