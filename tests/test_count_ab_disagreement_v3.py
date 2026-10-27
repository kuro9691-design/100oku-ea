import unittest

from scripts.count_ab_disagreement_v3 import compare_group, evidence_signature


class EvidenceSignatureTests(unittest.TestCase):
    def test_market_and_break_are_distinct(self):
        self.assertEqual("market", evidence_signature("a", "なし（成行）"))
        self.assertEqual("up:high", evidence_signature("a", "直近高値を上抜く足"))

    def test_ma_relation(self):
        self.assertEqual("above", evidence_signature("b", "MA20より上"))
        self.assertEqual("below", evidence_signature("b", "MA20の下側"))
        self.assertEqual("near", evidence_signature("b", "MA20付近"))


class DevelopmentAggregationTests(unittest.TestCase):
    def test_fixed_development_pair_counts(self):
        summary, rows = compare_group("dev")
        identification = summary["identification_and_time"]
        self.assertEqual(7, identification["target"])
        self.assertEqual(6, identification["both_identified"])
        self.assertEqual(2, identification["time_and_timeframe_same"])
        self.assertEqual(4, identification["same_timeframe_time_different"])
        self.assertEqual(7, len(rows))


if __name__ == "__main__":
    unittest.main()
