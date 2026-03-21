#!/usr/bin/env python3
"""Tests for upload_to_garmin.py."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

from health_export.upload_to_garmin import find_fit_files, upload, get_client


class TestFindFitFiles(unittest.TestCase):

    def test_finds_fit_files_recursively(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "2022" / "05").mkdir(parents=True)
            (d / "2022" / "06").mkdir(parents=True)
            (d / "2022" / "05" / "a.fit").touch()
            (d / "2022" / "06" / "b.fit").touch()
            (d / "2022" / "05" / "c.txt").touch()

            result = find_fit_files(d)
            self.assertEqual(len(result), 2)
            self.assertTrue(all(p.suffix == ".fit" for p in result))

    def test_returns_sorted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "b.fit").touch()
            (d / "a.fit").touch()
            (d / "c.fit").touch()

            result = find_fit_files(d)
            names = [p.name for p in result]
            self.assertEqual(names, ["a.fit", "b.fit", "c.fit"])

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = find_fit_files(Path(tmpdir))
            self.assertEqual(result, [])

    def test_ignores_non_fit_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "workout.tcx").touch()
            (d / "data.json").touch()
            (d / "workout.fit").touch()

            result = find_fit_files(d)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].name, "workout.fit")


class TestUploadDryRun(unittest.TestCase):

    def test_dry_run_does_not_call_api(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "2022" / "05").mkdir(parents=True)
            (d / "2022" / "05" / "test.fit").touch()
            files = find_fit_files(d)

            # Should not raise even though client is None
            upload(None, files, dry_run=True)


class TestUploadWithMockedApi(unittest.TestCase):

    def _make_files(self, tmpdir, names):
        d = Path(tmpdir)
        for name in names:
            (d / name).touch()
        return find_fit_files(d)

    @patch("time.sleep")
    def test_successful_upload(self, mock_sleep):
        client = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            files = self._make_files(tmpdir, ["a.fit", "b.fit"])
            upload(client, files)

        self.assertEqual(client.upload_activity.call_count, 2)

    @patch("time.sleep")
    def test_duplicate_is_skipped(self, mock_sleep):
        client = MagicMock()
        client.upload_activity.side_effect = Exception("409 Conflict")

        with tempfile.TemporaryDirectory() as tmpdir:
            files = self._make_files(tmpdir, ["a.fit"])
            upload(client, files)

        client.upload_activity.assert_called_once()

    @patch("time.sleep")
    def test_duplicate_already_exists(self, mock_sleep):
        client = MagicMock()
        client.upload_activity.side_effect = Exception("Activity already exists")

        with tempfile.TemporaryDirectory() as tmpdir:
            files = self._make_files(tmpdir, ["a.fit"])
            upload(client, files)

        client.upload_activity.assert_called_once()

    @patch("time.sleep")
    def test_other_error_is_recorded(self, mock_sleep):
        client = MagicMock()
        client.upload_activity.side_effect = Exception("500 Server Error")

        with tempfile.TemporaryDirectory() as tmpdir:
            files = self._make_files(tmpdir, ["a.fit"])
            upload(client, files)

        client.upload_activity.assert_called_once()

    @patch("time.sleep")
    def test_mixed_results(self, mock_sleep):
        """First upload succeeds, second is duplicate, third fails."""
        client = MagicMock()
        client.upload_activity.side_effect = [
            None,
            Exception("409 Conflict"),
            Exception("500 Server Error"),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            files = self._make_files(tmpdir, ["a.fit", "b.fit", "c.fit"])
            upload(client, files)

        self.assertEqual(client.upload_activity.call_count, 3)

    @patch("time.sleep")
    def test_no_sleep_after_last_file(self, mock_sleep):
        client = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            files = self._make_files(tmpdir, ["a.fit"])
            upload(client, files)

        mock_sleep.assert_not_called()


class TestGetClient(unittest.TestCase):

    @patch("health_export.upload_to_garmin.TOKENSTORE")
    @patch("health_export.upload_to_garmin.Garmin")
    def test_login_with_saved_tokens(self, MockGarmin, mock_tokenstore):
        mock_tokenstore.exists.return_value = True
        mock_client = MagicMock()
        MockGarmin.return_value = mock_client

        result = get_client("user@test.com", "pass")

        mock_client.login.assert_called_once_with(tokenstore=str(mock_tokenstore))
        self.assertEqual(result, mock_client)

    @patch("health_export.upload_to_garmin.TOKENSTORE")
    @patch("health_export.upload_to_garmin.Garmin")
    def test_expired_tokens_falls_back_to_credentials(self, MockGarmin, mock_tokenstore):
        mock_tokenstore.exists.return_value = True
        mock_client = MagicMock()
        MockGarmin.return_value = mock_client
        # First login (with tokenstore) fails, second (with credentials) succeeds
        mock_client.login.side_effect = [Exception("expired"), None]

        result = get_client("user@test.com", "pass")

        self.assertEqual(mock_client.login.call_count, 2)
        self.assertEqual(result, mock_client)

    @patch("health_export.upload_to_garmin.TOKENSTORE")
    @patch("health_export.upload_to_garmin.Garmin")
    def test_no_tokens_no_credentials_exits(self, MockGarmin, mock_tokenstore):
        mock_tokenstore.exists.return_value = False

        with self.assertRaises(SystemExit):
            get_client(None, None)

    @patch("health_export.upload_to_garmin.TOKENSTORE")
    @patch("health_export.upload_to_garmin.Garmin")
    def test_no_tokens_with_credentials_logs_in(self, MockGarmin, mock_tokenstore):
        mock_tokenstore.exists.return_value = False
        mock_client = MagicMock()
        MockGarmin.return_value = mock_client

        result = get_client("user@test.com", "pass")

        mock_client.login.assert_called_once()
        mock_tokenstore.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_client.garth.dump.assert_called_once()


class TestMainCli(unittest.TestCase):

    @patch("health_export.upload_to_garmin.upload")
    @patch("health_export.upload_to_garmin.find_fit_files")
    def test_main_dry_run(self, mock_find, mock_upload):
        mock_find.return_value = [Path("a.fit")]
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.fit").touch()
            with patch("sys.argv", ["upload_to_garmin.py", tmpdir, "--dry-run"]):
                from health_export.upload_to_garmin import main
                main()

        mock_upload.assert_called_once_with(None, [Path("a.fit")], dry_run=True)

    def test_main_missing_directory_exits(self):
        with patch("sys.argv", ["upload_to_garmin.py", "/nonexistent/path"]):
            from health_export.upload_to_garmin import main
            with self.assertRaises(SystemExit):
                main()

    @patch("health_export.upload_to_garmin.find_fit_files")
    def test_main_no_fit_files_exits(self, mock_find):
        mock_find.return_value = []
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("sys.argv", ["upload_to_garmin.py", tmpdir]):
                from health_export.upload_to_garmin import main
                with self.assertRaises(SystemExit):
                    main()


if __name__ == "__main__":
    unittest.main()
