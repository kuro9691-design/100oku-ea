import unittest
from datetime import datetime, timezone

from oku100.leak import AccessAudit, CausalSeries, FutureLeakError
from oku100.leak_check import run_cross_timeframe_leak_check, run_leak_check
from oku100.pipeline import DecisionPipeline

from tests.helpers import bars


class LeakTests(unittest.TestCase):
    def test_causal_series_rejects_future(self):
        audit = AccessAudit(2)
        series = CausalSeries([1, 2, 3, 4], 2, audit)
        with self.assertRaises(IndexError):
            _ = series[3]

    def test_audit_rejects_future_directly(self):
        with self.assertRaises(FutureLeakError):
            AccessAudit(2).record(3)

    def test_pipeline_passes_leak_check(self):
        h1 = bars(180, 1)
        h4 = bars(80, 4)
        d1 = bars(50, 24)
        result = run_leak_check(d1, h4, h1, warmup=120)
        self.assertTrue(result.passed)

    def test_pipeline_passes_cross_timeframe_leak_check(self):
        """2026-07に発見した「decision_indexが未確定の当日/現在バケットを指す」
        バグの再発防止。run_leak_check()は緑でもこのバグを検知できなかった。"""
        h1 = bars(180, 1)
        h4 = bars(80, 4)
        d1 = bars(50, 24)
        result = run_cross_timeframe_leak_check(d1, h4, h1)
        self.assertTrue(result.passed)
        # 先頭付近はD1/H4のウォームアップ不足でスキップされるため、全数一致ではなく
        # 大部分がチェックされていることだけを確認する。
        self.assertGreater(result.checked_points, len(h1) // 2)

    def test_resolve_indexes_excludes_same_day_d1_bar_mid_day(self):
        """日中(境界から離れた時刻)のH1候補は、当日ではなく前日の確定D1足を指す。"""
        d1 = bars(10, 24)  # d1[0]=01-01, d1[1]=01-02, d1[2]=01-03, ...
        h4 = bars(60, 4)
        h1 = bars(240, 1)
        cutoff = datetime(2024, 1, 3, 7, 0, tzinfo=timezone.utc)
        d1_index, _, _ = DecisionPipeline._resolve_indexes(d1, h4, h1, cutoff)
        self.assertEqual(d1[d1_index].timestamp, datetime(2024, 1, 2, tzinfo=timezone.utc))

    def test_resolve_indexes_includes_same_day_d1_bar_at_last_hour(self):
        """23時始まりのH1候補(終値確定=翌日00:00)は、確定時刻を跨ぐ当日分の
        D1足を正しく「確定済み」として参照できる(+1時間補正が無いと1日余分に
        古い足を参照してしまう=過度に保守的なバグになる)。"""
        d1 = bars(10, 24)
        h4 = bars(60, 4)
        h1 = bars(240, 1)
        cutoff = datetime(2024, 1, 3, 23, 0, tzinfo=timezone.utc)
        d1_index, _, _ = DecisionPipeline._resolve_indexes(d1, h4, h1, cutoff)
        self.assertEqual(d1[d1_index].timestamp, datetime(2024, 1, 3, tzinfo=timezone.utc))
