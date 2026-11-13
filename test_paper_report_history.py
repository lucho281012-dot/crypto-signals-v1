import copy
import json
import unittest

from paper_report_history import (
    append_report_snapshot,
    build_report_snapshot,
    deserialize_report_history,
    serialize_report_history,
    validate_report_history,
)


class PaperReportHistoryTests(unittest.TestCase):
    def setUp(self):
        self.report = {
            "quote_currency": "USDT",
            "equity_usdt": "1022.27",
            "total_pnl_usdt": "22.27",
            "positions": {"BTC": {"quantity": "0.75"}},
        }

    def snapshot(self, snapshot_id="snap-001", captured_at="2026-11-13T10:00:00-06:00"):
        return build_report_snapshot(self.report, captured_at, snapshot_id)

    def test_build_snapshot_normalizes_timestamp_to_utc(self):
        snapshot = self.snapshot()
        self.assertEqual(snapshot["captured_at"], "2026-11-13T16:00:00Z")
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(snapshot["snapshot_id"], "snap-001")

    def test_build_snapshot_detaches_report(self):
        original = copy.deepcopy(self.report)
        snapshot = self.snapshot()
        self.report["equity_usdt"] = "0"
        self.assertEqual(snapshot["report"], original)

    def test_snapshot_rejects_naive_timestamp(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            self.snapshot(captured_at="2026-11-13T10:00:00")

    def test_snapshot_rejects_invalid_timestamp(self):
        with self.assertRaisesRegex(ValueError, "ISO-8601"):
            self.snapshot(captured_at="yesterday")

    def test_snapshot_rejects_empty_id_and_report(self):
        with self.assertRaisesRegex(ValueError, "snapshot_id"):
            build_report_snapshot(self.report, "2026-11-13T10:00:00Z", " ")
        with self.assertRaisesRegex(ValueError, "report"):
            build_report_snapshot({}, "2026-11-13T10:00:00Z", "id")

    def test_snapshot_rejects_non_json_and_non_finite_values(self):
        with self.assertRaisesRegex(ValueError, "JSON-compatible"):
            build_report_snapshot({"bad": float("nan")}, "2026-11-13T10:00:00Z", "id")

    def test_append_is_immutable_and_preserves_order(self):
        first = self.snapshot()
        second = self.snapshot("snap-002", "2026-11-13T10:01:00-06:00")
        original = [first]
        original_copy = copy.deepcopy(original)
        updated = append_report_snapshot(original, second)
        self.assertEqual(original, original_copy)
        self.assertEqual([item["snapshot_id"] for item in updated], ["snap-001", "snap-002"])

    def test_append_rejects_duplicate_id(self):
        first = self.snapshot()
        duplicate = self.snapshot("snap-001", "2026-11-13T10:01:00-06:00")
        with self.assertRaisesRegex(ValueError, "duplicate snapshot_id"):
            append_report_snapshot([first], duplicate)

    def test_append_rejects_non_increasing_timestamp(self):
        first = self.snapshot()
        earlier = self.snapshot("snap-002", "2026-11-13T09:59:00-06:00")
        same_time = self.snapshot("snap-003", "2026-11-13T10:00:00-06:00")
        with self.assertRaisesRegex(ValueError, "later"):
            append_report_snapshot([first], earlier)
        with self.assertRaisesRegex(ValueError, "later"):
            append_report_snapshot([first], same_time)

    def test_validator_rejects_duplicate_ids_and_bad_schema(self):
        first = self.snapshot()
        duplicate = self.snapshot("snap-001", "2026-11-13T10:01:00-06:00")
        with self.assertRaisesRegex(ValueError, "duplicate snapshot_id"):
            validate_report_history([first, duplicate])
        bad = dict(first, schema_version=2)
        with self.assertRaisesRegex(ValueError, "schema_version"):
            validate_report_history([bad])

    def test_round_trip_serialization_is_deterministic(self):
        history = [
            self.snapshot(),
            self.snapshot("snap-002", "2026-11-13T10:01:00-06:00"),
        ]
        payload = serialize_report_history(history)
        self.assertEqual(payload, serialize_report_history(history))
        self.assertEqual(deserialize_report_history(payload), history)
        self.assertEqual(json.loads(payload)[0]["report"]["equity_usdt"], "1022.27")

    def test_deserializer_rejects_malformed_or_invalid_history(self):
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            deserialize_report_history("{broken")
        with self.assertRaisesRegex(ValueError, "list"):
            deserialize_report_history('{"not":"a list"}')
        with self.assertRaisesRegex(ValueError, "duplicate snapshot_id"):
            duplicate_payload = json.dumps([self.snapshot(), self.snapshot("snap-001", "2026-11-13T10:01:00Z")])
            deserialize_report_history(duplicate_payload)


if __name__ == "__main__":
    unittest.main()
