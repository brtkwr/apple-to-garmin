#!/usr/bin/env python3
"""
Unit tests for Apple Health to FIT converter
"""

import unittest
import tempfile
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

from convert_to_fit import (
    AppleToFitConverter,
    APPLE_SPORT_MAP,
    to_fit_ts,
)
from parser import MetricIndex
from fit_tool.fit_file import FitFile
from fit_tool.profile.profile_type import Sport


def get_fit_messages(parsed, name):
    """Extract data messages of a given type from a parsed FIT file, skipping DefinitionMessages."""
    results = []
    for r in parsed.records:
        msg = getattr(r, 'message', None)
        if msg is not None and getattr(msg, 'NAME', None) == name:
            results.append(msg)
    return results


class TestMetricIndex(unittest.TestCase):
    """Test MetricIndex time-series lookup."""

    def test_add_and_len(self):
        idx = MetricIndex()
        self.assertEqual(len(idx), 0)
        idx.add(datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc), 150.0)
        self.assertEqual(len(idx), 1)
        idx.add(datetime(2024, 1, 1, 10, 0, 1, tzinfo=timezone.utc), 151.0)
        self.assertEqual(len(idx), 2)

    def test_sort(self):
        idx = MetricIndex()
        idx.add(datetime(2024, 1, 1, 10, 0, 5, tzinfo=timezone.utc), 155.0)
        idx.add(datetime(2024, 1, 1, 10, 0, 1, tzinfo=timezone.utc), 151.0)
        idx.add(datetime(2024, 1, 1, 10, 0, 3, tzinfo=timezone.utc), 153.0)
        idx.sort()
        self.assertEqual(idx.values, [151.0, 153.0, 155.0])

    def test_lookup_exact(self):
        idx = MetricIndex()
        t = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        idx.add(t, 150.0)
        idx.sort()
        self.assertEqual(idx.lookup(t), 150.0)

    def test_lookup_nearest_neighbour(self):
        idx = MetricIndex()
        base = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        idx.add(base, 150.0)
        idx.add(base + timedelta(seconds=10), 160.0)
        idx.sort()
        # Query at +3s should return first value (closer)
        result = idx.lookup(base + timedelta(seconds=3))
        self.assertEqual(result, 150.0)
        # Query at +8s should return second value (closer)
        result = idx.lookup(base + timedelta(seconds=8))
        self.assertEqual(result, 160.0)

    def test_lookup_out_of_range(self):
        idx = MetricIndex()
        base = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        idx.add(base, 150.0)
        idx.sort()
        # 60 seconds away, default max_gap is 30
        result = idx.lookup(base + timedelta(seconds=60))
        self.assertIsNone(result)

    def test_lookup_custom_max_gap(self):
        idx = MetricIndex()
        base = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        idx.add(base, 150.0)
        idx.sort()
        # 60 seconds away with max_gap=90
        result = idx.lookup(base + timedelta(seconds=60), max_gap_seconds=90)
        self.assertEqual(result, 150.0)

    def test_lookup_empty(self):
        idx = MetricIndex()
        result = idx.lookup(datetime(2024, 1, 1, tzinfo=timezone.utc))
        self.assertIsNone(result)


class TestToFitTs(unittest.TestCase):
    def test_converts_to_epoch_ms(self):
        dt = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        result = to_fit_ts(dt)
        self.assertEqual(result, int(dt.timestamp() * 1000))


class TestAppleToFitConverter(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.export_dir = self.test_dir / "export"
        self.export_dir.mkdir()
        self.routes_dir = self.export_dir / "workout-routes"
        self.routes_dir.mkdir()

        self.create_sample_export_xml()
        self.create_sample_gpx()

        self.converter = AppleToFitConverter(self.export_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def create_sample_export_xml(self):
        # Running workout with GPX + HR records + running dynamics
        # Walking workout with GPX but no running dynamics
        # Strava workout (should be filtered out -- no Apple Watch source)
        xml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<HealthData>
    <ExportDate value="2024-01-20 12:00:00 +0000"/>

    <!-- Per-second heart rate records -->
    <Record type="HKQuantityTypeIdentifierHeartRate"
            sourceName="Bharat's Apple Watch"
            startDate="2024-01-15 10:00:00 +0000"
            endDate="2024-01-15 10:00:01 +0000"
            value="148"/>
    <Record type="HKQuantityTypeIdentifierHeartRate"
            sourceName="Bharat's Apple Watch"
            startDate="2024-01-15 10:00:10 +0000"
            endDate="2024-01-15 10:00:11 +0000"
            value="152"/>
    <Record type="HKQuantityTypeIdentifierHeartRate"
            sourceName="Bharat's Apple Watch"
            startDate="2024-01-15 10:00:20 +0000"
            endDate="2024-01-15 10:00:21 +0000"
            value="155"/>

    <!-- HR for second workout -->
    <Record type="HKQuantityTypeIdentifierHeartRate"
            sourceName="Bharat's Apple Watch"
            startDate="2024-01-16 13:15:00 +0000"
            endDate="2024-01-16 13:15:01 +0000"
            value="110"/>
    <Record type="HKQuantityTypeIdentifierHeartRate"
            sourceName="Bharat's Apple Watch"
            startDate="2024-01-16 13:15:10 +0000"
            endDate="2024-01-16 13:15:11 +0000"
            value="112"/>

    <!-- Running dynamics for first workout -->
    <Record type="HKQuantityTypeIdentifierRunningPower"
            sourceName="Bharat's Apple Watch"
            startDate="2024-01-15 10:00:00 +0000"
            endDate="2024-01-15 10:00:01 +0000"
            value="280"/>
    <Record type="HKQuantityTypeIdentifierRunningPower"
            sourceName="Bharat's Apple Watch"
            startDate="2024-01-15 10:00:10 +0000"
            endDate="2024-01-15 10:00:11 +0000"
            value="285"/>
    <Record type="HKQuantityTypeIdentifierRunningPower"
            sourceName="Bharat's Apple Watch"
            startDate="2024-01-15 10:00:20 +0000"
            endDate="2024-01-15 10:00:21 +0000"
            value="290"/>

    <Record type="HKQuantityTypeIdentifierRunningStrideLength"
            sourceName="Bharat's Apple Watch"
            startDate="2024-01-15 10:00:00 +0000"
            endDate="2024-01-15 10:00:01 +0000"
            value="1.15"/>
    <Record type="HKQuantityTypeIdentifierRunningStrideLength"
            sourceName="Bharat's Apple Watch"
            startDate="2024-01-15 10:00:10 +0000"
            endDate="2024-01-15 10:00:11 +0000"
            value="1.18"/>
    <Record type="HKQuantityTypeIdentifierRunningStrideLength"
            sourceName="Bharat's Apple Watch"
            startDate="2024-01-15 10:00:20 +0000"
            endDate="2024-01-15 10:00:21 +0000"
            value="1.20"/>

    <Record type="HKQuantityTypeIdentifierRunningVerticalOscillation"
            sourceName="Bharat's Apple Watch"
            startDate="2024-01-15 10:00:00 +0000"
            endDate="2024-01-15 10:00:01 +0000"
            value="8.5"/>
    <Record type="HKQuantityTypeIdentifierRunningVerticalOscillation"
            sourceName="Bharat's Apple Watch"
            startDate="2024-01-15 10:00:10 +0000"
            endDate="2024-01-15 10:00:11 +0000"
            value="8.7"/>

    <Record type="HKQuantityTypeIdentifierRunningGroundContactTime"
            sourceName="Bharat's Apple Watch"
            startDate="2024-01-15 10:00:00 +0000"
            endDate="2024-01-15 10:00:01 +0000"
            value="235"/>
    <Record type="HKQuantityTypeIdentifierRunningGroundContactTime"
            sourceName="Bharat's Apple Watch"
            startDate="2024-01-15 10:00:10 +0000"
            endDate="2024-01-15 10:00:11 +0000"
            value="238"/>

    <Record type="HKQuantityTypeIdentifierRunningSpeed"
            sourceName="Bharat's Apple Watch"
            startDate="2024-01-15 10:00:00 +0000"
            endDate="2024-01-15 10:00:01 +0000"
            value="12.5"/>
    <Record type="HKQuantityTypeIdentifierRunningSpeed"
            sourceName="Bharat's Apple Watch"
            startDate="2024-01-15 10:00:10 +0000"
            endDate="2024-01-15 10:00:11 +0000"
            value="12.8"/>

    <!-- Running workout with GPX route -->
    <Workout workoutActivityType="HKWorkoutActivityTypeRunning"
             duration="30.0" durationUnit="min"
             sourceName="Bharat's Apple Watch" sourceVersion="10.0"
             creationDate="2024-01-15 10:30:00 +0000"
             startDate="2024-01-15 10:00:00 +0000"
             endDate="2024-01-15 10:30:00 +0000">
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

    <!-- Walking workout with GPX route -->
    <Workout workoutActivityType="HKWorkoutActivityTypeWalking"
             duration="45.0" durationUnit="min"
             sourceName="Bharat's Apple Watch" sourceVersion="10.0"
             creationDate="2024-01-16 14:00:00 +0000"
             startDate="2024-01-16 13:15:00 +0000"
             endDate="2024-01-16 14:00:00 +0000">
        <WorkoutStatistics type="HKQuantityTypeIdentifierDistanceWalkingRunning"
                          startDate="2024-01-16 13:15:00 +0000"
                          endDate="2024-01-16 14:00:00 +0000"
                          sum="3.0" unit="km"/>
        <WorkoutRoute sourceName="Bharat's Apple Watch" sourceVersion="10.0">
            <FileReference path="/workout-routes/route_2024-01-16_1.15pm.gpx"/>
        </WorkoutRoute>
    </Workout>

    <!-- Strava workout (should be ignored) -->
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
        gpx_running = '''<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Apple Health Export" xmlns="http://www.topografix.com/GPX/1/1">
    <trk>
        <name>Route 2024-01-15 10:00am</name>
        <trkseg>
            <trkpt lon="-2.60000" lat="51.44000">
                <ele>100.0</ele>
                <time>2024-01-15T10:00:00Z</time>
            </trkpt>
            <trkpt lon="-2.59950" lat="51.44050">
                <ele>101.0</ele>
                <time>2024-01-15T10:00:10Z</time>
            </trkpt>
            <trkpt lon="-2.59900" lat="51.44100">
                <ele>102.0</ele>
                <time>2024-01-15T10:00:20Z</time>
            </trkpt>
        </trkseg>
    </trk>
</gpx>'''

        gpx_walking = '''<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Apple Health Export" xmlns="http://www.topografix.com/GPX/1/1">
    <trk>
        <name>Route 2024-01-16 1:15pm</name>
        <trkseg>
            <trkpt lon="-2.61000" lat="51.45000">
                <ele>90.0</ele>
                <time>2024-01-16T13:15:00Z</time>
            </trkpt>
            <trkpt lon="-2.60950" lat="51.45050">
                <ele>91.0</ele>
                <time>2024-01-16T13:15:10Z</time>
            </trkpt>
        </trkseg>
    </trk>
</gpx>'''

        with open(self.routes_dir / "route_2024-01-15_10.00am.gpx", 'w') as f:
            f.write(gpx_running)
        with open(self.routes_dir / "route_2024-01-16_1.15pm.gpx", 'w') as f:
            f.write(gpx_walking)


class TestWorkoutExtraction(TestAppleToFitConverter):
    """Test workout extraction from XML."""

    def test_running_workout_metadata(self):
        tree = ET.parse(self.converter.export_xml)
        root = tree.getroot()
        workouts = root.findall('.//Workout')
        workout = self.converter.extract_workout(workouts[0])

        self.assertEqual(workout['sport'], Sport.RUNNING)
        self.assertEqual(workout['sport_name'], 'running')
        self.assertAlmostEqual(workout['duration_seconds'], 30.0 * 60)
        self.assertEqual(workout['heart_rate_avg'], 150.0)
        self.assertEqual(workout['distance_km'], 5.0)
        self.assertEqual(workout['calories'], 300.0)

    def test_walking_workout_metadata(self):
        tree = ET.parse(self.converter.export_xml)
        root = tree.getroot()
        workouts = root.findall('.//Workout')
        workout = self.converter.extract_workout(workouts[1])

        self.assertEqual(workout['sport'], Sport.WALKING)
        self.assertEqual(workout['distance_km'], 3.0)
        self.assertIsNone(workout['heart_rate_avg'])

    def test_sport_mapping(self):
        for apple_type, expected_sport in APPLE_SPORT_MAP.items():
            self.assertEqual(APPLE_SPORT_MAP[apple_type], expected_sport)

    def test_unknown_sport_defaults_to_generic(self):
        tree = ET.parse(self.converter.export_xml)
        root = tree.getroot()
        workouts = root.findall('.//Workout')
        # Manually set an unknown type
        workouts[0].set('workoutActivityType', 'HKWorkoutActivityTypeYoga')
        workout = self.converter.extract_workout(workouts[0])
        self.assertEqual(workout['sport'], Sport.GENERIC)

    def test_gpx_file_linked(self):
        tree = ET.parse(self.converter.export_xml)
        root = tree.getroot()
        workouts = root.findall('.//Workout')
        workout = self.converter.extract_workout(workouts[0])

        self.assertIsNotNone(workout['gpx_file'])
        self.assertEqual(workout['gpx_file'].name, "route_2024-01-15_10.00am.gpx")

    def test_workout_without_dates_returns_none(self):
        elem = ET.fromstring('<Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="10"/>')
        result = self.converter.extract_workout(elem)
        self.assertIsNone(result)


class TestGpxParsing(TestAppleToFitConverter):
    """Test GPX file parsing."""

    def test_parse_running_gpx(self):
        gpx_file = self.routes_dir / "route_2024-01-15_10.00am.gpx"
        trackpoints = self.converter.parse_gpx_file(gpx_file)

        self.assertEqual(len(trackpoints), 3)

        tp = trackpoints[0]
        self.assertAlmostEqual(tp['lat'], 51.44000)
        self.assertAlmostEqual(tp['lon'], -2.60000)
        self.assertAlmostEqual(tp['elevation'], 100.0)
        self.assertIsInstance(tp['time'], datetime)

    def test_parse_gpx_nonexistent(self):
        result = self.converter.parse_gpx_file(Path("/nonexistent.gpx"))
        self.assertEqual(result, [])

    def test_parse_gpx_none(self):
        result = self.converter.parse_gpx_file(None)
        self.assertEqual(result, [])

    def test_trackpoint_timestamps_are_correct(self):
        gpx_file = self.routes_dir / "route_2024-01-15_10.00am.gpx"
        trackpoints = self.converter.parse_gpx_file(gpx_file)

        expected_times = [
            datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            datetime(2024, 1, 15, 10, 0, 10, tzinfo=timezone.utc),
            datetime(2024, 1, 15, 10, 0, 20, tzinfo=timezone.utc),
        ]
        for tp, expected in zip(trackpoints, expected_times):
            self.assertEqual(tp['time'], expected)


class TestMetricParsing(TestAppleToFitConverter):
    """Test per-second metric record parsing from export.xml."""

    def _parse_metrics(self):
        tree = ET.parse(self.converter.export_xml)
        root = tree.getroot()
        self.converter.parse_metrics(root)

    def test_heart_rate_records_parsed(self):
        self._parse_metrics()
        hr = self.converter.metrics['heart_rate']
        # 3 for running workout + 2 for walking workout = 5
        self.assertEqual(len(hr), 5)

    def test_running_power_records_parsed(self):
        self._parse_metrics()
        power = self.converter.metrics['power']
        self.assertEqual(len(power), 3)

    def test_stride_length_records_parsed(self):
        self._parse_metrics()
        sl = self.converter.metrics['stride_length']
        self.assertEqual(len(sl), 3)

    def test_vertical_oscillation_records_parsed(self):
        self._parse_metrics()
        vo = self.converter.metrics['vertical_oscillation']
        self.assertEqual(len(vo), 2)

    def test_ground_contact_time_records_parsed(self):
        self._parse_metrics()
        gct = self.converter.metrics['ground_contact_time']
        self.assertEqual(len(gct), 2)

    def test_speed_records_parsed(self):
        self._parse_metrics()
        speed = self.converter.metrics['speed']
        self.assertEqual(len(speed), 2)

    def test_metric_lookup_returns_correct_value(self):
        self._parse_metrics()
        hr = self.converter.metrics['heart_rate']
        t = datetime.fromisoformat("2024-01-15 10:00:00 +0000")
        self.assertEqual(hr.lookup(t), 148.0)


class TestFitFileCreation(TestAppleToFitConverter):
    """Test FIT file creation and validity."""

    def _build_fit_file(self):
        tree = ET.parse(self.converter.export_xml)
        root = tree.getroot()
        self.converter.parse_metrics(root)

        workouts = root.findall('.//Workout')
        workout = self.converter.extract_workout(workouts[0])
        trackpoints = self.converter.parse_gpx_file(workout['gpx_file'])
        return self.converter.create_fit(workout, trackpoints), workout, trackpoints

    def test_fit_file_can_be_written_and_read_back(self):
        fit_file, _, _ = self._build_fit_file()
        output_path = self.test_dir / "test.fit"
        fit_file.to_file(str(output_path))

        self.assertTrue(output_path.exists())
        self.assertGreater(output_path.stat().st_size, 0)

        # Read it back with fit_tool
        parsed = FitFile.from_file(str(output_path))
        self.assertIsNotNone(parsed)

    def test_fit_contains_record_messages(self):
        fit_file, _, trackpoints = self._build_fit_file()
        output_path = self.test_dir / "test.fit"
        fit_file.to_file(str(output_path))

        parsed = FitFile.from_file(str(output_path))
        records = get_fit_messages(parsed, 'record')
        # Merged streams: GPS records + metric records at their own timestamps
        self.assertGreater(len(records), len(trackpoints))

    def test_fit_records_have_heart_rate(self):
        fit_file, _, _ = self._build_fit_file()
        output_path = self.test_dir / "test.fit"
        fit_file.to_file(str(output_path))

        parsed = FitFile.from_file(str(output_path))
        records = get_fit_messages(parsed, 'record')
        hr_records = [r for r in records if r.heart_rate is not None]
        self.assertGreater(len(hr_records), 0)

    def test_fit_records_have_running_power(self):
        fit_file, _, _ = self._build_fit_file()
        output_path = self.test_dir / "test.fit"
        fit_file.to_file(str(output_path))

        parsed = FitFile.from_file(str(output_path))
        records = get_fit_messages(parsed, 'record')
        power_records = [r for r in records if r.power is not None]
        self.assertGreater(len(power_records), 0)

    def test_fit_records_have_stride_length(self):
        fit_file, _, _ = self._build_fit_file()
        output_path = self.test_dir / "test.fit"
        fit_file.to_file(str(output_path))

        parsed = FitFile.from_file(str(output_path))
        records = get_fit_messages(parsed, 'record')
        stride_records = [r for r in records if r.step_length is not None]
        self.assertGreater(len(stride_records), 0)

    def test_fit_contains_session(self):
        fit_file, workout, _ = self._build_fit_file()
        output_path = self.test_dir / "test.fit"
        fit_file.to_file(str(output_path))

        parsed = FitFile.from_file(str(output_path))
        sessions = get_fit_messages(parsed, 'session')
        self.assertEqual(len(sessions), 1)

    def test_fit_contains_lap(self):
        fit_file, _, _ = self._build_fit_file()
        output_path = self.test_dir / "test.fit"
        fit_file.to_file(str(output_path))

        parsed = FitFile.from_file(str(output_path))
        laps = get_fit_messages(parsed, 'lap')
        self.assertEqual(len(laps), 1)

    def test_fit_contains_file_id(self):
        fit_file, _, _ = self._build_fit_file()
        output_path = self.test_dir / "test.fit"
        fit_file.to_file(str(output_path))

        parsed = FitFile.from_file(str(output_path))
        file_ids = get_fit_messages(parsed, 'file_id')
        self.assertEqual(len(file_ids), 1)


class TestConvertWorkoutsIntegration(TestAppleToFitConverter):
    """End-to-end integration tests."""

    def test_converts_apple_watch_workouts(self):
        output_dir = self.test_dir / "fit_output"
        count = self.converter.convert_workouts(output_dir)

        # Both workouts have GPX files, so both should convert
        self.assertEqual(count, 2)
        self.assertTrue(output_dir.exists())

    def test_output_directory_structure(self):
        output_dir = self.test_dir / "fit_output"
        self.converter.convert_workouts(output_dir)

        # Running workout: 2024/01
        running_dir = output_dir / "2024" / "01"
        self.assertTrue(running_dir.exists())
        fit_files = list(running_dir.glob("*.fit"))
        self.assertEqual(len(fit_files), 2)  # running + walking both in Jan 2024

    def test_output_filenames(self):
        output_dir = self.test_dir / "fit_output"
        self.converter.convert_workouts(output_dir)

        fit_files = sorted(output_dir.rglob("*.fit"))
        names = [f.name for f in fit_files]

        self.assertTrue(any("Running" in n for n in names))
        self.assertTrue(any("Walking" in n for n in names))
        self.assertTrue(any("2024-01-15" in n for n in names))
        self.assertTrue(any("2024-01-16" in n for n in names))

    def test_fit_output_files_are_valid(self):
        output_dir = self.test_dir / "fit_output"
        self.converter.convert_workouts(output_dir)

        for fit_path in output_dir.rglob("*.fit"):
            parsed = FitFile.from_file(str(fit_path))
            self.assertIsNotNone(parsed)
            # Every file should have at least file_id, event, record, session
            self.assertTrue(len(get_fit_messages(parsed, 'file_id')) >= 1)
            self.assertTrue(len(get_fit_messages(parsed, 'record')) >= 1)
            self.assertTrue(len(get_fit_messages(parsed, 'session')) >= 1)

    def test_strava_workouts_excluded(self):
        output_dir = self.test_dir / "fit_output"
        self.converter.convert_workouts(output_dir)

        fit_files = list(output_dir.rglob("*.fit"))
        # Only 2 Apple Watch workouts, not the Strava one
        self.assertEqual(len(fit_files), 2)

    def test_default_output_dir(self):
        count = self.converter.convert_workouts()
        default_dir = self.export_dir / "fit_files"
        self.assertTrue(default_dir.exists())
        self.assertEqual(count, 2)


class TestActivityFilter(TestAppleToFitConverter):
    """Test activity type filtering."""

    def test_filter_running(self):
        output_dir = self.test_dir / "fit_filtered"
        count = self.converter.convert_workouts(output_dir, activity_filter="running")
        self.assertEqual(count, 1)
        fit_files = list(output_dir.rglob("*.fit"))
        self.assertEqual(len(fit_files), 1)
        self.assertIn("Running", fit_files[0].name)

    def test_filter_walking(self):
        output_dir = self.test_dir / "fit_filtered"
        count = self.converter.convert_workouts(output_dir, activity_filter="walking")
        self.assertEqual(count, 1)
        fit_files = list(output_dir.rglob("*.fit"))
        self.assertEqual(len(fit_files), 1)
        self.assertIn("Walking", fit_files[0].name)

    def test_filter_no_match(self):
        output_dir = self.test_dir / "fit_filtered"
        count = self.converter.convert_workouts(output_dir, activity_filter="cycling")
        self.assertEqual(count, 0)

    def test_filter_case_insensitive(self):
        output_dir = self.test_dir / "fit_filtered"
        count = self.converter.convert_workouts(output_dir, activity_filter="Running")
        self.assertEqual(count, 1)


if __name__ == '__main__':
    unittest.main()
