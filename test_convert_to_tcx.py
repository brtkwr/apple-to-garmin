#!/usr/bin/env python3
"""
Unit tests for Apple Health to TCX converter
"""

import unittest
import tempfile
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from convert_to_tcx import AppleWorkoutConverter


class TestAppleWorkoutConverter(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures"""
        self.test_dir = Path(tempfile.mkdtemp())
        self.export_dir = self.test_dir / "export"
        self.export_dir.mkdir()
        self.routes_dir = self.export_dir / "workout-routes"
        self.routes_dir.mkdir()
        
        # Create sample export.xml
        self.create_sample_export_xml()
        # Create sample GPX file
        self.create_sample_gpx()
        
        self.converter = AppleWorkoutConverter(self.export_dir)
    
    def tearDown(self):
        """Clean up test fixtures"""
        shutil.rmtree(self.test_dir)
    
    def create_sample_export_xml(self):
        """Create a sample export.xml file for testing"""
        xml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<HealthData>
    <ExportDate value="2024-01-01 12:00:00 +0000"/>
    <Me HKCharacteristicTypeIdentifierDateOfBirth="1990-01-01"
        HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexMale"
        HKCharacteristicTypeIdentifierBloodType="HKBloodTypeNotSet"
        HKCharacteristicTypeIdentifierFitzpatrickSkinType="HKFitzpatrickSkinTypeNotSet"
        HKCharacteristicTypeIdentifierCardioFitnessMedicationsUse="HKCardioFitnessMedicationsUseNotSet"/>
    
    <Workout workoutActivityType="HKWorkoutActivityTypeRunning" 
             duration="30.0" durationUnit="min" 
             sourceName="Bharat's Apple Watch" sourceVersion="10.0" 
             creationDate="2024-01-15 10:30:00 +0000" 
             startDate="2024-01-15 10:00:00 +0000" 
             endDate="2024-01-15 10:30:00 +0000">
        <MetadataEntry key="HKIndoorWorkout" value="0"/>
        <MetadataEntry key="HKElevationAscended" value="500 cm"/>
        <WorkoutStatistics type="HKQuantityTypeIdentifierHeartRate" 
                          startDate="2024-01-15 10:00:00 +0000" 
                          endDate="2024-01-15 10:30:00 +0000" 
                          average="150" minimum="120" maximum="180" unit="count/min"/>
        <WorkoutStatistics type="HKQuantityTypeIdentifierDistanceWalkingRunning" 
                          startDate="2024-01-15 10:00:00 +0000" 
                          endDate="2024-01-15 10:30:00 +0000" 
                          sum="5.0" unit="km"/>
        <WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" 
                          startDate="2024-01-15 10:00:00 +0000" 
                          endDate="2024-01-15 10:30:00 +0000" 
                          sum="300" unit="Cal"/>
        <WorkoutRoute sourceName="Bharat's Apple Watch" sourceVersion="10.0" 
                     creationDate="2024-01-15 10:30:01 +0000" 
                     startDate="2024-01-15 10:00:00 +0000" 
                     endDate="2024-01-15 10:30:00 +0000">
            <FileReference path="/workout-routes/route_2024-01-15_10.00am.gpx"/>
        </WorkoutRoute>
    </Workout>
    
    <Workout workoutActivityType="HKWorkoutActivityTypeWalking" 
             duration="45.0" durationUnit="min" 
             sourceName="Bharat's Apple Watch" sourceVersion="10.0" 
             creationDate="2024-01-16 14:00:00 +0000" 
             startDate="2024-01-16 13:15:00 +0000" 
             endDate="2024-01-16 14:00:00 +0000">
        <MetadataEntry key="HKIndoorWorkout" value="0"/>
        <WorkoutStatistics type="HKQuantityTypeIdentifierDistanceWalkingRunning" 
                          startDate="2024-01-16 13:15:00 +0000" 
                          endDate="2024-01-16 14:00:00 +0000" 
                          sum="3.0" unit="km"/>
        <WorkoutRoute sourceName="Bharat's Apple Watch" sourceVersion="10.0">
            <FileReference path="/workout-routes/route_2024-01-16_1.15pm.gpx"/>
        </WorkoutRoute>
    </Workout>
    
    <Workout workoutActivityType="HKWorkoutActivityTypeRunning" 
             duration="25.0" durationUnit="min" 
             sourceName="Strava" sourceVersion="1.0" 
             creationDate="2024-01-17 09:30:00 +0000" 
             startDate="2024-01-17 09:00:00 +0000" 
             endDate="2024-01-17 09:25:00 +0000">
    </Workout>
</HealthData>'''
        
        export_file = self.export_dir / "export.xml"
        with open(export_file, 'w') as f:
            f.write(xml_content)
    
    def create_sample_gpx(self):
        """Create a sample GPX file for testing"""
        gpx_content = '''<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Apple Health Export" xmlns="http://www.topografix.com/GPX/1/1">
    <trk>
        <name>Route 2024-01-15 10:00am</name>
        <trkseg>
            <trkpt lon="-2.60000" lat="51.44000">
                <ele>100.0</ele>
                <time>2024-01-15T10:00:00Z</time>
                <extensions><speed>3.0</speed><course>45.0</course></extensions>
            </trkpt>
            <trkpt lon="-2.59950" lat="51.44050">
                <ele>101.0</ele>
                <time>2024-01-15T10:00:10Z</time>
                <extensions><speed>3.2</speed><course>47.0</course></extensions>
            </trkpt>
            <trkpt lon="-2.59900" lat="51.44100">
                <ele>102.0</ele>
                <time>2024-01-15T10:00:20Z</time>
                <extensions><speed>2.8</speed><course>43.0</course></extensions>
            </trkpt>
        </trkseg>
    </trk>
</gpx>'''
        
        gpx_file = self.routes_dir / "route_2024-01-15_10.00am.gpx"
        with open(gpx_file, 'w') as f:
            f.write(gpx_content)

    def test_parse_apple_workouts(self):
        """Test parsing workouts from export.xml"""
        workouts = self.converter.parse_apple_workouts()
        
        # Should find 2 Apple Watch workouts (ignoring Strava one)
        self.assertEqual(len(workouts), 2)
        
        # Test first workout (with heart rate)
        workout1 = workouts[0]
        self.assertEqual(workout1['sport'], 'Running')
        self.assertEqual(workout1['duration_minutes'], 30.0)
        self.assertIsNotNone(workout1['heart_rate'])
        self.assertEqual(workout1['heart_rate']['avg'], 150.0)
        self.assertEqual(workout1['heart_rate']['min'], 120)
        self.assertEqual(workout1['heart_rate']['max'], 180)
        self.assertEqual(workout1['distance'], 5.0)
        self.assertEqual(workout1['calories'], 300.0)
        self.assertEqual(workout1['elevation_gain'], 5.0)  # 500cm -> 5m
        
        # Test second workout (without heart rate)
        workout2 = workouts[1]
        self.assertEqual(workout2['sport'], 'Walking')
        self.assertEqual(workout2['duration_minutes'], 45.0)
        self.assertIsNone(workout2['heart_rate'])
        self.assertEqual(workout2['distance'], 3.0)

    def test_convert_activity_type(self):
        """Test activity type conversion"""
        test_cases = [
            ('HKWorkoutActivityTypeRunning', 'Running'),
            ('HKWorkoutActivityTypeWalking', 'Walking'),
            ('HKWorkoutActivityTypeCycling', 'Biking'),
            ('HKWorkoutActivityTypeHiking', 'Other'),
            ('HKWorkoutActivityTypeSwimming', 'Swimming'),
            ('HKWorkoutActivityTypeUnknown', 'Other'),
        ]
        
        for apple_type, expected in test_cases:
            result = self.converter.convert_activity_type(apple_type)
            self.assertEqual(result, expected)

    def test_parse_apple_date(self):
        """Test Apple date format parsing"""
        date_str = "2024-01-15 10:00:00 +0000"
        result = self.converter.parse_apple_date(date_str)
        
        expected = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(result, expected)

    def test_parse_gpx_file(self):
        """Test GPX file parsing"""
        gpx_file = self.routes_dir / "route_2024-01-15_10.00am.gpx"
        trackpoints = self.converter.parse_gpx_file(gpx_file)
        
        self.assertEqual(len(trackpoints), 3)
        
        # Test first trackpoint
        tp1 = trackpoints[0]
        self.assertEqual(tp1['lat'], 51.44000)
        self.assertEqual(tp1['lon'], -2.60000)
        self.assertEqual(tp1['elevation'], 100.0)
        self.assertIsNone(tp1['speed'])  # Speed parsing requires specific format
        self.assertIsInstance(tp1['time'], datetime)

    def test_parse_gpx_file_nonexistent(self):
        """Test GPX file parsing with non-existent file"""
        nonexistent_file = self.routes_dir / "nonexistent.gpx"
        trackpoints = self.converter.parse_gpx_file(nonexistent_file)
        self.assertEqual(trackpoints, [])

    def test_create_tcx_with_heart_rate(self):
        """Test TCX creation with heart rate data"""
        workout_data = {
            'sport': 'Running',
            'start_time': datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            'end_time': datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            'duration_minutes': 30.0,
            'heart_rate': {'avg': 150.0, 'min': 120, 'max': 180},
            'distance': 5.0,
            'calories': 300.0,
            'elevation_gain': 5.0,
            'gpx_file': self.routes_dir / "route_2024-01-15_10.00am.gpx"
        }
        
        tcx = self.converter.create_tcx(workout_data)
        
        # Verify TCX structure
        self.assertEqual(tcx.tag, 'TrainingCenterDatabase')
        self.assertIn('http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2', 
                     tcx.get('xmlns', ''))
        
        # Find activity (no namespace prefix needed for default namespace)
        activity = tcx.find('.//Activity')
        self.assertIsNotNone(activity)
        self.assertEqual(activity.get('Sport'), 'Running')
        
        # Check lap data
        lap = tcx.find('.//Lap')
        self.assertIsNotNone(lap)
        
        # Check heart rate
        avg_hr = tcx.find('.//AverageHeartRateBpm/Value')
        self.assertIsNotNone(avg_hr)
        self.assertEqual(avg_hr.text, '150')
        
        # Check trackpoints
        trackpoints = tcx.findall('.//Trackpoint')
        self.assertEqual(len(trackpoints), 3)

    def test_create_tcx_no_heart_rate(self):
        """Test TCX creation without heart rate data"""
        workout_data = {
            'sport': 'Walking',
            'start_time': datetime(2024, 1, 16, 13, 15, 0, tzinfo=timezone.utc),
            'end_time': datetime(2024, 1, 16, 14, 0, 0, tzinfo=timezone.utc),
            'duration_minutes': 45.0,
            'heart_rate': None,
            'distance': 3.0,
            'calories': 200.0,
            'elevation_gain': None,
            'gpx_file': self.routes_dir / "route_2024-01-15_10.00am.gpx"
        }
        
        tcx = self.converter.create_tcx_no_hr(workout_data)
        
        # Verify no heart rate elements
        hr_elements = tcx.findall('.//HeartRateBpm')
        self.assertEqual(len(hr_elements), 0)
        
        # Verify trackpoints still exist
        trackpoints = tcx.findall('.//Trackpoint')
        self.assertEqual(len(trackpoints), 3)

    def test_convert_workouts_integration(self):
        """Test full workout conversion integration"""
        output_dir = self.test_dir / "tcx_output"
        
        result_count = self.converter.convert_workouts(output_dir)
        
        # Should convert both workouts
        self.assertEqual(result_count, 2)
        
        # Check directory structure - workouts should be organized by year/month
        self.assertTrue(output_dir.exists())
        
        # Check 2024/01 directory exists
        year_month_dir = output_dir / "2024" / "01"
        self.assertTrue(year_month_dir.exists())
        
        # Check no_heart_rate directory exists
        no_hr_dir = output_dir / "no_heart_rate" / "2024" / "01"
        self.assertTrue(no_hr_dir.exists())
        
        # Count TCX files
        tcx_files_with_hr = list(year_month_dir.glob("*.tcx"))
        tcx_files_no_hr = list(no_hr_dir.glob("*.tcx"))
        
        self.assertEqual(len(tcx_files_with_hr), 1)  # Running workout with HR
        self.assertEqual(len(tcx_files_no_hr), 1)    # Walking workout without HR
        
        # Verify file names
        hr_file = tcx_files_with_hr[0]
        self.assertIn("Running", hr_file.name)
        self.assertIn("2024-01-15", hr_file.name)
        
        no_hr_file = tcx_files_no_hr[0]
        self.assertIn("Walking", no_hr_file.name)
        self.assertIn("2024-01-16", no_hr_file.name)

    def test_activity_filter(self):
        """Test filtering workouts by activity type"""
        output_dir = self.test_dir / "tcx_output_filtered"
        
        # Filter for running only
        result_count = self.converter.convert_workouts(output_dir, "running")
        
        # Should only convert running workout
        self.assertEqual(result_count, 1)
        
        # Check only running workout was converted
        tcx_files = list(output_dir.rglob("*.tcx"))
        self.assertEqual(len(tcx_files), 1)
        self.assertIn("Running", tcx_files[0].name)

    def test_invalid_export_xml(self):
        """Test handling of invalid export.xml"""
        # Create invalid XML
        invalid_xml = self.export_dir / "export.xml"
        with open(invalid_xml, 'w') as f:
            f.write("This is not valid XML")
        
        converter = AppleWorkoutConverter(self.export_dir)
        
        # Should raise an exception
        with self.assertRaises(ET.ParseError):
            converter.parse_apple_workouts()


class TestUtilityFunctions(unittest.TestCase):
    """Test standalone utility functions"""
    
    def test_main_function_imports(self):
        """Test that main function and imports work correctly"""
        # This tests that the module can be imported without errors
        from convert_to_tcx import main, AppleWorkoutConverter
        self.assertTrue(callable(main))
        self.assertTrue(callable(AppleWorkoutConverter))


if __name__ == '__main__':
    unittest.main()