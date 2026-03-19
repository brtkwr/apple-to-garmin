#!/usr/bin/env python3
"""
Convert Apple Watch workouts from Apple Health export to TCX format for Garmin Connect.
Combines workout metadata, heart rate data, and GPS routes from GPX files.
"""

import xml.etree.ElementTree as ET
import argparse
from pathlib import Path

from parser import MetricIndex, parse_gpx_file, parse_export, ACTIVITY_TYPE_MAP


class AppleWorkoutConverter:
    def __init__(self, export_dir):
        self.export_dir = Path(export_dir)
        self.export_xml = self.export_dir / "export.xml"
        self.routes_dir = self.export_dir / "workout-routes"
        self._hr_index = MetricIndex()

    def parse_apple_workouts(self):
        """Parse Apple Watch workouts from export.xml."""
        workouts, metrics = parse_export(self.export_xml)
        self._hr_index = metrics['heart_rate']
        # Adapt to legacy TCX dict shape expected by create_tcx / create_tcx_no_hr
        return [self._to_tcx_workout(w) for w in workouts]

    @staticmethod
    def _to_tcx_workout(w):
        """Convert a parser workout dict to the legacy TCX dict shape."""
        return {
            'sport': w['sport'],
            'start_time': w['start_time'],
            'end_time': w['end_time'],
            'duration_minutes': w['duration_seconds'] / 60,
            'heart_rate': w['heart_rate'],
            'distance': w['distance_km'],
            'calories': w['calories'],
            'elevation_gain': w['elevation_gain'],
            'gpx_file': w['gpx_file'],
        }

    def convert_activity_type(self, apple_type):
        """Convert Apple workout type to TCX sport type."""
        return ACTIVITY_TYPE_MAP.get(apple_type, 'Other')

    @staticmethod
    def parse_apple_date(date_str):
        """Parse Apple Health date format to datetime."""
        from datetime import datetime
        return datetime.fromisoformat(date_str)

    @staticmethod
    def parse_gpx_file(gpx_file):
        """Parse GPX file and extract trackpoints."""
        return parse_gpx_file(gpx_file)

    def lookup_heart_rate(self, timestamp, max_gap_seconds=30):
        """Find the nearest heart rate record for a given timestamp."""
        return self._hr_index.lookup(timestamp, max_gap_seconds)

    def create_tcx(self, workout_data):
        """Create TCX format XML for a single workout."""
        tcx = ET.Element('TrainingCenterDatabase')
        tcx.set('xmlns', 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2')
        tcx.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')
        tcx.set('xsi:schemaLocation',
                'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2 '
                'http://www.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd')

        activities = ET.SubElement(tcx, 'Activities')
        activity = ET.SubElement(activities, 'Activity', Sport=workout_data['sport'])

        activity_id = ET.SubElement(activity, 'Id')
        activity_id.text = workout_data['start_time'].strftime('%Y-%m-%dT%H:%M:%S.%fZ')

        lap = ET.SubElement(activity, 'Lap',
                            StartTime=workout_data['start_time'].strftime('%Y-%m-%dT%H:%M:%S.%fZ'))

        total_time = ET.SubElement(lap, 'TotalTimeSeconds')
        total_time.text = str(workout_data['duration_minutes'] * 60)

        if workout_data['distance']:
            distance_m = ET.SubElement(lap, 'DistanceMeters')
            distance_m.text = str(workout_data['distance'] * 1000)

        if workout_data['calories']:
            calories = ET.SubElement(lap, 'Calories')
            calories.text = str(int(workout_data['calories']))

        if workout_data['heart_rate']:
            avg_hr = ET.SubElement(lap, 'AverageHeartRateBpm')
            avg_hr_value = ET.SubElement(avg_hr, 'Value')
            avg_hr_value.text = str(int(workout_data['heart_rate']['avg']))

            max_hr = ET.SubElement(lap, 'MaximumHeartRateBpm')
            max_hr_value = ET.SubElement(max_hr, 'Value')
            max_hr_value.text = str(workout_data['heart_rate']['max'])

        trackpoints = parse_gpx_file(workout_data['gpx_file'])

        if trackpoints:
            track = ET.SubElement(lap, 'Track')
            for tp in trackpoints:
                trackpoint = ET.SubElement(track, 'Trackpoint')

                time_elem = ET.SubElement(trackpoint, 'Time')
                time_elem.text = tp['time'].strftime('%Y-%m-%dT%H:%M:%S.%fZ')

                position = ET.SubElement(trackpoint, 'Position')
                lat_elem = ET.SubElement(position, 'LatitudeDegrees')
                lat_elem.text = str(tp['lat'])
                lon_elem = ET.SubElement(position, 'LongitudeDegrees')
                lon_elem.text = str(tp['lon'])

                alt_elem = ET.SubElement(trackpoint, 'AltitudeMeters')
                alt_elem.text = str(tp['elevation'])

                hr = self.lookup_heart_rate(tp['time'])
                if hr is None and workout_data['heart_rate']:
                    hr = int(workout_data['heart_rate']['avg'])
                if hr is not None:
                    hr_elem = ET.SubElement(trackpoint, 'HeartRateBpm')
                    hr_value = ET.SubElement(hr_elem, 'Value')
                    hr_value.text = str(hr)

        creator = ET.SubElement(activity, 'Creator')
        creator.set('xsi:type', 'Device_t')
        name_elem = ET.SubElement(creator, 'Name')
        name_elem.text = 'Apple Watch'
        unit_id = ET.SubElement(creator, 'UnitId')
        unit_id.text = '0'
        product_id = ET.SubElement(creator, 'ProductID')
        product_id.text = '0'

        return tcx

    def create_tcx_no_hr(self, workout_data):
        """Create TCX format XML for a workout without heart rate data."""
        tcx = ET.Element('TrainingCenterDatabase')
        tcx.set('xmlns', 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2')
        tcx.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')
        tcx.set('xsi:schemaLocation',
                'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2 '
                'http://www.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd')

        activities = ET.SubElement(tcx, 'Activities')
        activity = ET.SubElement(activities, 'Activity', Sport=workout_data['sport'])

        activity_id = ET.SubElement(activity, 'Id')
        activity_id.text = workout_data['start_time'].strftime('%Y-%m-%dT%H:%M:%S.%fZ')

        lap = ET.SubElement(activity, 'Lap',
                            StartTime=workout_data['start_time'].strftime('%Y-%m-%dT%H:%M:%S.%fZ'))

        total_time = ET.SubElement(lap, 'TotalTimeSeconds')
        total_time.text = str(workout_data['duration_minutes'] * 60)

        if workout_data['distance']:
            distance_m = ET.SubElement(lap, 'DistanceMeters')
            distance_m.text = str(workout_data['distance'] * 1000)

        if workout_data['calories']:
            calories = ET.SubElement(lap, 'Calories')
            calories.text = str(int(workout_data['calories']))

        trackpoints = parse_gpx_file(workout_data['gpx_file'])

        if trackpoints:
            track = ET.SubElement(lap, 'Track')
            for tp in trackpoints:
                trackpoint = ET.SubElement(track, 'Trackpoint')

                time_elem = ET.SubElement(trackpoint, 'Time')
                time_elem.text = tp['time'].strftime('%Y-%m-%dT%H:%M:%S.%fZ')

                position = ET.SubElement(trackpoint, 'Position')
                lat_elem = ET.SubElement(position, 'LatitudeDegrees')
                lat_elem.text = str(tp['lat'])
                lon_elem = ET.SubElement(position, 'LongitudeDegrees')
                lon_elem.text = str(tp['lon'])

                alt_elem = ET.SubElement(trackpoint, 'AltitudeMeters')
                alt_elem.text = str(tp['elevation'])

        creator = ET.SubElement(activity, 'Creator')
        creator.set('xsi:type', 'Device_t')
        name_elem = ET.SubElement(creator, 'Name')
        name_elem.text = 'Apple Watch'
        unit_id = ET.SubElement(creator, 'UnitId')
        unit_id.text = '0'
        product_id = ET.SubElement(creator, 'ProductID')
        product_id.text = '0'

        return tcx

    def convert_workouts(self, output_dir=None, activity_filter=None):
        """Convert all Apple Watch workouts to TCX files."""
        if output_dir is None:
            output_dir = self.export_dir / "tcx_files"
        else:
            output_dir = Path(output_dir)

        output_dir.mkdir(exist_ok=True)

        workouts = self.parse_apple_workouts()

        if activity_filter:
            workouts = [w for w in workouts if activity_filter.lower() in w['sport'].lower()]

        no_hr_dir = output_dir / "no_heart_rate"
        no_hr_dir.mkdir(exist_ok=True)

        converted_count = 0
        no_hr_count = 0

        for workout in workouts:
            if not workout['heart_rate']:
                try:
                    tcx = self.create_tcx_no_hr(workout)

                    start_time = workout['start_time']
                    year_month_no_hr_dir = no_hr_dir / str(start_time.year) / f"{start_time.month:02d}"
                    year_month_no_hr_dir.mkdir(parents=True, exist_ok=True)

                    start_time_str = start_time.strftime('%Y-%m-%d_%H%M%S')
                    filename = f"{start_time_str}_{workout['sport']}.tcx"
                    output_file = year_month_no_hr_dir / filename
                    tree = ET.ElementTree(tcx)
                    ET.indent(tree, space="  ", level=0)
                    tree.write(output_file, encoding='utf-8', xml_declaration=True)
                    no_hr_count += 1
                except Exception as e:
                    print(f"Error converting no-HR workout from {workout['start_time']}: {e}")
                continue

            try:
                tcx = self.create_tcx(workout)

                start_time = workout['start_time']
                year_month_dir = output_dir / str(start_time.year) / f"{start_time.month:02d}"
                year_month_dir.mkdir(parents=True, exist_ok=True)

                start_time_str = start_time.strftime('%Y-%m-%d_%H%M%S')
                filename = f"{start_time_str}_{workout['sport']}.tcx"

                output_file = year_month_dir / filename
                tree = ET.ElementTree(tcx)
                ET.indent(tree, space="  ", level=0)
                tree.write(output_file, encoding='utf-8', xml_declaration=True)

                print(f"Converted: {filename}")
                print(f"  Sport: {workout['sport']}")
                print(f"  Duration: {workout['duration_minutes']:.1f} min")
                if workout['distance']:
                    print(f"  Distance: {workout['distance']:.2f} km")
                if workout['heart_rate']:
                    hr = workout['heart_rate']
                    print(f"  HR: {hr['avg']:.0f} avg, {hr['min']}-{hr['max']} range")
                print()

                converted_count += 1

            except Exception as e:
                print(f"Error converting workout from {workout['start_time']}: {e}")

        print(f"\nSummary:")
        print(f"  Converted {converted_count} workouts WITH heart rate to {output_dir}")
        print(f"  Converted {no_hr_count} workouts WITHOUT heart rate to {no_hr_dir}")
        print(f"  Total: {converted_count + no_hr_count} workouts converted")
        return converted_count + no_hr_count


def main():
    parser = argparse.ArgumentParser(description='Convert Apple Watch workouts to TCX for Garmin Connect')
    parser.add_argument('export_dir', help='Path to Apple Health export directory')
    parser.add_argument('--output', '-o', help='Output directory for TCX files')
    parser.add_argument('--activity', '-a', help='Filter by activity type (running, walking, etc.)')

    args = parser.parse_args()

    converter = AppleWorkoutConverter(args.export_dir)
    converter.convert_workouts(args.output, args.activity)


if __name__ == '__main__':
    main()
