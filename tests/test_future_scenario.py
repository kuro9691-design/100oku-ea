from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime

import numpy as np

from oku100.io import read_bars
from scripts.render_future_scenario import (
    build_scenario,
    project_flat_future_ma_at_judgment,
    project_ma_lines,
    scenario_geometry_warnings,
)


class FutureScenarioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.h1 = read_bars("data/h1.csv")
        cls.h4 = read_bars("data/h4.csv")

    def test_future_rows_do_not_change_scenario(self) -> None:
        ts = datetime.fromisoformat("2024-07-27T12:00:00+00:00")
        full, _ = build_scenario(self.h1, self.h4, ts, "buy")
        h1_past = [bar for bar in self.h1 if bar.timestamp < ts]
        h4_past = [bar for bar in self.h4 if bar.timestamp < ts]
        past_only, _ = build_scenario(h1_past, h4_past, ts, "buy")

        self.assertEqual(full, past_only)

    def test_scenario_has_explicit_invalidation_and_target(self) -> None:
        ts = datetime.fromisoformat("2024-07-27T12:00:00+00:00")
        scenario, _ = build_scenario(self.h1, self.h4, ts, "buy")

        self.assertLess(scenario.invalidation, scenario.trigger)
        self.assertGreater(scenario.target_1, scenario.trigger)
        self.assertGreater(scenario.h1_atr, 0)

    def test_buy_warns_when_invalidation_is_not_below_support(self) -> None:
        ts = datetime.fromisoformat("2024-07-27T12:00:00+00:00")
        scenario, _ = build_scenario(self.h1, self.h4, ts, "buy")

        self.assertEqual(scenario.invalidation, 67630.0)
        self.assertEqual(scenario.support_or_resistance, 67598.0)
        self.assertEqual(
            scenario.geometry_warnings,
            ["BUY_INVALIDATION_NOT_BELOW_SUPPORT"],
        )

    def test_geometry_warning_is_symmetric_and_diagnostic_only(self) -> None:
        self.assertEqual(
            scenario_geometry_warnings("sell", 100.0, 101.0),
            ["SELL_INVALIDATION_NOT_ABOVE_RESISTANCE"],
        )
        self.assertEqual(scenario_geometry_warnings("buy", 99.0, 100.0), [])
        self.assertEqual(scenario_geometry_warnings("sell", 101.0, 100.0), [])

    def test_projected_ma_uses_only_history_and_conditional_closes(self) -> None:
        history = [float(i) for i in range(1, 501)]
        future = [501.0, 502.0, 503.0]

        lines = project_ma_lines(history, future, [20, 80, 480])

        self.assertEqual(lines[20][0], sum(range(482, 502)) / 20)
        self.assertEqual(lines[80][0], sum(range(422, 502)) / 80)
        self.assertEqual(lines[480][0], sum(range(22, 502)) / 480)
        self.assertEqual(len(lines[20]), len(future))

    def test_ph52_projection_is_unchanged_when_actual_future_rows_change(self) -> None:
        for timestamp in (
            "2024-07-27T12:00:00+00:00",
            "2026-01-13T09:00:00+00:00",
        ):
            with self.subTest(timestamp=timestamp):
                ts = datetime.fromisoformat(timestamp)
                expected, end_idx = project_flat_future_ma_at_judgment(self.h1, ts)
                changed = list(self.h1)
                for index in range(end_idx + 1, len(changed)):
                    value = float("nan") if index % 2 else 1.0e12
                    changed[index] = replace(
                        changed[index], open=value, high=value, low=value, close=value,
                    )

                actual, changed_end_idx = project_flat_future_ma_at_judgment(changed, ts)

                self.assertEqual(changed_end_idx, end_idx)
                for period in (20, 80, 480):
                    np.testing.assert_array_equal(actual[period], expected[period])

    def test_ph52_ma480_is_unavailable_without_480_confirmed_rows(self) -> None:
        history = [float(i) for i in range(1, 480)]

        lines = project_ma_lines(history, [479.0] * 48, [20, 80, 480])

        self.assertTrue(all(np.isnan(value) for value in lines[480]))
        self.assertTrue(all(np.isfinite(value) for value in lines[20]))
        self.assertTrue(all(np.isfinite(value) for value in lines[80]))


if __name__ == "__main__":
    unittest.main()
