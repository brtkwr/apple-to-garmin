#!/usr/bin/env python3
"""Tests for fetch_healthkit.py using the mock server."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from mock_server import start_mock_server


class TestFetchHealthkit(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port = start_mock_server(num_workouts=3)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.output_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.output_dir)

    def _run_fetch(self, host="127.0.0.1", port=None, output_dir=None):
        """Run fetch_healthkit.main() with the given args."""
        import sys
        port = port or self.port
        output_dir = output_dir or self.output_dir

        old_argv = sys.argv
        sys.argv = ["fetch_healthkit.py", host, str(port), str(output_dir)]
        try:
            from fetch_healthkit import main
            main()
        finally:
            sys.argv = old_argv

    def test_fetches_all_workouts(self):
        self._run_fetch()
        workouts_file = self.output_dir / "workouts.json"
        self.assertTrue(workouts_file.exists())
        workouts = json.load(open(workouts_file))
        self.assertEqual(len(workouts), 3)

    def test_creates_individual_workout_files(self):
        self._run_fetch()
        workout_files = list(self.output_dir.glob("2*.json"))
        self.assertEqual(len(workout_files), 3)

    def test_workout_file_contains_metrics_and_route(self):
        self._run_fetch()
        workout_files = sorted(self.output_dir.glob("2*.json"))
        data = json.load(open(workout_files[0]))

        self.assertIn("workout", data)
        self.assertIn("metrics", data)
        self.assertIn("route", data)

        # Route should have GPS points
        self.assertGreater(len(data["route"]), 0)
        self.assertIn("latitude", data["route"][0])
        self.assertIn("longitude", data["route"][0])

        # Metrics should have heart rate
        self.assertIn("heart_rate", data["metrics"])
        self.assertGreater(len(data["metrics"]["heart_rate"]), 0)

    def test_route_not_in_metrics(self):
        """Route should be separated from metrics in the output."""
        self._run_fetch()
        workout_files = sorted(self.output_dir.glob("2*.json"))
        data = json.load(open(workout_files[0]))
        self.assertNotIn("route", data["metrics"])

    def test_running_workout_has_running_dynamics(self):
        self._run_fetch()
        workout_files = sorted(self.output_dir.glob("*running*.json"))
        self.assertGreater(len(workout_files), 0)
        data = json.load(open(workout_files[0]))
        metrics = data["metrics"]
        self.assertIn("running_power", metrics)
        self.assertIn("running_speed", metrics)
        self.assertIn("stride_length", metrics)
        self.assertIn("vertical_oscillation", metrics)
        self.assertIn("ground_contact_time", metrics)


class TestMockServer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port = start_mock_server(num_workouts=2)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def _fetch(self, path):
        import urllib.request
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read())

    def test_workouts_endpoint(self):
        data = self._fetch("/workouts")
        self.assertEqual(len(data), 2)
        self.assertIn("index", data[0])
        self.assertIn("start_date", data[0])
        self.assertIn("activity_type", data[0])

    def test_metrics_endpoint(self):
        data = self._fetch("/workouts/0")
        self.assertIn("heart_rate", data)
        self.assertIn("route", data)
        self.assertGreater(len(data["heart_rate"]), 0)

    def test_metrics_endpoint_invalid_index(self):
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._fetch("/workouts/999")
        self.assertEqual(ctx.exception.code, 404)

    def test_404_for_unknown_path(self):
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._fetch("/unknown")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
