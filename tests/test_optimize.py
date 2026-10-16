import unittest

from oku100.models import Params
from oku100.optimize import optimize

from tests.helpers import bars


class OptimizeTests(unittest.TestCase):
    def test_optimizer_returns_a_list(self):
        result = optimize(
            bars(60, 24, 0.8),
            bars(100, 4, 0.4),
            bars(240, 1),
            [Params()],
        )
        self.assertIsInstance(result, list)
