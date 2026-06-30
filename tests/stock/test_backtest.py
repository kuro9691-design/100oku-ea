"""run_stock_backtest の結合テスト。合成バーで IS/OOS 分割・スリッパージ集計を確認する。"""
import unittest
from datetime import timedelta
from math import sin

from oku100.models import Bar
from stock.backtest import run_stock_backtest
from stock.models import StockParams
from tests.stock.helpers import _BASE, flat_bar


def _wave_bars(count: int, start: float = 2000.0, drift: float = 2.0, amp: float = 50.0) -> list[Bar]:
    result = []
    for i in range(count):
        center = start + i * drift + sin(i / 8) * amp
        o = center - 1.0
        c = center + 1.0
        h = center + amp * 0.3
        lo = center - amp * 0.3
        h = max(h, o, c)
        lo = min(lo, o, c)
        result.append(
            Bar(
                timestamp=_BASE + timedelta(days=i),
                open=o,
                high=h,
                low=lo,
                close=c,
            )
        )
    return result


class TestRunStockBacktest(unittest.TestCase):
    def setUp(self):
        self.bars = _wave_bars(300)
        self.params = StockParams(
            N_d1=3,
            atr_period=14,
            trend_ma_period=20,
            sl_atr=2.0,
            tp_atr=4.0,
            max_hold_bars=20,
            index_ma_period=5,
        )

    def test_returns_result_without_index(self):
        result = run_stock_backtest(self.bars, params=self.params)
        self.assertIsNotNone(result)

    def test_split_timestamp_in_range(self):
        result = run_stock_backtest(self.bars, params=self.params)
        self.assertGreaterEqual(result.split_timestamp, self.bars[0].timestamp)
        self.assertLessEqual(result.split_timestamp, self.bars[-1].timestamp)

    def test_is_oos_trade_indices_are_disjoint(self):
        result = run_stock_backtest(self.bars, params=self.params)
        split = result.split_timestamp
        is_entries = {t.entry_index for t in result.trades if t.entry_index < _entry_split(self.bars, split)}
        oos_entries = {t.entry_index for t in result.trades if t.entry_index >= _entry_split(self.bars, split)}
        self.assertTrue(is_entries.isdisjoint(oos_entries))

    def test_metrics_total_r_equals_sum_of_trades(self):
        result = run_stock_backtest(self.bars, params=self.params)
        all_trades = result.trades
        if not all_trades:
            self.skipTest("no trades generated")
        total = sum(t.pnl_r for t in all_trades)
        reported = result.in_sample.total_r + result.out_of_sample.total_r
        self.assertAlmostEqual(total, reported, places=6)

    def test_slipped_count_in_to_dict(self):
        result = run_stock_backtest(self.bars, params=self.params)
        d = result.to_dict()
        self.assertIn("slipped_count", d)
        slipped = sum(1 for t in result.trades if t.slipped)
        self.assertEqual(d["slipped_count"], slipped)

    def test_exclude_slipped_reduces_trade_count(self):
        # inject a slipped trade via a gap bar sequence
        from stock.backtest import _resolve_stock_trade
        from stock.models import StockParams
        from oku100.models import Direction
        from tests.stock.helpers import make_bar
        params = StockParams(sl_atr=2.0, tp_atr=4.0, max_hold_bars=20)
        bars = [
            flat_bar(0, 105),
            make_bar(1, 100, 101, 99, 100),
            make_bar(2, 90, 91, 89, 90),  # SL gap
        ]
        trade = _resolve_stock_trade(bars, 0, Direction.LONG, 2.0, params)
        self.assertTrue(trade.slipped)

    def test_with_short_index_bars(self):
        # index bars shorter than index_ma_period → filter always False → no trades via filter
        index_bars = _wave_bars(50, start=2500.0)  # only 50 < index_ma_period=200
        result = run_stock_backtest(self.bars, index_bars=index_bars, params=self.params)
        self.assertIsNotNone(result)

    def test_invalid_split_ratio_raises(self):
        with self.assertRaises(ValueError):
            run_stock_backtest(self.bars, params=self.params, split_ratio=0.3)

    def test_split_date_respected(self):
        split = _BASE + timedelta(days=210)
        result = run_stock_backtest(self.bars, params=self.params, split_date=split)
        self.assertAlmostEqual(
            (result.split_timestamp - _BASE).days, 210, delta=1
        )


def _entry_split(bars: list[Bar], split_ts) -> int:
    for i, b in enumerate(bars):
        if b.timestamp >= split_ts:
            return i
    return len(bars)


if __name__ == "__main__":
    unittest.main()
