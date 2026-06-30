import unittest
from datetime import timedelta

from stock.market_filter import IndexFilter
from stock.models import StockParams
from tests.stock.helpers import flat_bar, _BASE

_PARAMS_200 = StockParams(index_ma_period=200)
_PARAMS_5 = StockParams(index_ma_period=5)


def _rising_bars(count: int, start: float = 100.0, step: float = 1.0):
    return [flat_bar(i, start + i * step) for i in range(count)]


def _falling_bars(count: int, start: float = 200.0, step: float = 1.0):
    return [flat_bar(i, start - i * step) for i in range(count)]


class TestIndexFilterLong(unittest.TestCase):
    def test_favorable_when_close_above_ma(self):
        # MA5 of [100,101,102,103,104] = 102; close = 104 > 102
        bars = _rising_bars(10, start=100.0, step=1.0)
        f = IndexFilter(bars, _PARAMS_5)
        as_of = _BASE + timedelta(days=9)
        self.assertTrue(f.is_favorable(as_of, direction=1))

    def test_unfavorable_when_close_below_ma(self):
        # falling bars: close decreases, close < MA
        bars = _falling_bars(10, start=200.0)
        f = IndexFilter(bars, _PARAMS_5)
        as_of = _BASE + timedelta(days=9)
        self.assertFalse(f.is_favorable(as_of, direction=1))

    def test_unfavorable_before_warmup(self):
        bars = _rising_bars(3, start=100.0)
        f = IndexFilter(bars, _PARAMS_5)
        as_of = _BASE + timedelta(days=2)
        self.assertFalse(f.is_favorable(as_of, direction=1))

    def test_cutoff_before_all_bars_returns_false(self):
        bars = _rising_bars(5, start=100.0)
        f = IndexFilter(bars, _PARAMS_5)
        as_of = _BASE - timedelta(days=1)
        self.assertFalse(f.is_favorable(as_of, direction=1))


class TestIndexFilterShort(unittest.TestCase):
    def test_favorable_short_when_close_below_ma(self):
        bars = _falling_bars(10, start=200.0)
        f = IndexFilter(bars, _PARAMS_5)
        as_of = _BASE + timedelta(days=9)
        self.assertTrue(f.is_favorable(as_of, direction=-1))

    def test_unfavorable_short_when_close_above_ma(self):
        bars = _rising_bars(10, start=100.0)
        f = IndexFilter(bars, _PARAMS_5)
        as_of = _BASE + timedelta(days=9)
        self.assertFalse(f.is_favorable(as_of, direction=-1))


if __name__ == "__main__":
    unittest.main()
