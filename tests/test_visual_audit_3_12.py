import unittest
from datetime import datetime, timezone

from oku100.models import Bar
from scripts.visual_audit_render_w1_3_12 import aggregate_closed_weeks


class WeeklyAggregationTests(unittest.TestCase):
    def test_excludes_open_week(self):
        bars = [
            Bar(datetime(2026, 10, 12, tzinfo=timezone.utc), 1, 3, 0, 2),
            Bar(datetime(2026, 10, 13, tzinfo=timezone.utc), 2, 4, 1, 3),
            Bar(datetime(2026, 10, 19, tzinfo=timezone.utc), 3, 5, 2, 4),
        ]
        result = aggregate_closed_weeks(bars, datetime(2026, 10, 19, 12, tzinfo=timezone.utc))
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0].open, result[0].high, result[0].low, result[0].close), (1, 4, 0, 3))


if __name__ == "__main__":
    unittest.main()
