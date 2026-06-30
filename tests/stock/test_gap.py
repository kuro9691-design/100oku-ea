"""ギャップ約定のユニットテスト。

(a) 保有中にSLを下に飛び越える窓  → pnl_r が -1.0 より悪化、slipped=True
(b) 保有中にTPを上に飛び越える窓  → pnl_r が 計画RRより良化、slipped=True
(c) エントリーバーではギャップ判定が発火しない（通常SL: pnl_r=-1.0, slipped=False）
"""
import unittest

from oku100.models import Direction
from stock.backtest import _resolve_stock_trade
from stock.models import StockParams
from tests.stock.helpers import flat_bar, make_bar

# 共通セットアップ
# fill_price=100, sl_atr=2.0, atr=2.0 → risk=4.0, stop=96, target=108
# 計画RR = tp_atr / sl_atr = 4.0 / 2.0 = 2.0
_PARAMS = StockParams(sl_atr=2.0, tp_atr=4.0, max_hold_bars=20)
_ATR = 2.0
_FILL = 100.0
_RISK = _PARAMS.sl_atr * _ATR   # 4.0
_STOP = _FILL - _RISK            # 96.0
_TARGET = _FILL + _PARAMS.tp_atr * _ATR  # 108.0
_PLANNED_RR = _PARAMS.tp_atr / _PARAMS.sl_atr  # 2.0


class TestSlGap(unittest.TestCase):
    """(a) 保有中に open がSLを下回る窓"""

    def _trade(self, gap_open: float) -> object:
        bars = [
            flat_bar(0, 105),                        # signal bar (index=0)
            make_bar(1, _FILL, 101, 99, 100),        # entry bar  (index=1)
            make_bar(2, gap_open, gap_open + 0.5, gap_open - 0.5, gap_open),  # gap bar
        ]
        return _resolve_stock_trade(bars, 0, Direction.LONG, _ATR, _PARAMS)

    def test_pnl_worse_than_minus_one(self):
        trade = self._trade(gap_open=90.0)
        self.assertLess(trade.pnl_r, -1.0)

    def test_pnl_value(self):
        trade = self._trade(gap_open=90.0)
        # pnl_r = (90 - 100) / 4 = -2.5
        self.assertAlmostEqual(trade.pnl_r, -2.5, places=9)

    def test_slipped_true(self):
        trade = self._trade(gap_open=90.0)
        self.assertTrue(trade.slipped)

    def test_exit_at_gap_open(self):
        trade = self._trade(gap_open=90.0)
        self.assertAlmostEqual(trade.exit_price, 90.0, places=9)

    def test_reason_is_stop(self):
        trade = self._trade(gap_open=90.0)
        self.assertEqual(trade.reason, "stop")

    def test_exit_index_is_gap_bar(self):
        trade = self._trade(gap_open=90.0)
        self.assertEqual(trade.exit_index, 2)

    def test_sl_gap_short(self):
        """売り版: open が SL を上抜け → pnl_r < -1.0, slipped=True"""
        # fill=100 short: stop=104, target=92
        bars = [
            flat_bar(0, 95),
            make_bar(1, _FILL, 101, 99, 100),
            make_bar(2, 110.0, 111, 109, 110),  # gap above stop=104
        ]
        trade = _resolve_stock_trade(bars, 0, Direction.SHORT, _ATR, _PARAMS)
        self.assertTrue(trade.slipped)
        self.assertLess(trade.pnl_r, -1.0)
        self.assertAlmostEqual(trade.pnl_r, (100.0 - 110.0) / _RISK, places=9)


class TestTpGap(unittest.TestCase):
    """(b) 保有中に open がTPを上回る窓"""

    def _trade(self, gap_open: float) -> object:
        bars = [
            flat_bar(0, 105),
            make_bar(1, _FILL, 101, 99, 100),
            make_bar(2, gap_open, gap_open + 0.5, gap_open - 0.5, gap_open),
        ]
        return _resolve_stock_trade(bars, 0, Direction.LONG, _ATR, _PARAMS)

    def test_pnl_better_than_planned_rr(self):
        trade = self._trade(gap_open=115.0)
        self.assertGreater(trade.pnl_r, _PLANNED_RR)

    def test_pnl_value(self):
        trade = self._trade(gap_open=115.0)
        # pnl_r = (115 - 100) / 4 = 3.75
        self.assertAlmostEqual(trade.pnl_r, 3.75, places=9)

    def test_slipped_true(self):
        trade = self._trade(gap_open=115.0)
        self.assertTrue(trade.slipped)

    def test_exit_at_gap_open(self):
        trade = self._trade(gap_open=115.0)
        self.assertAlmostEqual(trade.exit_price, 115.0, places=9)

    def test_reason_is_target(self):
        trade = self._trade(gap_open=115.0)
        self.assertEqual(trade.reason, "target")

    def test_tp_gap_short(self):
        """売り版: open が TP を下抜け → pnl_r > 計画RR, slipped=True"""
        bars = [
            flat_bar(0, 95),
            make_bar(1, _FILL, 101, 99, 100),
            make_bar(2, 88.0, 89, 87, 88),  # gap below target=92
        ]
        trade = _resolve_stock_trade(bars, 0, Direction.SHORT, _ATR, _PARAMS)
        self.assertTrue(trade.slipped)
        self.assertGreater(trade.pnl_r, _PLANNED_RR)


class TestNoGapOnEntryBar(unittest.TestCase):
    """(c) エントリーバー（index == signal_index+1）ではギャップ判定が発火しない。
    エントリーバーの low が stop を下回っても、slipped=False・pnl_r=-1.0 になること。
    """

    def test_entry_bar_low_triggers_normal_sl_not_gap(self):
        # fill=100, stop=96, target=108
        # entry bar (index=1): open=100, low=90 (< stop=96)
        # → ギャップチェックは index>1 のみ → 発火しない
        # → 通常 intrabar チェック: low<=stop → SL確定, slipped=False
        bars = [
            flat_bar(0, 105),
            make_bar(1, _FILL, 101, 90, 99),  # entry bar: low=90 < stop=96
        ]
        trade = _resolve_stock_trade(bars, 0, Direction.LONG, _ATR, _PARAMS)
        self.assertIsNotNone(trade)
        self.assertFalse(trade.slipped)
        self.assertAlmostEqual(trade.pnl_r, -1.0, places=9)
        self.assertEqual(trade.exit_price, _STOP)
        self.assertEqual(trade.exit_index, 1)

    def test_entry_bar_high_triggers_normal_tp_not_gap(self):
        # entry bar: open=100, high=115 (> target=108)
        # → ギャップチェックは発火しない → 通常 TP確定, slipped=False
        bars = [
            flat_bar(0, 105),
            make_bar(1, _FILL, 115, 99, 110),  # entry bar: high=115 > target=108
        ]
        trade = _resolve_stock_trade(bars, 0, Direction.LONG, _ATR, _PARAMS)
        self.assertIsNotNone(trade)
        self.assertFalse(trade.slipped)
        self.assertAlmostEqual(trade.pnl_r, _PLANNED_RR, places=9)
        self.assertEqual(trade.exit_index, 1)

    def test_entry_bar_both_sl_and_tp_hit_conservative(self):
        # entry bar: low<stop AND high>target → same-bar ambiguity → stop優先, slipped=False
        bars = [
            flat_bar(0, 105),
            make_bar(1, _FILL, 115, 90, 100),
        ]
        trade = _resolve_stock_trade(bars, 0, Direction.LONG, _ATR, _PARAMS)
        self.assertFalse(trade.slipped)
        self.assertAlmostEqual(trade.pnl_r, -1.0, places=9)
        self.assertEqual(trade.reason, "stop")


class TestGapBothSlAndTp(unittest.TestCase):
    """極端な窓で SL/TP 両方を飛び越える → 保守的に stop, slipped=True"""

    def test_gap_through_both_is_stop(self):
        # open=80 は stop(96) も target(108) も通り越している（ありえないが境界テスト）
        # stop=96 < target=108、open=80 < stop=96 → open_past_stop=True が先に判定
        bars = [
            flat_bar(0, 105),
            make_bar(1, _FILL, 101, 99, 100),
            make_bar(2, 80.0, 81, 79, 80),
        ]
        trade = _resolve_stock_trade(bars, 0, Direction.LONG, _ATR, _PARAMS)
        self.assertTrue(trade.slipped)
        self.assertEqual(trade.reason, "stop")
        self.assertLess(trade.pnl_r, -1.0)


class TestNormalExits(unittest.TestCase):
    """ギャップなし: 通常SL/TP/時間切れ"""

    def test_normal_sl_slipped_false(self):
        bars = [
            flat_bar(0, 105),
            make_bar(1, _FILL, 101, 99, 100),
            make_bar(2, 97, 98, 95, 96),   # low=95 < stop=96
        ]
        trade = _resolve_stock_trade(bars, 0, Direction.LONG, _ATR, _PARAMS)
        self.assertFalse(trade.slipped)
        self.assertAlmostEqual(trade.pnl_r, -1.0, places=9)
        self.assertEqual(trade.reason, "stop")

    def test_normal_tp_slipped_false(self):
        bars = [
            flat_bar(0, 105),
            make_bar(1, _FILL, 101, 99, 100),
            make_bar(2, 107, 109, 106, 108),  # high=109 > target=108
        ]
        trade = _resolve_stock_trade(bars, 0, Direction.LONG, _ATR, _PARAMS)
        self.assertFalse(trade.slipped)
        self.assertAlmostEqual(trade.pnl_r, _PLANNED_RR, places=9)
        self.assertEqual(trade.reason, "target")

    def test_time_exit(self):
        params = StockParams(sl_atr=2.0, tp_atr=4.0, max_hold_bars=3)
        bars = [flat_bar(i, 100) for i in range(6)]
        trade = _resolve_stock_trade(bars, 0, Direction.LONG, _ATR, params)
        self.assertFalse(trade.slipped)
        self.assertEqual(trade.reason, "time_exit")

    def test_no_entry_bar_returns_none(self):
        bars = [flat_bar(0, 105)]
        trade = _resolve_stock_trade(bars, 0, Direction.LONG, _ATR, _PARAMS)
        self.assertIsNone(trade)


if __name__ == "__main__":
    unittest.main()
