import unittest

from oku100.indicators import confirmed_pivots, trend_direction

from tests.helpers import bars


class IndicatorTests(unittest.TestCase):
    def test_pivots_are_confirmed_without_right_edge_future(self):
        data = bars(80, 1)
        pivots = confirmed_pivots(data, 50, 3)
        self.assertTrue(all(pivot.index <= 47 for pivot in pivots))

    def test_trend_direction_is_bounded(self):
        value = trend_direction(confirmed_pivots(bars(100, 1), 99, 3))
        self.assertIn(value, (-1, 0, 1))
