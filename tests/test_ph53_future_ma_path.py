from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime

from oku100.io import read_bars
from scripts.ph53_future_ma_path import measure_case, measure_direction


class PH53FutureMAPathTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.d1 = read_bars("data/d1.csv")
        cls.h4 = read_bars("data/h4.csv")
        cls.h1 = read_bars("data/h1.csv")

    @staticmethod
    def _replace_future(bars, judgment_ts):
        changed = []
        for index, bar in enumerate(bars):
            if bar.timestamp < judgment_ts:
                changed.append(bar)
                continue
            value = 1.0e12 if index % 2 == 0 else -1.0e12
            changed.append(replace(bar, open=value, high=value, low=value, close=value))
        return changed

    def test_ph53_is_unchanged_when_actual_future_rows_are_extreme(self) -> None:
        timestamp = "2024-07-27T12:00:00+00:00"
        judgment = datetime.fromisoformat(timestamp)
        expected = measure_case(self.d1, self.h4, self.h1, timestamp, "buy")
        actual = measure_case(
            self._replace_future(self.d1, judgment),
            self._replace_future(self.h4, judgment),
            self._replace_future(self.h1, judgment),
            timestamp,
            "buy",
        )
        self.assertEqual(actual, expected)

    def test_control_both_directions_are_causal_under_future_replacement(self) -> None:
        timestamp = "2025-02-15T17:00:00+00:00"
        judgment = datetime.fromisoformat(timestamp)
        expected = measure_case(self.d1, self.h4, self.h1, timestamp, None)
        actual = measure_case(
            self._replace_future(self.d1, judgment),
            self._replace_future(self.h4, judgment),
            self._replace_future(self.h1, judgment),
            timestamp,
            None,
        )
        self.assertEqual(actual, expected)

    def test_sma_update_formula_matches_direct_two_close_recalculation(self) -> None:
        result = measure_direction(
            self.d1, self.h4, self.h1,
            "2026-01-13T09:00:00+00:00", "buy",
        )
        self.assertEqual(result.path_status, "valid")
        self.assertLess(result.formula_max_abs_error, 1.0e-9)


if __name__ == "__main__":
    unittest.main()
