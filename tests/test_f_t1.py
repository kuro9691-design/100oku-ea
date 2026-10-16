"""F judges RR to the first take-profit line T1 (docs/execution_spec.md 7-5)."""
import unittest
from unittest.mock import patch

from oku100 import indicators
from oku100.models import Params, Pivot
from oku100.pipeline import DecisionPipeline
from tests.helpers import bars
from tests.test_split_targets import state


def clear_caches():
    for name in ("_PIVOT_CACHE", "_SMA_CACHE", "_ATR_CACHE"):
        getattr(indicators, name).clear()


class FirstTargetTests(unittest.TestCase):
    def setUp(self):
        clear_caches()
        self.pipeline = DecisionPipeline()

    def first(self, h4_lines, d1_prices, d1_ma=80, entry=100.0, direction=1):
        h4 = state([], fast_ma=90, close=90)
        d1 = state(d1_prices, fast_ma=d1_ma, close=80)
        with patch.object(self.pipeline, "_h4_lines", return_value=h4_lines):
            return self.pipeline._first_target(d1, h4, entry, direction)

    def test_nearest_h4_line_is_t1_even_when_near(self):
        self.assertEqual(self.first([100.6, 104], [120]), 100.6)

    def test_trigger_line_is_not_t1(self):
        self.assertEqual(self.first([100.3, 104], [120]), 104)

    def test_d1_structure_when_no_h4_level(self):
        self.assertEqual(self.first([], [108, 115]), 108)

    def test_d1_ma_when_no_pivot(self):
        self.assertEqual(self.first([], [], d1_ma=111), 111)

    def test_none_when_no_structure_ahead(self):
        self.assertIsNone(self.first([95], [90]))

    def test_short_mirror(self):
        self.assertEqual(self.first([99.4, 96], [80], d1_ma=120, direction=-1), 99.4)


class FCriterionTests(unittest.TestCase):
    def score(self, t1_offset, params=Params()):
        clear_caches()
        pipeline = DecisionPipeline(params)
        d1, h4, h1 = bars(220, 24, 0.8), bars(400, 4, 0.4), bars(1000, 1)
        states = pipeline._states((d1, h4, h1), (200, 380, 990))
        entry = h1[990].close
        stop_pivots = [Pivot(980, h1[980].timestamp, entry - 1.0, "low")]
        t1 = None if t1_offset is None else entry + t1_offset
        with patch.object(pipeline, "_first_target", return_value=t1):
            return pipeline._score_direction(1, *states, 0, stop_entry=None, stop_pivots=stop_pivots)

    def test_rr_one_passes(self):
        self.assertTrue(self.score(1.0)["criteria"]["F"].passed)

    def test_rr_below_one_fails(self):
        self.assertFalse(self.score(0.9)["criteria"]["F"].passed)

    def test_no_target_fails(self):
        self.assertFalse(self.score(None)["criteria"]["F"].passed)

    def test_old_rule_when_disabled(self):
        result = self.score(0.1, Params(f_uses_t1=False))
        expected = result["rr"] is not None and result["rr"] >= Params().MinRR
        self.assertEqual(result["criteria"]["F"].passed, expected)
        self.assertTrue(result["criteria"]["F"].evidence.startswith("RR="))

    def test_minimum_rr_is_source_value(self):
        self.assertEqual(Params().f_min_rr, 1.0)


if __name__ == "__main__":
    unittest.main()
