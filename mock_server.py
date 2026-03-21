#!/usr/bin/env python3
"""
Mock HealthKit Exporter server for testing.
Serves sample workout data on the same endpoints as the iOS app.
Can be used in tests or run standalone for local development.
"""

import json
import re
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading


def generate_sample_workouts(count=5):
    """Generate sample workout metadata."""
    workouts = []
    base_date = datetime(2024, 6, 1, 17, 30, 0, tzinfo=timezone.utc)

    activities = [
        ("running", 37, 60.0, 10.5, 500),
        ("walking", 52, 45.0, 4.2, 200),
        ("cycling", 13, 90.0, 25.0, 600),
        ("running", 37, 30.0, 5.5, 300),
        ("yoga", 46, 60.0, None, 150),
    ]

    for i in range(min(count, len(activities))):
        activity, raw, duration, distance, calories = activities[i]
        start = base_date + timedelta(days=i * 3)
        end = start + timedelta(seconds=duration * 60)

        workout = {
            "index": i,
            "start_date": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_date": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_seconds": duration * 60,
            "activity_type": activity,
            "activity_type_raw": raw,
            "source": "Bharat\u00a0s Apple\u00a0Watch",
            "total_energy_kcal": calories,
        }
        if distance is not None:
            workout["total_distance_metres"] = distance * 1000
        workouts.append(workout)

    return workouts


def generate_sample_metrics(workout):
    """Generate sample metrics including route for a workout."""
    start = datetime.fromisoformat(workout["start_date"].replace("Z", "+00:00"))
    duration = workout["duration_seconds"]
    activity = workout.get("activity_type", "other")

    metrics = {}

    # Heart rate — one reading every ~7 seconds
    hr_points = []
    for sec in range(0, int(duration), 7):
        ts = start + timedelta(seconds=sec)
        hr = 120 + (sec % 60)  # varies 120-180
        hr_points.append({
            "timestamp": ts.timestamp(),
            "date": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "value": hr,
        })
    metrics["heart_rate"] = hr_points

    if activity == "running":
        # Running power
        power_points = []
        for sec in range(0, int(duration), 5):
            ts = start + timedelta(seconds=sec)
            power_points.append({
                "timestamp": ts.timestamp(),
                "date": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "value": 200 + (sec % 100),
            })
        metrics["running_power"] = power_points

        # Running speed (m/s)
        speed_points = []
        for sec in range(0, int(duration), 5):
            ts = start + timedelta(seconds=sec)
            speed_points.append({
                "timestamp": ts.timestamp(),
                "date": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "value": 2.5 + (sec % 20) * 0.1,
            })
        metrics["running_speed"] = speed_points

        # Stride length (m)
        stride_points = []
        for sec in range(0, int(duration), 10):
            ts = start + timedelta(seconds=sec)
            stride_points.append({
                "timestamp": ts.timestamp(),
                "date": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "value": 1.1 + (sec % 10) * 0.05,
            })
        metrics["stride_length"] = stride_points

        # Vertical oscillation (cm)
        vo_points = []
        for sec in range(0, int(duration), 10):
            ts = start + timedelta(seconds=sec)
            vo_points.append({
                "timestamp": ts.timestamp(),
                "date": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "value": 8.0 + (sec % 10) * 0.3,
            })
        metrics["vertical_oscillation"] = vo_points

        # Ground contact time (ms)
        gct_points = []
        for sec in range(0, int(duration), 10):
            ts = start + timedelta(seconds=sec)
            gct_points.append({
                "timestamp": ts.timestamp(),
                "date": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "value": 240 + (sec % 30),
            })
        metrics["ground_contact_time"] = gct_points

    # Route (GPS) — one point per second
    route = []
    base_lat, base_lon = 51.4440, -2.5998
    for sec in range(0, int(duration)):
        ts = start + timedelta(seconds=sec)
        route.append({
            "latitude": base_lat + sec * 0.00001,
            "longitude": base_lon + sec * 0.000005,
            "altitude": 15.0 + (sec % 100) * 0.1,
            "timestamp": ts.timestamp(),
            "date": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "horizontal_accuracy": 2.0,
            "vertical_accuracy": 1.0,
            "speed": 3.0,
            "course": 45.0,
        })
    metrics["route"] = route

    return metrics


class MockHealthKitHandler(BaseHTTPRequestHandler):
    """HTTP handler that mimics the HealthKit Exporter iOS app."""

    workouts = None

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def do_GET(self):
        if self.path == "/workouts":
            self._send_json(self.workouts or [])
            return

        match = re.match(r"^/workouts/(\d+)/metrics$", self.path)
        if match:
            idx = int(match.group(1))
            if 0 <= idx < len(self.workouts or []):
                metrics = generate_sample_metrics(self.workouts[idx])
                self._send_json(metrics)
            else:
                self._send_json({"error": f"Workout not found at index {idx}"}, 404)
            return

        self._send_json({"error": "Not found"}, 404)

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_mock_server(host="127.0.0.1", port=0, num_workouts=5):
    """Start a mock server and return (server, port).

    Use port=0 to pick a random available port.
    """
    workouts = generate_sample_workouts(num_workouts)
    MockHealthKitHandler.workouts = workouts

    server = HTTPServer((host, port), MockHealthKitHandler)
    actual_port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return server, actual_port


def main():
    """Run the mock server standalone for local development."""
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    num_workouts = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    workouts = generate_sample_workouts(num_workouts)
    MockHealthKitHandler.workouts = workouts

    server = HTTPServer(("0.0.0.0", port), MockHealthKitHandler)
    print(f"Mock server running on http://localhost:{port}")
    print(f"Serving {num_workouts} sample workouts")
    print("Endpoints:")
    print("  GET /workouts")
    print("  GET /workouts/{index}/metrics")
    print("  GET /workouts/{index}/heart_rate")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
