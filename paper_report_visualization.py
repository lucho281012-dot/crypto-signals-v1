"""Pure chart-data preparation for paper performance history.

This module does not render charts, access files/networks, or perform trading.
It converts validated snapshots into deterministic time-series data for a UI.
"""
from decimal import Decimal, InvalidOperation

from paper_report_history import validate_report_history


_METRICS = (
    "equity_usdt",
    "total_pnl_usdt",
    "total_return_pct",
    "cash_usdt",
    "market_value_usdt",
)


def _finite_decimal(value, field):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be numeric")
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return number


def build_report_chart_data(history):
    """Build chronological metric and per-asset market-value series.

    All five portfolio metrics are required in every snapshot so chart lines
    cannot silently compare incomplete or inconsistent data. An absent asset
    position in a snapshot is represented as zero market value.
    """
    validate_report_history(history)
    if not history:
        return {
            "schema_version": 1,
            "snapshot_count": 0,
            "timestamps": [],
            "series": {metric: [] for metric in _METRICS},
            "asset_market_value_usdt": {},
        }

    series = {metric: [] for metric in _METRICS}
    asset_values = {}
    timestamps = []

    for index, snapshot in enumerate(history):
        captured_at = snapshot["captured_at"]
        report = snapshot["report"]
        timestamps.append(captured_at)

        for metric in _METRICS:
            value = _finite_decimal(report.get(metric), f"history[{index}].{metric}")
            series[metric].append({
                "snapshot_id": snapshot["snapshot_id"],
                "captured_at": captured_at,
                "value": str(value),
            })

        positions = report.get("positions", {})
        if not isinstance(positions, dict):
            raise ValueError(f"history[{index}].positions must be a dictionary")
        normalized_positions = {}
        for asset, position in positions.items():
            if not isinstance(asset, str) or not asset.strip():
                raise ValueError(f"history[{index}] has an invalid asset name")
            if not isinstance(position, dict):
                raise ValueError(f"history[{index}].positions[{asset}] must be a dictionary")
            normalized_positions[asset] = _finite_decimal(
                position.get("market_value_usdt"),
                f"history[{index}].positions[{asset}].market_value_usdt",
            )

        for asset in set(asset_values) | set(normalized_positions):
            asset_values.setdefault(asset, [])
            asset_values[asset].append({
                "snapshot_id": snapshot["snapshot_id"],
                "captured_at": captured_at,
                "value": str(normalized_positions.get(asset, Decimal("0"))),
            })

    return {
        "schema_version": 1,
        "snapshot_count": len(history),
        "timestamps": timestamps,
        "series": series,
        "asset_market_value_usdt": {
            asset: asset_values[asset] for asset in sorted(asset_values)
        },
    }
