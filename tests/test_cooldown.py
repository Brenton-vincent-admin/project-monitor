import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PyQt6.QtCore import QDateTime, Qt

from app.codex import _extract_rate_limit
from app.db import Database
from ui import format_cooldown_remaining, format_timestamp


class CooldownTests(unittest.TestCase):
    def test_timezone_is_preserved_when_counting_down(self):
        now = QDateTime.fromString("2026-09-03T23:00:00Z", Qt.DateFormat.ISODate)

        text, seconds = format_cooldown_remaining(
            "2026-09-04T04:00:00Z", now
        )

        self.assertEqual(text, "05:00:00")
        self.assertEqual(seconds, 5 * 60 * 60)

    def test_last_used_timestamp_is_displayed_in_local_time(self):
        displayed = format_timestamp("2026-09-03T23:00:00Z")

        self.assertIn("6:00 AM", displayed)

    def test_next_available_skips_future_cooldowns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "monitor.db")
            first = db.add_account("First", "one")
            second = db.add_account("Second", "two")
            future = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
            db.update_account(first, cooldown_until=future)

            selected = db.get_next_available()

            self.assertEqual(selected["id"], second)
            db.close()

    def test_prefers_the_five_hour_server_window(self):
        result = {
            "rateLimits": {
                "limitId": "codex",
                "primary": {
                    "usedPercent": 100,
                    "windowDurationMins": 300,
                    "resetsAt": 2_000_000_000,
                },
                "secondary": {
                    "usedPercent": 10,
                    "windowDurationMins": 10_080,
                    "resetsAt": 2_100_000_000,
                },
            }
        }

        limit = _extract_rate_limit(result, 300)

        self.assertEqual(limit["window_minutes"], 300)
        self.assertEqual(limit["used_percent"], 100)
        self.assertEqual(limit["resets_at"], 2_000_000_000)


if __name__ == "__main__":
    unittest.main()
