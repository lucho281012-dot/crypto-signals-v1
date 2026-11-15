"""Build an in-memory dashboard preview from the read-only Paper report.

No files are read or written here. The caller supplies the report, timestamp,
snapshot identifier, and optional prior in-memory history.
"""
from copy import deepcopy

from paper_report_dashboard import build_report_dashboard_model
from paper_report_history import append_report_snapshot, build_report_snapshot, validate_report_history


def build_dashboard_preview(report, captured_at, snapshot_id, history=None):
    if history is None:
        history = []
    validate_report_history(history)
    snapshot = build_report_snapshot(report, captured_at, snapshot_id)
    updated_history = append_report_snapshot(history, snapshot)
    dashboard = build_report_dashboard_model(updated_history)
    return {
        "snapshot": snapshot,
        "dashboard": dashboard,
        "history": deepcopy(updated_history),
    }
