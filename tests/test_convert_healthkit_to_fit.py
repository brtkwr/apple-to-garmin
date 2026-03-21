#!/usr/bin/env python3
"""Tests for the HealthKit-to-FIT converter."""

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone

# Stub the 'parser' module before importing the converter, since it may not
# exist in the test environment (it's only needed for GPX file parsing).
if 'parser' not in sys.modules:
    _stub = types.ModuleType('parser')
    _stub.parse_gpx_file = lambda path: []
    sys.modules['parser'] = _stub

from fit_tool.fit_file import FitFile
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.profile_type import Sport

from health_export.convert_healthkit_to_fit import create_fit, parse_iso, to_fit_ts, SPORT_MAP, main


def make_workout(
    activity_type='running',
    start='2024-01-15T08:00:00Z',
    end='2024-01-15T08:30:00Z',
    duration_seconds=1800,
    total_distance_metres=5000.0,
    total_energy_kcal=350,
):
    return {
        'activity_type': activity_type,
        'start_date': start,
        'end_date': end,
        'duration_seconds': duration_seconds,
        'total_distance_metres': total_distance_metres,
        'total_energy_kcal': total_energy_kcal,
    }


def make_metrics(
    heart_rate=True,
    power=True,
    speed=True,
    stride_length=True,
    vertical_oscillation=True,
    ground_contact_time=True,
):
    """Build a metrics dict with sample data points at known timestamps."""
    base_ts = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc).timestamp()
    result = {}

    if heart_rate:
        result['heart_rate'] = [
            {'timestamp': base_ts + 0, 'date': '2024-01-15T08:00:00Z', 'value': 140},
            {'timestamp': base_ts + 10, 'date': '2024-01-15T08:00:10Z', 'value': 155},
            {'timestamp': base_ts + 20, 'date': '2024-01-15T08:00:20Z', 'value': 162},
        ]
    if power:
        result['running_power'] = [
            {'timestamp': base_ts + 5, 'date': '2024-01-15T08:00:05Z', 'value': 250},
            {'timestamp': base_ts + 15, 'date': '2024-01-15T08:00:15Z', 'value': 260},
        ]
    if speed:
        result['running_speed'] = [
            {'timestamp': base_ts + 3, 'date': '2024-01-15T08:00:03Z', 'value': 3.5},
            {'timestamp': base_ts + 13, 'date': '2024-01-15T08:00:13Z', 'value': 3.6},
        ]
    if stride_length:
        result['stride_length'] = [
            {'timestamp': base_ts + 7, 'date': '2024-01-15T08:00:07Z', 'value': 1.2},
        ]
    if vertical_oscillation:
        result['vertical_oscillation'] = [
            {'timestamp': base_ts + 8, 'date': '2024-01-15T08:00:08Z', 'value': 8.5},
        ]
    if ground_contact_time:
        result['ground_contact_time'] = [
            {'timestamp': base_ts + 9, 'date': '2024-01-15T08:00:09Z', 'value': 240.0},
        ]
    return result


def make_trackpoints():
    """Build GPS trackpoints in the HealthKit route JSON format."""
    base_ts = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
    return [
        {
            'time': base_ts,
            'lat': 51.5074,
            'lon': -0.1278,
            'elevation': 10.0,
        },
        {
            'time': datetime(2024, 1, 15, 8, 0, 12, tzinfo=timezone.utc),
            'lat': 51.5080,
            'lon': -0.1270,
            'elevation': 11.5,
        },
    ]


def make_healthkit_route_points():
    """Build GPS data in HealthKit route JSON format (latitude/longitude/altitude/timestamp keys)."""
    base_ts = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc).timestamp()
    return [
        {
            'latitude': 51.5074,
            'longitude': -0.1278,
            'altitude': 10.0,
            'timestamp': base_ts + 0,
            'date': '2024-01-15T08:00:00Z',
            'speed': 3.5,
            'course': 90.0,
        },
        {
            'latitude': 51.5080,
            'longitude': -0.1270,
            'altitude': 11.5,
            'timestamp': base_ts + 12,
            'date': '2024-01-15T08:00:12Z',
            'speed': 3.6,
            'course': 85.0,
        },
    ]


def write_fit_and_read_back(fit_file):
    """Write a FIT file to a temp path and read it back."""
    tmp = tempfile.NamedTemporaryFile(suffix='.fit', delete=False)
    tmp.close()
    try:
        fit_file.to_file(tmp.name)
        return FitFile.from_file(tmp.name)
    finally:
        os.unlink(tmp.name)


def get_data_messages(fit_file, message_type):
    """Extract all data messages of a given type from a FIT file."""
    return [
        r.message for r in fit_file.records
        if not r.is_definition and isinstance(r.message, message_type)
    ]


class TestCreateFit(unittest.TestCase):
    """Test create_fit produces a valid FIT file from sample data."""

    def test_creates_valid_fit_file(self):
        workout = make_workout()
        metrics = make_metrics()
        trackpoints = make_trackpoints()

        fit_file = create_fit(workout, metrics, trackpoints)
        parsed = write_fit_and_read_back(fit_file)

        # Should have records (definitions + data)
        self.assertGreater(len(parsed.records), 0)

    def test_empty_metrics_and_trackpoints(self):
        workout = make_workout()
        fit_file = create_fit(workout, {}, [])
        parsed = write_fit_and_read_back(fit_file)
        self.assertGreater(len(parsed.records), 0)


class TestGPSTrackpoints(unittest.TestCase):
    """Test GPS trackpoints from HealthKit route JSON format."""

    def test_healthkit_route_json_format(self):
        """Trackpoints using latitude/longitude/altitude keys (HealthKit route format)."""
        workout = make_workout()
        base_ts = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)

        # Use the HealthKit route JSON key names directly as trackpoints
        trackpoints = [
            {
                'time': base_ts,
                'latitude': 51.5074,
                'longitude': -0.1278,
                'altitude': 10.0,
            },
            {
                'time': datetime(2024, 1, 15, 8, 0, 12, tzinfo=timezone.utc),
                'latitude': 51.5080,
                'longitude': -0.1270,
                'altitude': 11.5,
            },
        ]

        fit_file = create_fit(workout, {}, trackpoints)
        parsed = write_fit_and_read_back(fit_file)
        records = get_data_messages(parsed, RecordMessage)

        # Should have 2 GPS records
        self.assertEqual(len(records), 2)

        # Check first GPS point has position data
        self.assertIsNotNone(records[0].position_lat)
        self.assertIsNotNone(records[0].position_long)

    def test_lat_lon_keys(self):
        """Trackpoints using lat/lon keys (GPX-style)."""
        workout = make_workout()
        trackpoints = make_trackpoints()

        fit_file = create_fit(workout, {}, trackpoints)
        parsed = write_fit_and_read_back(fit_file)
        records = get_data_messages(parsed, RecordMessage)

        self.assertEqual(len(records), 2)
        self.assertIsNotNone(records[0].position_lat)
        self.assertIsNotNone(records[0].position_long)


class TestMergedStreams(unittest.TestCase):
    """Verify GPS records and metric records are sorted by time."""

    def test_records_sorted_by_timestamp(self):
        workout = make_workout()
        metrics = make_metrics()
        trackpoints = make_trackpoints()

        fit_file = create_fit(workout, metrics, trackpoints)
        parsed = write_fit_and_read_back(fit_file)
        records = get_data_messages(parsed, RecordMessage)

        timestamps = [r.timestamp for r in records]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_gps_and_metrics_interleaved(self):
        """GPS and metric records should be interleaved by time, not grouped."""
        workout = make_workout()
        metrics = make_metrics(
            power=False, stride_length=False,
            vertical_oscillation=False, ground_contact_time=False,
        )
        trackpoints = make_trackpoints()

        fit_file = create_fit(workout, metrics, trackpoints)
        parsed = write_fit_and_read_back(fit_file)
        records = get_data_messages(parsed, RecordMessage)

        # We have GPS at t+0, t+12 and HR at t+0, t+10, t+20 and speed at t+3, t+13
        # Unique timestamps: {0, 3, 10, 12, 13, 20} = 6 records, sorted
        self.assertEqual(len(records), 6)

        timestamps = [r.timestamp for r in records]
        self.assertEqual(timestamps, sorted(timestamps))


class TestMetricFields(unittest.TestCase):
    """Test that heart rate, power, speed, stride length, vertical oscillation,
    and ground contact time all appear in FIT record messages."""

    def test_heart_rate_records(self):
        workout = make_workout()
        metrics = make_metrics(
            power=False, speed=False, stride_length=False,
            vertical_oscillation=False, ground_contact_time=False,
        )

        fit_file = create_fit(workout, metrics, [])
        parsed = write_fit_and_read_back(fit_file)
        records = get_data_messages(parsed, RecordMessage)

        hr_values = [r.heart_rate for r in records if r.heart_rate is not None]
        self.assertEqual(len(hr_values), 3)
        self.assertIn(140, hr_values)
        self.assertIn(155, hr_values)
        self.assertIn(162, hr_values)

    def test_power_records(self):
        workout = make_workout()
        metrics = make_metrics(
            heart_rate=False, speed=False, stride_length=False,
            vertical_oscillation=False, ground_contact_time=False,
        )

        fit_file = create_fit(workout, metrics, [])
        parsed = write_fit_and_read_back(fit_file)
        records = get_data_messages(parsed, RecordMessage)

        power_values = [r.power for r in records if r.power is not None]
        self.assertEqual(len(power_values), 2)
        self.assertIn(250, power_values)
        self.assertIn(260, power_values)

    def test_speed_records(self):
        workout = make_workout()
        metrics = make_metrics(
            heart_rate=False, power=False, stride_length=False,
            vertical_oscillation=False, ground_contact_time=False,
        )

        fit_file = create_fit(workout, metrics, [])
        parsed = write_fit_and_read_back(fit_file)
        records = get_data_messages(parsed, RecordMessage)

        speed_values = [r.enhanced_speed for r in records if r.enhanced_speed is not None]
        self.assertEqual(len(speed_values), 2)

    def test_stride_length_records(self):
        workout = make_workout()
        metrics = make_metrics(
            heart_rate=False, power=False, speed=False,
            vertical_oscillation=False, ground_contact_time=False,
        )

        fit_file = create_fit(workout, metrics, [])
        parsed = write_fit_and_read_back(fit_file)
        records = get_data_messages(parsed, RecordMessage)

        # step_length is set from stride_length (m -> mm)
        step_values = [r.step_length for r in records if r.step_length is not None]
        self.assertEqual(len(step_values), 1)

    def test_vertical_oscillation_records(self):
        workout = make_workout()
        metrics = make_metrics(
            heart_rate=False, power=False, speed=False,
            stride_length=False, ground_contact_time=False,
        )

        fit_file = create_fit(workout, metrics, [])
        parsed = write_fit_and_read_back(fit_file)
        records = get_data_messages(parsed, RecordMessage)

        vo_values = [r.vertical_oscillation for r in records if r.vertical_oscillation is not None]
        self.assertEqual(len(vo_values), 1)

    def test_ground_contact_time_records(self):
        workout = make_workout()
        metrics = make_metrics(
            heart_rate=False, power=False, speed=False,
            stride_length=False, vertical_oscillation=False,
        )

        fit_file = create_fit(workout, metrics, [])
        parsed = write_fit_and_read_back(fit_file)
        records = get_data_messages(parsed, RecordMessage)

        gct_values = [r.stance_time for r in records if r.stance_time is not None]
        self.assertEqual(len(gct_values), 1)

    def test_all_metrics_present(self):
        """A single FIT file with all metric types populated."""
        workout = make_workout()
        metrics = make_metrics()
        trackpoints = make_trackpoints()

        fit_file = create_fit(workout, metrics, trackpoints)
        parsed = write_fit_and_read_back(fit_file)
        records = get_data_messages(parsed, RecordMessage)

        hr_count = sum(1 for r in records if r.heart_rate is not None)
        power_count = sum(1 for r in records if r.power is not None)
        speed_count = sum(1 for r in records if r.enhanced_speed is not None)
        gps_count = sum(1 for r in records if r.position_lat is not None)

        # With interpolation, all metrics are present on all 11 records
        self.assertEqual(len(records), 11)
        self.assertEqual(hr_count, 11)
        self.assertEqual(power_count, 11)
        self.assertEqual(speed_count, 11)
        self.assertEqual(gps_count, 2)


class TestInterpolation(unittest.TestCase):
    """Test that metric values are linearly interpolated between known points."""

    def test_hr_interpolated_between_points(self):
        """HR at t+5 should be midpoint between t+0 (140) and t+10 (155)."""
        base_ts = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc).timestamp()
        workout = make_workout()
        metrics = {
            'heart_rate': [
                {'timestamp': base_ts + 0, 'date': '2024-01-15T08:00:00Z', 'value': 140},
                {'timestamp': base_ts + 10, 'date': '2024-01-15T08:00:10Z', 'value': 160},
            ],
        }
        # GPS at t+5 to force a record at the midpoint
        trackpoints = [{
            'time': datetime(2024, 1, 15, 8, 0, 5, tzinfo=timezone.utc),
            'lat': 51.5074, 'lon': -0.1278, 'elevation': 10.0,
        }]

        fit_file = create_fit(workout, metrics, trackpoints)
        parsed = write_fit_and_read_back(fit_file)
        records = get_data_messages(parsed, RecordMessage)

        # Find the record at t+5
        target_ts = to_fit_ts(datetime(2024, 1, 15, 8, 0, 5, tzinfo=timezone.utc))
        mid_records = [r for r in records if r.timestamp == target_ts]
        self.assertEqual(len(mid_records), 1)
        # Interpolated: 140 + (160-140) * 0.5 = 150
        self.assertEqual(mid_records[0].heart_rate, 150)

    def test_exact_timestamp_uses_exact_value(self):
        """When a record falls on an exact metric timestamp, use that value."""
        base_ts = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc).timestamp()
        workout = make_workout()
        metrics = {
            'heart_rate': [
                {'timestamp': base_ts + 0, 'date': '2024-01-15T08:00:00Z', 'value': 140},
                {'timestamp': base_ts + 10, 'date': '2024-01-15T08:00:10Z', 'value': 160},
            ],
        }

        fit_file = create_fit(workout, metrics, [])
        parsed = write_fit_and_read_back(fit_file)
        records = get_data_messages(parsed, RecordMessage)

        hr_values = [r.heart_rate for r in records if r.heart_rate is not None]
        self.assertIn(140, hr_values)
        self.assertIn(160, hr_values)

    def test_before_first_point_uses_first_value(self):
        """Timestamps before the first metric point get the first value."""
        base_ts = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc).timestamp()
        workout = make_workout()
        metrics = {
            'heart_rate': [
                {'timestamp': base_ts + 10, 'date': '2024-01-15T08:00:10Z', 'value': 150},
            ],
        }
        trackpoints = [{
            'time': datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc),
            'lat': 51.5074, 'lon': -0.1278, 'elevation': 10.0,
        }]

        fit_file = create_fit(workout, metrics, trackpoints)
        parsed = write_fit_and_read_back(fit_file)
        records = get_data_messages(parsed, RecordMessage)

        # Record at t+0 should have HR=150 (first/only known value)
        target_ts = to_fit_ts(datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc))
        early_records = [r for r in records if r.timestamp == target_ts]
        self.assertEqual(len(early_records), 1)
        self.assertEqual(early_records[0].heart_rate, 150)


class TestSportTypeMapping(unittest.TestCase):
    """Test sport type mapping from HealthKit activity types."""

    def test_running_maps_to_running(self):
        workout = make_workout(activity_type='running')
        fit_file = create_fit(workout, make_metrics(), [])
        parsed = write_fit_and_read_back(fit_file)
        sessions = get_data_messages(parsed, SessionMessage)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].sport, Sport.RUNNING.value)

    def test_cycling_maps_to_cycling(self):
        workout = make_workout(activity_type='cycling')
        fit_file = create_fit(workout, make_metrics(), [])
        parsed = write_fit_and_read_back(fit_file)
        sessions = get_data_messages(parsed, SessionMessage)
        self.assertEqual(sessions[0].sport, Sport.CYCLING.value)

    def test_walking_maps_to_walking(self):
        workout = make_workout(activity_type='walking')
        fit_file = create_fit(workout, make_metrics(), [])
        parsed = write_fit_and_read_back(fit_file)
        sessions = get_data_messages(parsed, SessionMessage)
        self.assertEqual(sessions[0].sport, Sport.WALKING.value)

    def test_hiking_maps_to_hiking(self):
        workout = make_workout(activity_type='hiking')
        fit_file = create_fit(workout, make_metrics(), [])
        parsed = write_fit_and_read_back(fit_file)
        sessions = get_data_messages(parsed, SessionMessage)
        self.assertEqual(sessions[0].sport, Sport.HIKING.value)

    def test_unknown_maps_to_generic(self):
        workout = make_workout(activity_type='unknown_sport')
        fit_file = create_fit(workout, make_metrics(), [])
        parsed = write_fit_and_read_back(fit_file)
        sessions = get_data_messages(parsed, SessionMessage)
        self.assertEqual(sessions[0].sport, Sport.GENERIC.value)

    def test_all_mapped_sports(self):
        for hk_type, fit_sport in SPORT_MAP.items():
            workout = make_workout(activity_type=hk_type)
            fit_file = create_fit(workout, make_metrics(), [])
            parsed = write_fit_and_read_back(fit_file)
            sessions = get_data_messages(parsed, SessionMessage)
            self.assertEqual(sessions[0].sport, fit_sport.value, f'Failed for {hk_type}')


class TestWorkoutMetadata(unittest.TestCase):
    """Test workout metadata (distance, calories, duration) in session and lap."""

    def test_session_distance(self):
        workout = make_workout(total_distance_metres=5000.0)
        fit_file = create_fit(workout, make_metrics(), [])
        parsed = write_fit_and_read_back(fit_file)
        sessions = get_data_messages(parsed, SessionMessage)
        self.assertAlmostEqual(sessions[0].total_distance, 5000.0, places=0)

    def test_session_calories(self):
        workout = make_workout(total_energy_kcal=350)
        fit_file = create_fit(workout, make_metrics(), [])
        parsed = write_fit_and_read_back(fit_file)
        sessions = get_data_messages(parsed, SessionMessage)
        self.assertEqual(sessions[0].total_calories, 350)

    def test_session_duration(self):
        workout = make_workout(duration_seconds=1800)
        fit_file = create_fit(workout, make_metrics(), [])
        parsed = write_fit_and_read_back(fit_file)
        sessions = get_data_messages(parsed, SessionMessage)
        self.assertAlmostEqual(sessions[0].total_elapsed_time, 1800, places=0)

    def test_lap_distance(self):
        workout = make_workout(total_distance_metres=5000.0)
        fit_file = create_fit(workout, make_metrics(), [])
        parsed = write_fit_and_read_back(fit_file)
        laps = get_data_messages(parsed, LapMessage)
        self.assertEqual(len(laps), 1)
        self.assertAlmostEqual(laps[0].total_distance, 5000.0, places=0)

    def test_lap_calories(self):
        workout = make_workout(total_energy_kcal=350)
        fit_file = create_fit(workout, make_metrics(), [])
        parsed = write_fit_and_read_back(fit_file)
        laps = get_data_messages(parsed, LapMessage)
        self.assertEqual(laps[0].total_calories, 350)

    def test_lap_duration(self):
        workout = make_workout(duration_seconds=1800)
        fit_file = create_fit(workout, make_metrics(), [])
        parsed = write_fit_and_read_back(fit_file)
        laps = get_data_messages(parsed, LapMessage)
        self.assertAlmostEqual(laps[0].total_elapsed_time, 1800, places=0)

    def test_no_distance_when_absent(self):
        workout = make_workout()
        del workout['total_distance_metres']
        fit_file = create_fit(workout, make_metrics(), [])
        parsed = write_fit_and_read_back(fit_file)
        sessions = get_data_messages(parsed, SessionMessage)
        # total_distance should be None when not provided
        self.assertIsNone(sessions[0].total_distance)

    def test_no_calories_when_absent(self):
        workout = make_workout()
        del workout['total_energy_kcal']
        fit_file = create_fit(workout, make_metrics(), [])
        parsed = write_fit_and_read_back(fit_file)
        sessions = get_data_messages(parsed, SessionMessage)
        self.assertIsNone(sessions[0].total_calories)


class TestIntegration(unittest.TestCase):
    """Integration test: create sample JSON files in HealthKit export format,
    run the converter, verify FIT files are produced."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.hk_dir = os.path.join(self.tmpdir, 'apple_health_export')
        self.output_dir = os.path.join(self.tmpdir, 'fit_output')
        os.makedirs(self.hk_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write_workout_file(self, filename, workout, metrics, route=None):
        data = {
            'workout': workout,
            'metrics': metrics,
        }
        if route is not None:
            data['route'] = route
        path = os.path.join(self.hk_dir, filename)
        with open(path, 'w') as f:
            json.dump(data, f)

    def test_end_to_end_conversion(self):
        """Write sample HealthKit JSON files, run main(), verify FIT output."""
        workout = make_workout()
        metrics = make_metrics()
        route = make_healthkit_route_points()

        # Write workouts.json (list of workout metadata)
        workouts_path = os.path.join(self.hk_dir, 'workouts.json')
        with open(workouts_path, 'w') as f:
            json.dump([workout], f)

        # Write individual workout file (filename starts with date)
        self._write_workout_file(
            '2024-01-15_running_88.json',
            workout, metrics, route,
        )

        import sys
        old_argv = sys.argv
        try:
            sys.argv = [
                'convert_healthkit_to_fit.py',
                self.hk_dir,
                '--output', self.output_dir,
            ]
            main()
        finally:
            sys.argv = old_argv

        # Verify FIT files were produced
        fit_files = []
        for root, dirs, files in os.walk(self.output_dir):
            for f in files:
                if f.endswith('.fit'):
                    fit_files.append(os.path.join(root, f))

        self.assertEqual(len(fit_files), 1)

        # Verify the FIT file is valid and readable
        parsed = FitFile.from_file(fit_files[0])
        records = get_data_messages(parsed, RecordMessage)
        sessions = get_data_messages(parsed, SessionMessage)

        self.assertGreater(len(records), 0)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].sport, Sport.RUNNING.value)

    def test_multiple_workouts(self):
        """Multiple workout files produce multiple FIT files."""
        workout1 = make_workout(
            start='2024-01-15T08:00:00Z',
            end='2024-01-15T08:30:00Z',
        )
        workout2 = make_workout(
            activity_type='cycling',
            start='2024-01-16T10:00:00Z',
            end='2024-01-16T11:00:00Z',
            duration_seconds=3600,
            total_distance_metres=20000.0,
            total_energy_kcal=500,
        )
        metrics = make_metrics()

        self._write_workout_file('2024-01-15_running_88.json', workout1, metrics)
        self._write_workout_file('2024-01-16_cycling_89.json', workout2, metrics)

        import sys
        old_argv = sys.argv
        try:
            sys.argv = [
                'convert_healthkit_to_fit.py',
                self.hk_dir,
                '--output', self.output_dir,
            ]
            main()
        finally:
            sys.argv = old_argv

        fit_files = []
        for root, dirs, files in os.walk(self.output_dir):
            for f in files:
                if f.endswith('.fit'):
                    fit_files.append(os.path.join(root, f))

        self.assertEqual(len(fit_files), 2)

    def test_skips_workout_with_no_metrics(self):
        """Workouts with no metric data are skipped."""
        workout = make_workout()
        empty_metrics = {}

        self._write_workout_file('2024-01-15_running_88.json', workout, empty_metrics)

        import sys
        old_argv = sys.argv
        try:
            sys.argv = [
                'convert_healthkit_to_fit.py',
                self.hk_dir,
                '--output', self.output_dir,
            ]
            main()
        finally:
            sys.argv = old_argv

        fit_files = []
        for root, dirs, files in os.walk(self.output_dir):
            for f in files:
                if f.endswith('.fit'):
                    fit_files.append(os.path.join(root, f))

        self.assertEqual(len(fit_files), 0)

    def test_activity_filter(self):
        """--activity flag filters workouts by type."""
        running = make_workout(activity_type='running')
        cycling = make_workout(
            activity_type='cycling',
            start='2024-01-16T10:00:00Z',
            end='2024-01-16T11:00:00Z',
        )
        metrics = make_metrics()

        self._write_workout_file('2024-01-15_running_88.json', running, metrics)
        self._write_workout_file('2024-01-16_cycling_89.json', cycling, metrics)

        import sys
        old_argv = sys.argv
        try:
            sys.argv = [
                'convert_healthkit_to_fit.py',
                self.hk_dir,
                '--output', self.output_dir,
                '--activity', 'running',
            ]
            main()
        finally:
            sys.argv = old_argv

        fit_files = []
        for root, dirs, files in os.walk(self.output_dir):
            for f in files:
                if f.endswith('.fit'):
                    fit_files.append(os.path.join(root, f))

        self.assertEqual(len(fit_files), 1)


class TestHelpers(unittest.TestCase):
    """Test helper functions."""

    def test_parse_iso_with_z(self):
        dt = parse_iso('2024-01-15T08:00:00Z')
        self.assertEqual(dt.year, 2024)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_iso_with_offset(self):
        dt = parse_iso('2024-01-15T08:00:00+00:00')
        self.assertEqual(dt.year, 2024)

    def test_to_fit_ts(self):
        dt = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        ts = to_fit_ts(dt)
        self.assertIsInstance(ts, int)
        self.assertGreater(ts, 0)


if __name__ == '__main__':
    unittest.main()
