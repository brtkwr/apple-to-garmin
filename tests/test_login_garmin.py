#!/usr/bin/env python3
"""Tests for login_garmin.py."""

import unittest
from unittest.mock import MagicMock, patch


class TestLoginGarmin(unittest.TestCase):

    @patch("scripts.login_garmin.TOKENSTORE")
    @patch("scripts.login_garmin.Garmin")
    @patch.dict("os.environ", {"GARMIN_EMAIL": "test@example.com", "GARMIN_PASSWORD": "secret"})
    def test_successful_login_saves_tokens(self, MockGarmin, mock_tokenstore):
        mock_client = MagicMock()
        MockGarmin.return_value = mock_client

        from scripts.login_garmin import main
        main()

        mock_client.login.assert_called_once()
        mock_tokenstore.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_client.garth.dump.assert_called_once_with(str(mock_tokenstore))

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_credentials_exits(self):
        # Remove env vars if set
        import os
        os.environ.pop("GARMIN_EMAIL", None)
        os.environ.pop("GARMIN_PASSWORD", None)

        from scripts.login_garmin import main
        with self.assertRaises(SystemExit):
            main()

    @patch.dict("os.environ", {"GARMIN_EMAIL": "test@example.com"}, clear=True)
    def test_missing_password_exits(self):
        from scripts.login_garmin import main
        with self.assertRaises(SystemExit):
            main()


if __name__ == "__main__":
    unittest.main()
