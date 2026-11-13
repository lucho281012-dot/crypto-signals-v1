"""Append-only, in-memory history helpers for paper performance reports.

This module deliberately performs no file I/O, network access, or trading.
A separate storage layer may be considered only after these pure helpers pass
independent tests and receive explicit approval.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json


def _normalize_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("captured_at must be a non-empty ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError("captured_at must be a valid ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("captured_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_copy(value, field):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return json.loads(encoded)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{field} must contain only finite JSON-compatible values")


def build_report_snapshot(report, captured_at, snapshot_id):
    """Create a detached, JSON-safe snapshot without changing the report."""
    if not isinstance(report, dict) or not report:
        raise ValueError("report must be a non-empty dictionary")
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise ValueError("snapshot_id must be a non-empty string")
    return {
        "schema_version": 1,
        "snapshot_id": snapshot_id.strip(),
        "captured_at": _normalize_timestamp(captured_at),
        "report": _json_copy(report, "report"),
    }


def validate_report_history(history):
    """Validate schema, unique IDs and strictly increasing UTC timestamps."""
    if not isinstance(history, list):
        raise ValueError("history must be a list")
    seen_ids = set()
    previous_time = None
    for index, snapshot in enumerate(history):
        if not isinstance(snapshot, dict):
            raise ValueError(f"history[{index}] must be a dictionary")
        if snapshot.get("schema_version") != 1:
            raise ValueError(f"history[{index}] has unsupported schema_version")
        snapshot_id = snapshot.get("snapshot_id")
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise ValueError(f"history[{index}] has invalid snapshot_id")
        if snapshot_id in seen_ids:
            raise ValueError(f"duplicate snapshot_id: {snapshot_id}")
        seen_ids.add(snapshot_id)
        timestamp = _normalize_timestamp(snapshot.get("captured_at"))
        current_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if previous_time is not None and current_time <= previous_time:
            raise ValueError("history timestamps must be strictly increasing")
        previous_time = current_time
        report = snapshot.get("report")
        if not isinstance(report, dict) or not report:
            raise ValueError(f"history[{index}].report must be a non-empty dictionary")
        _json_copy(report, f"history[{index}].report")
    return True


def append_report_snapshot(history, snapshot):
    """Return a new history with snapshot appended; never mutate inputs."""
    validate_report_history(history)
    validate_report_history([snapshot])
    if history:
        last_time = datetime.fromisoformat(
            _normalize_timestamp(history[-1]["captured_at"]).replace("Z", "+00:00")
        )
        new_time = datetime.fromisoformat(
            _normalize_timestamp(snapshot["captured_at"]).replace("Z", "+00:00")
        )
        if new_time <= last_time:
            raise ValueError("new snapshot must be later than the latest history entry")
    if any(item["snapshot_id"] == snapshot["snapshot_id"] for item in history):
        raise ValueError(f"duplicate snapshot_id: {snapshot['snapshot_id']}")
    result = deepcopy(history)
    result.append(_json_copy(snapshot, "snapshot"))
    validate_report_history(result)
    return result


def serialize_report_history(history):
    """Serialize validated history as deterministic JSON."""
    validate_report_history(history)
    return json.dumps(history, sort_keys=True, separators=(",", ":"), allow_nan=False)


def deserialize_report_history(payload):
    """Parse and validate a JSON history payload."""
    if not isinstance(payload, str):
        raise ValueError("payload must be a JSON string")
    try:
        history = json.loads(payload)
    except (TypeError, ValueError):
        raise ValueError("payload must contain valid JSON")
    validate_report_history(history)
    return history
