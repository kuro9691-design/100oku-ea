import unittest

from scripts.render_visual_audit_3_12_v2 import choose_development_samples


class VisualAuditV2SelectionTests(unittest.TestCase):
    def setUp(self):
        self.manifest = [
            {"id": "P1", "symbol": "BTC", "judgment_ts": "2026-01-01T01:00:00+00:00", "ts_source": "old"},
            {"id": "N1", "symbol": "ETH", "judgment_ts": "2026-01-01T02:00:00+00:00", "ts_source": "old"},
            {"id": "F1", "symbol": "BTC", "judgment_ts": "2026-01-01T03:00:00+00:00", "ts_source": "old"},
        ]

    def test_positive_uses_v2_and_control_stays_unchanged(self):
        selected = choose_development_samples(
            self.manifest,
            {"P1": "positive", "N1": "negative"},
            {"F1"},
            {"P1": "2026-01-02T04:00:00+00:00"},
        )
        by_id = {sample["id"]: sample for sample in selected}
        self.assertEqual(by_id["P1"]["judgment_ts"], "2026-01-02T04:00:00+00:00")
        self.assertEqual(by_id["P1"]["ts_source"], "v2")
        self.assertEqual(by_id["N1"]["judgment_ts"], "2026-01-01T02:00:00+00:00")
        self.assertEqual(by_id["N1"]["ts_source"], "old")

    def test_unidentified_positive_is_not_rendered(self):
        selected = choose_development_samples(
            self.manifest,
            {"P1": "positive", "N1": "negative"},
            {"F1"},
            {},
        )
        self.assertEqual([sample["id"] for sample in selected], ["N1"])

    def test_final_id_is_always_rejected(self):
        with self.assertRaises(ValueError):
            choose_development_samples(
                self.manifest,
                {"F1": "positive"},
                {"F1"},
                {"F1": "2026-01-02T04:00:00+00:00"},
            )


if __name__ == "__main__":
    unittest.main()
