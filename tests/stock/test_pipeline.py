import unittest
from datetime import timedelta
from math import sin

from oku100.models import Bar, Direction
from stock.market_filter import IndexFilter
from stock.models import StockParams
from stock.pipeline import StockPipeline
from tests.stock.helpers import _BASE, flat_bar


def _sine_bars(count: int, start: float = 100.0, amplitude: float = 5.0, drift: float = 0.3) -> list[Bar]:
    """上昇ドリフト付き正弦波バー。上昇トレンドのピボットを自然に生成する。"""
    result = []
    for i in range(count):
        center = start + i * drift + sin(i / 4) * amplitude
        open_ = center - 0.2
        close = center + 0.2
        high = center + amplitude * 0.4
        low = center - amplitude * 0.4
        high = max(high, open_, close)
        low = min(low, open_, close)
        result.append(
            Bar(
                timestamp=_BASE + timedelta(days=i),
                open=open_,
                high=high,
                low=low,
                close=close,
            )
        )
    return result


class TestStockPipelineNoSignal(unittest.TestCase):
    def test_too_few_bars_raises(self):
        params = StockParams(N_d1=3, trend_ma_period=5, atr_period=5)
        pipeline = StockPipeline(params)
        bars = [flat_bar(i, 100) for i in range(5)]
        # as_of before first bar
        with self.assertRaises(ValueError):
            pipeline.evaluate(bars, _BASE - timedelta(days=1))

    def test_flat_bars_return_no_trend(self):
        params = StockParams(N_d1=3, trend_ma_period=10, atr_period=5)
        pipeline = StockPipeline(params)
        bars = [flat_bar(i, 100) for i in range(50)]
        signal = pipeline.evaluate(bars, bars[-1].timestamp)
        self.assertFalse(signal.actionable)

    def test_allowed_directions_long_only_blocks_short(self):
        params = StockParams(
            N_d1=3, trend_ma_period=10, atr_period=5,
            allowed_directions=("long",),
        )
        # falling bars create downtrend
        bars = [flat_bar(i, 200 - i) for i in range(50)]
        pipeline = StockPipeline(params)
        signal = pipeline.evaluate(bars, bars[-1].timestamp)
        # Short should be blocked even if trend is down
        self.assertFalse(signal.actionable)
        if not signal.actionable:
            self.assertIn(signal.reason, ("no_trend", "no_breakout", "no_pivot", "price_far_from_ma"))


class TestStockPipelineWithMarketFilter(unittest.TestCase):
    def test_market_filter_blocks_long_when_index_below_ma(self):
        params = StockParams(N_d1=3, trend_ma_period=10, atr_period=5, index_ma_period=5)
        # Uptrend stock bars
        bars = _sine_bars(60, drift=0.5)
        # Falling index bars so close < MA5 → filter blocks long
        index_bars = [flat_bar(i, 200 - i) for i in range(60)]
        index_filter = IndexFilter(index_bars, params)
        pipeline = StockPipeline(params, index_filter)
        # Check several bars; any actionable long should be absent
        blocked = all(
            not pipeline.evaluate(bars, bars[i].timestamp).actionable
            for i in range(15, 60)
        )
        self.assertTrue(blocked)


class TestSignalFields(unittest.TestCase):
    def test_signal_has_positive_atr(self):
        params = StockParams(N_d1=3, trend_ma_period=10, atr_period=5)
        bars = _sine_bars(60, drift=0.5)
        pipeline = StockPipeline(params)
        signal = pipeline.evaluate(bars, bars[-1].timestamp)
        self.assertGreater(signal.atr_value, 0)

    def test_signal_timestamp_matches_as_of_bar(self):
        params = StockParams(N_d1=3, trend_ma_period=10, atr_period=5)
        bars = _sine_bars(60, drift=0.5)
        pipeline = StockPipeline(params)
        as_of = bars[40].timestamp
        signal = pipeline.evaluate(bars, as_of)
        self.assertEqual(signal.timestamp, bars[40].timestamp)


if __name__ == "__main__":
    unittest.main()
