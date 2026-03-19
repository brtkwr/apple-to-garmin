#!/usr/bin/env python3
"""
Convert Apple Watch workouts from Apple Health export to FIT format for Garmin Connect.
Preserves per-second heart rate, running power, stride length, vertical oscillation,
ground contact time, and GPS data.
"""

import xml.etree.ElementTree as ET
from bisect import bisect_left
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

# Apple Health quantity type identifiers we care about
METRIC_TYPES = {
    'HKQuantityTypeIdentifierHeartRate': 'heart_rate',
    'HKQuantityTypeIdentifierRunningPower': 'power',
    'HKQuantityTypeIdentifierRunningSpeed': 'speed',
    'HKQuantityTypeIdentifierRunningVerticalOscillation': 'vertical_oscillation',
    'HKQuantityTypeIdentifierRunningGroundContactTime': 'ground_contact_time',
    'HKQuantityTypeIdentifierRunningStrideLength': 'stride_length',
}

SPORT_MAP = {
    'HKWorkoutActivityTypeRunning': Sport.RUNNING,
    'HKWorkoutActivityTypeWalking': Sport.WALKING,
    'HKWorkoutActivityTypeCycling': Sport.CYCLING,
    'HKWorkoutActivityTypeHiking': Sport.HIKING,
    'HKWorkoutActivityTypeSwimming': Sport.SWIMMING,
}


def to_fit_ts(dt):
    """Convert datetime to milliseconds since Unix epoch (fit-tool's expected input)."""
    return int(dt.timestamp() * 1000)


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


class AppleToFitConverter:
    def __init__(self, export_dir):
        self.export_dir = Path(export_dir)
        self.export_xml = self.export_dir / "export.xml"
        self.routes_dir = self.export_dir / "workout-routes"
        self.metrics = {}

    def parse_metrics(self, root):
        """Parse per-second metric records from export.xml."""
        for metric_type, name in METRIC_TYPES.items():
            self.metrics[name] = MetricIndex()

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
                self.metrics[name].add(dt, float(value))
            except (ValueError, TypeError):
                continue

        for name, index in self.metrics.items():
            index.sort()
            print(f"  {name}: {len(index)} records")

    def parse_gpx_file(self, gpx_file):
        """Parse GPX file and extract trackpoints."""
        if not gpx_file or not gpx_file.exists():
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
                trackpoints.append({
                    'lat': lat,
                    'lon': lon,
                    'elevation': elevation,
                    'time': timestamp,
                })
            return trackpoints
        except Exception as e:
            print(f"Error parsing GPX file {gpx_file}: {e}")
            return []

    def extract_workout(self, workout_elem):
        """Extract workout metadata from XML element."""
        activity_type = workout_elem.get('workoutActivityType', '')
        start_date = workout_elem.get('startDate', '')
        end_date = workout_elem.get('endDate', '')
        duration = float(workout_elem.get('duration', 0))

        if not start_date or not end_date:
            return None

        sport = SPORT_MAP.get(activity_type, Sport.GENERIC)
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)

        workout = {
            'sport': sport,
            'sport_name': sport.name.lower().replace('_', ' '),
            'start_time': start_dt,
            'end_time': end_dt,
            'duration_seconds': duration * 60,
            'heart_rate_avg': None,
            'distance_km': None,
            'calories': None,
            'gpx_file': None,
        }

        for stat in workout_elem.findall('.//WorkoutStatistics'):
            stat_type = stat.get('type', '')
            if 'HeartRate' in stat_type:
                workout['heart_rate_avg'] = float(stat.get('average', 0))
            elif 'DistanceWalkingRunning' in stat_type or 'DistanceCycling' in stat_type:
                workout['distance_km'] = float(stat.get('sum', 0))
            elif 'ActiveEnergyBurned' in stat_type:
                workout['calories'] = float(stat.get('sum', 0))

        route_elem = workout_elem.find('.//WorkoutRoute/FileReference')
        if route_elem is not None:
            gpx_path = route_elem.get('path', '')
            if gpx_path.startswith('/workout-routes/'):
                gpx_filename = gpx_path.replace('/workout-routes/', '')
                workout['gpx_file'] = self.routes_dir / gpx_filename

        return workout

    def create_fit(self, workout, trackpoints):
        """Create a FIT file for a single workout."""
        builder = FitFileBuilder()
        start = workout['start_time']
        end = workout['end_time']

        # File ID
        file_id = FileIdMessage()
        file_id.type = FileType.ACTIVITY
        file_id.manufacturer = Manufacturer.DEVELOPMENT
        file_id.product = 0
        file_id.serial_number = 0
        file_id.time_created = to_fit_ts(start)
        builder.add(file_id)

        # Timer start event
        event = EventMessage()
        event.event = Event.TIMER
        event.event_type = EventType.START
        event.timestamp = to_fit_ts(start)
        builder.add(event)

        # Records (trackpoints with metrics)
        for tp in trackpoints:
            record = RecordMessage()
            record.timestamp = to_fit_ts(tp['time'])
            record.position_lat = tp['lat']
            record.position_long = tp['lon']
            record.enhanced_altitude = tp['elevation']

            # Heart rate — per-second lookup, fall back to workout average
            hr = self.metrics['heart_rate'].lookup(tp['time'])
            if hr is None and workout['heart_rate_avg']:
                hr = workout['heart_rate_avg']
            if hr is not None:
                record.heart_rate = min(int(hr), 255)

            # Running power (watts)
            power = self.metrics['power'].lookup(tp['time'])
            if power is not None:
                record.power = int(power)

            # Speed (Apple exports km/hr, FIT wants m/s)
            speed = self.metrics['speed'].lookup(tp['time'])
            if speed is not None:
                record.enhanced_speed = speed / 3.6  # km/h -> m/s

            # Vertical oscillation (Apple exports cm, FIT wants mm)
            vo = self.metrics['vertical_oscillation'].lookup(tp['time'])
            if vo is not None:
                record.vertical_oscillation = vo * 10  # cm -> mm

            # Ground contact time (Apple exports ms, FIT wants ms)
            gct = self.metrics['ground_contact_time'].lookup(tp['time'])
            if gct is not None:
                record.stance_time = gct

            # Stride length (Apple exports m, FIT wants mm)
            sl = self.metrics['stride_length'].lookup(tp['time'])
            if sl is not None:
                record.step_length = sl * 1000  # m -> mm

            builder.add(record)

        # Timer stop event
        event_stop = EventMessage()
        event_stop.event = Event.TIMER
        event_stop.event_type = EventType.STOP_ALL
        event_stop.timestamp = to_fit_ts(end)
        builder.add(event_stop)

        # Lap
        lap = LapMessage()
        lap.timestamp = to_fit_ts(end)
        lap.start_time = to_fit_ts(start)
        lap.total_elapsed_time = workout['duration_seconds']
        lap.total_timer_time = workout['duration_seconds']
        lap.sport = workout['sport']
        if workout['distance_km']:
            lap.total_distance = workout['distance_km'] * 1000  # km -> m  # km -> m
        if workout['calories']:
            lap.total_calories = int(workout['calories'])
        builder.add(lap)

        # Session
        session = SessionMessage()
        session.timestamp = to_fit_ts(end)
        session.start_time = to_fit_ts(start)
        session.total_elapsed_time = workout['duration_seconds']
        session.total_timer_time = workout['duration_seconds']
        session.sport = workout['sport']
        session.first_lap_index = 0
        session.num_laps = 1
        if workout['distance_km']:
            session.total_distance = workout['distance_km'] * 1000  # km -> m
        if workout['calories']:
            session.total_calories = int(workout['calories'])
        builder.add(session)

        # Activity
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
        tree = ET.parse(self.export_xml)
        root = tree.getroot()

        print("Parsing metric records...")
        self.parse_metrics(root)

        all_workouts = root.findall('.//Workout')
        print(f"Found {len(all_workouts)} total workouts")

        workouts = []
        for workout_elem in all_workouts:
            source_name = workout_elem.get('sourceName', '')
            if 'Apple Watch' in source_name or 'Bharat' in source_name:
                workout = self.extract_workout(workout_elem)
                if workout:
                    workouts.append(workout)

        print(f"Found {len(workouts)} Apple Watch workouts")

        if activity_filter:
            workouts = [w for w in workouts if activity_filter.lower() in w['sport_name']]
            print(f"Filtered to {len(workouts)} {activity_filter} workouts")

        converted = 0
        for workout in workouts:
            trackpoints = self.parse_gpx_file(workout['gpx_file'])
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
