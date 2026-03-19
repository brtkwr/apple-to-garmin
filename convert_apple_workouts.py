#!/usr/bin/env python3
"""
Convert Apple Watch workouts from Apple Health export to TCX format for Garmin Connect.
Combines workout metadata, heart rate data, and GPS routes from GPX files.
"""

import xml.etree.ElementTree as ET
import os
import re
from bisect import bisect_left
from datetime import datetime, timezone
from pathlib import Path
import argparse

class AppleWorkoutConverter:
    def __init__(self, export_dir):
        self.export_dir = Path(export_dir)
        self.export_xml = self.export_dir / "export.xml"
        self.routes_dir = self.export_dir / "workout-routes"
        
    def parse_heart_rate_records(self, root):
        """Parse per-second heart rate records from export.xml into a sorted list."""
        hr_records = []
        for record in root.findall('.//Record[@type="HKQuantityTypeIdentifierHeartRate"]'):
            start_date = record.get('startDate', '')
            value = record.get('value', '')
            if not start_date or not value:
                continue
            try:
                dt = self.parse_apple_date(start_date)
                hr_records.append((dt, int(float(value))))
            except (ValueError, TypeError):
                continue
        hr_records.sort(key=lambda x: x[0])
        print(f"Parsed {len(hr_records)} per-second heart rate records")
        self._hr_timestamps = [r[0] for r in hr_records]
        self._hr_values = [r[1] for r in hr_records]

    def lookup_heart_rate(self, timestamp, max_gap_seconds=30):
        """Find the nearest heart rate record for a given timestamp."""
        if not self._hr_timestamps:
            return None
        idx = bisect_left(self._hr_timestamps, timestamp)
        candidates = []
        if idx < len(self._hr_timestamps):
            candidates.append(idx)
        if idx > 0:
            candidates.append(idx - 1)
        best = None
        best_gap = None
        for i in candidates:
            gap = abs((self._hr_timestamps[i] - timestamp).total_seconds())
            if best_gap is None or gap < best_gap:
                best_gap = gap
                best = i
        if best is not None and best_gap <= max_gap_seconds:
            return self._hr_values[best]
        return None

    def parse_apple_workouts(self):
        """Parse Apple Watch workouts from export.xml"""
        tree = ET.parse(self.export_xml)
        root = tree.getroot()

        self.parse_heart_rate_records(root)

        workouts = []
        all_workouts = root.findall('.//Workout')
        print(f"Found {len(all_workouts)} total workouts")
        
        apple_watch_count = 0
        for i, workout in enumerate(all_workouts):
            source_name = workout.get('sourceName', '')
            if i < 5:  # Show first 5 source names for debugging
                print(f"Workout {i}: source='{source_name}'")
            if 'Apple Watch' in source_name or 'Bharat' in source_name:
                apple_watch_count += 1
                workout_data = self.extract_workout_data(workout)
                if workout_data:
                    workouts.append(workout_data)
                    
        print(f"Found {apple_watch_count} Apple Watch workouts")
        print(f"Successfully parsed {len(workouts)} workouts with data")
        
        return workouts
    
    def extract_workout_data(self, workout_elem):
        """Extract workout data from XML element"""
        # Basic workout info
        activity_type = workout_elem.get('workoutActivityType', '')
        start_date = workout_elem.get('startDate', '')
        end_date = workout_elem.get('endDate', '')
        duration = float(workout_elem.get('duration', 0))
        
        if not start_date or not end_date:
            return None
            
        # Convert activity type
        sport = self.convert_activity_type(activity_type)
        
        # Parse dates
        start_dt = self.parse_apple_date(start_date)
        end_dt = self.parse_apple_date(end_date)
        
        workout_data = {
            'sport': sport,
            'start_time': start_dt,
            'end_time': end_dt,
            'duration_minutes': duration,
            'heart_rate': None,
            'distance': None,
            'calories': None,
            'elevation_gain': None,
            'gpx_file': None
        }
        
        # Extract workout statistics
        for stat in workout_elem.findall('.//WorkoutStatistics'):
            stat_type = stat.get('type', '')
            if 'HeartRate' in stat_type:
                workout_data['heart_rate'] = {
                    'avg': float(stat.get('average', 0)),
                    'min': int(stat.get('minimum', 0)),
                    'max': int(stat.get('maximum', 0))
                }
            elif 'DistanceWalkingRunning' in stat_type:
                workout_data['distance'] = float(stat.get('sum', 0))
            elif 'ActiveEnergyBurned' in stat_type:
                workout_data['calories'] = float(stat.get('sum', 0))
        
        # Extract elevation gain
        elevation_elem = workout_elem.find('.//MetadataEntry[@key="HKElevationAscended"]')
        if elevation_elem is not None:
            elevation_str = elevation_elem.get('value', '0 cm')
            elevation_cm = float(elevation_str.replace(' cm', ''))
            workout_data['elevation_gain'] = elevation_cm / 100  # Convert to meters
        
        # Find corresponding GPX file
        route_elem = workout_elem.find('.//WorkoutRoute/FileReference')
        if route_elem is not None:
            gpx_path = route_elem.get('path', '')
            if gpx_path.startswith('/workout-routes/'):
                gpx_filename = gpx_path.replace('/workout-routes/', '')
                workout_data['gpx_file'] = self.routes_dir / gpx_filename
        
        return workout_data
    
    def convert_activity_type(self, apple_type):
        """Convert Apple workout type to TCX sport type"""
        mapping = {
            'HKWorkoutActivityTypeRunning': 'Running',
            'HKWorkoutActivityTypeWalking': 'Walking',
            'HKWorkoutActivityTypeCycling': 'Biking',
            'HKWorkoutActivityTypeHiking': 'Other',
            'HKWorkoutActivityTypeSwimming': 'Swimming',
        }
        return mapping.get(apple_type, 'Other')
    
    def parse_apple_date(self, date_str):
        """Parse Apple Health date format to datetime"""
        # Format: "2022-10-06 20:04:10 +0100"
        return datetime.fromisoformat(date_str)
    
    def parse_gpx_file(self, gpx_file):
        """Parse GPX file and extract trackpoints"""
        if not gpx_file or not gpx_file.exists():
            return []
        
        try:
            tree = ET.parse(gpx_file)
            root = tree.getroot()
            
            # Handle GPX namespace
            ns = {'gpx': 'http://www.topografix.com/GPX/1/1'}
            
            trackpoints = []
            for trkpt in root.findall('.//gpx:trkpt', ns):
                lat = float(trkpt.get('lat', 0))
                lon = float(trkpt.get('lon', 0))
                
                # Extract elevation
                ele_elem = trkpt.find('./gpx:ele', ns)
                elevation = float(ele_elem.text) if ele_elem is not None else 0
                
                # Extract time
                time_elem = trkpt.find('./gpx:time', ns)
                if time_elem is not None:
                    timestamp = datetime.fromisoformat(time_elem.text.replace('Z', '+00:00'))
                else:
                    continue
                
                # Extract extensions (speed, heart rate if available)
                extensions = trkpt.find('./gpx:extensions', ns)
                speed = None
                if extensions is not None:
                    speed_elem = extensions.find('./speed')
                    if speed_elem is not None:
                        speed = float(speed_elem.text)
                
                trackpoints.append({
                    'lat': lat,
                    'lon': lon,
                    'elevation': elevation,
                    'time': timestamp,
                    'speed': speed
                })
            
            return trackpoints
        except Exception as e:
            print(f"Error parsing GPX file {gpx_file}: {e}")
            return []
    
    def create_tcx(self, workout_data):
        """Create TCX format XML for a single workout"""
        # TCX root structure
        tcx = ET.Element('TrainingCenterDatabase')
        tcx.set('xmlns', 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2')
        tcx.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')
        tcx.set('xsi:schemaLocation', 
                'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2 '
                'http://www.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd')
        
        # Activities section
        activities = ET.SubElement(tcx, 'Activities')
        activity = ET.SubElement(activities, 'Activity', Sport=workout_data['sport'])
        
        # Activity ID (start time)
        activity_id = ET.SubElement(activity, 'Id')
        activity_id.text = workout_data['start_time'].strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        
        # Lap
        lap = ET.SubElement(activity, 'Lap', StartTime=workout_data['start_time'].strftime('%Y-%m-%dT%H:%M:%S.%fZ'))
        
        # Lap totals
        total_time = ET.SubElement(lap, 'TotalTimeSeconds')
        total_time.text = str(workout_data['duration_minutes'] * 60)
        
        if workout_data['distance']:
            distance_m = ET.SubElement(lap, 'DistanceMeters')
            distance_m.text = str(workout_data['distance'] * 1000)  # Convert km to m
        
        if workout_data['calories']:
            calories = ET.SubElement(lap, 'Calories')
            calories.text = str(int(workout_data['calories']))
        
        # Heart rate summary
        if workout_data['heart_rate']:
            avg_hr = ET.SubElement(lap, 'AverageHeartRateBpm')
            avg_hr_value = ET.SubElement(avg_hr, 'Value')
            avg_hr_value.text = str(int(workout_data['heart_rate']['avg']))
            
            max_hr = ET.SubElement(lap, 'MaximumHeartRateBpm')
            max_hr_value = ET.SubElement(max_hr, 'Value')
            max_hr_value.text = str(workout_data['heart_rate']['max'])
        
        # Parse GPS trackpoints
        trackpoints = self.parse_gpx_file(workout_data['gpx_file'])
        
        if trackpoints:
            track = ET.SubElement(lap, 'Track')
            
            for i, tp in enumerate(trackpoints):
                trackpoint = ET.SubElement(track, 'Trackpoint')
                
                # Time
                time_elem = ET.SubElement(trackpoint, 'Time')
                time_elem.text = tp['time'].strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                
                # Position
                position = ET.SubElement(trackpoint, 'Position')
                lat_elem = ET.SubElement(position, 'LatitudeDegrees')
                lat_elem.text = str(tp['lat'])
                lon_elem = ET.SubElement(position, 'LongitudeDegrees')
                lon_elem.text = str(tp['lon'])
                
                # Altitude
                alt_elem = ET.SubElement(trackpoint, 'AltitudeMeters')
                alt_elem.text = str(tp['elevation'])
                
                # Heart rate — use per-second records, fall back to workout average
                hr = self.lookup_heart_rate(tp['time'])
                if hr is None and workout_data['heart_rate']:
                    hr = int(workout_data['heart_rate']['avg'])
                if hr is not None:
                    hr_elem = ET.SubElement(trackpoint, 'HeartRateBpm')
                    hr_value = ET.SubElement(hr_elem, 'Value')
                    hr_value.text = str(hr)
        
        # Creator/device info
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
        """Create TCX format XML for a workout without heart rate data"""
        # TCX root structure
        tcx = ET.Element('TrainingCenterDatabase')
        tcx.set('xmlns', 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2')
        tcx.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')
        tcx.set('xsi:schemaLocation', 
                'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2 '
                'http://www.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd')
        
        # Activities section
        activities = ET.SubElement(tcx, 'Activities')
        activity = ET.SubElement(activities, 'Activity', Sport=workout_data['sport'])
        
        # Activity ID (start time)
        activity_id = ET.SubElement(activity, 'Id')
        activity_id.text = workout_data['start_time'].strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        
        # Lap
        lap = ET.SubElement(activity, 'Lap', StartTime=workout_data['start_time'].strftime('%Y-%m-%dT%H:%M:%S.%fZ'))
        
        # Lap totals
        total_time = ET.SubElement(lap, 'TotalTimeSeconds')
        total_time.text = str(workout_data['duration_minutes'] * 60)
        
        if workout_data['distance']:
            distance_m = ET.SubElement(lap, 'DistanceMeters')
            distance_m.text = str(workout_data['distance'] * 1000)  # Convert km to m
        
        if workout_data['calories']:
            calories = ET.SubElement(lap, 'Calories')
            calories.text = str(int(workout_data['calories']))
        
        # Parse GPS trackpoints
        trackpoints = self.parse_gpx_file(workout_data['gpx_file'])
        
        if trackpoints:
            track = ET.SubElement(lap, 'Track')
            
            for i, tp in enumerate(trackpoints):
                trackpoint = ET.SubElement(track, 'Trackpoint')
                
                # Time
                time_elem = ET.SubElement(trackpoint, 'Time')
                time_elem.text = tp['time'].strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                
                # Position
                position = ET.SubElement(trackpoint, 'Position')
                lat_elem = ET.SubElement(position, 'LatitudeDegrees')
                lat_elem.text = str(tp['lat'])
                lon_elem = ET.SubElement(position, 'LongitudeDegrees')
                lon_elem.text = str(tp['lon'])
                
                # Altitude
                alt_elem = ET.SubElement(trackpoint, 'AltitudeMeters')
                alt_elem.text = str(tp['elevation'])
        
        # Creator/device info
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
        """Convert all Apple Watch workouts to TCX files"""
        if output_dir is None:
            output_dir = self.export_dir / "tcx_files"
        else:
            output_dir = Path(output_dir)
        
        output_dir.mkdir(exist_ok=True)
        
        workouts = self.parse_apple_workouts()
        
        # Filter by activity type if specified
        if activity_filter:
            workouts = [w for w in workouts if activity_filter.lower() in w['sport'].lower()]
        
        # Create separate folder for workouts without HR data
        no_hr_dir = output_dir / "no_heart_rate"
        no_hr_dir.mkdir(exist_ok=True)
        
        converted_count = 0
        no_hr_count = 0
        
        for workout in workouts:
            if not workout['heart_rate']:
                # Save workout without HR data to separate folder
                try:
                    tcx = self.create_tcx_no_hr(workout)
                    
                    # Organize no-HR workouts by year/month too
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
                
                # Generate filename and organize by year/month
                start_time = workout['start_time']
                year_month_dir = output_dir / str(start_time.year) / f"{start_time.month:02d}"
                year_month_dir.mkdir(parents=True, exist_ok=True)
                
                start_time_str = start_time.strftime('%Y-%m-%d_%H%M%S')
                filename = f"{start_time_str}_{workout['sport']}.tcx"
                
                # Write TCX file
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