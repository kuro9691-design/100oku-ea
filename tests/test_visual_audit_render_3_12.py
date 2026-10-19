import unittest
import math
from datetime import datetime, timedelta, timezone

from oku100.models import Bar
from scripts.render_candidate_charts import (
    MA_COLOR,
    MA_PERIODS_D1,
    MA_PERIODS_H1,
    MA_PERIODS_H4,
    MA_PERIODS_M15,
    MA_PERIODS_W1,
)
from scripts.visual_audit_render_3_12 import (
    PERIODS,
    WINDOWS,
    confirmed_before,
    prepare_panels,
    reject_final_ids,
)


def make_bars(start, count, step):
    return [Bar(start + i * step, 100 + i, 102 + i, 99 + i, 101 + i) for i in range(count)]


class FiveTimeframeRenderTests(unittest.TestCase):
    def setUp(self):
        start = datetime(2020, 1, 6, tzinfo=timezone.utc)
        self.data = {
            "d1": make_bars(start, 1300, timedelta(days=1)),
            "h4": make_bars(start, 8000, timedelta(hours=4)),
            "h1": make_bars(start, 32000, timedelta(hours=1)),
            "m15": make_bars(start, 128000, timedelta(minutes=15)),
        }
        self.cutoff = start + timedelta(days=1200, hours=10, minutes=7)

    def test_excludes_bars_closing_after_judgment(self):
        for timeframe in ("d1", "h4", "h1", "m15"):
            selected = confirmed_before(self.data[timeframe], self.cutoff, timeframe)
            self.assertTrue(selected)
            lengths = {"d1": timedelta(days=1), "h4": timedelta(hours=4), "h1": timedelta(hours=1), "m15": timedelta(minutes=15)}
            self.assertLessEqual(selected[-1].timestamp + lengths[timeframe], self.cutoff)
            next_index = len(selected)
            if next_index < len(self.data[timeframe]):
                self.assertGreater(self.data[timeframe][next_index].timestamp + lengths[timeframe], self.cutoff)

    def test_open_week_day_and_h4_are_excluded(self):
        panels = prepare_panels(self.data, self.cutoff)
        self.assertLessEqual(panels["w1"].bars[-1].timestamp + timedelta(days=7), self.cutoff)
        self.assertLessEqual(panels["d1"].bars[-1].timestamp + timedelta(days=1), self.cutoff)
        self.assertLessEqual(panels["h4"].bars[-1].timestamp + timedelta(hours=4), self.cutoff)

    def test_fixed_display_counts(self):
        panels = prepare_panels(self.data, self.cutoff)
        self.assertEqual({tf: len(panel.bars) for tf, panel in panels.items()}, WINDOWS)

    def test_future_changes_do_not_change_panels(self):
        original = prepare_panels(self.data, self.cutoff)
        changed = {tf: list(bars) for tf, bars in self.data.items()}
        for timeframe, bars in changed.items():
            for index, bar in enumerate(bars):
                if bar.timestamp > self.cutoff:
                    bars[index] = Bar(bar.timestamp, 9000, 9002, 8999, 9001)
        mutated = prepare_panels(changed, self.cutoff)
        for timeframe in original:
            self.assertEqual(original[timeframe].bars, mutated[timeframe].bars)
            for period in PERIODS[timeframe]:
                before = original[timeframe].ma_values[period]
                after = mutated[timeframe].ma_values[period]
                self.assertEqual(len(before), len(after))
                for left, right in zip(before, after):
                    self.assertTrue((math.isnan(left) and math.isnan(right)) or left == right)

    def test_ma_constants_are_imported_standard(self):
        self.assertIs(PERIODS["w1"], MA_PERIODS_W1)
        self.assertIs(PERIODS["d1"], MA_PERIODS_D1)
        self.assertIs(PERIODS["h4"], MA_PERIODS_H4)
        self.assertIs(PERIODS["h1"], MA_PERIODS_H1)
        self.assertIs(PERIODS["m15"], MA_PERIODS_M15)
        for timeframe, periods in PERIODS.items():
            self.assertEqual(set(periods), set(MA_COLOR[timeframe]))

    def test_final_test_ids_rejected_by_default(self):
        with self.assertRaises(ValueError):
            reject_final_ids({"S02"}, {"S02"}, False)
        reject_final_ids({"S02"}, {"S02"}, True)


if __name__ == "__main__":
    unittest.main()
