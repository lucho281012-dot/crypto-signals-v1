"""Pure dashboard model assembly for paper performance history.

This module prepares UI-ready data only. It has no renderer, file/network
access, persistence, exchange integration, or trading behavior.
"""
from decimal import Decimal

from paper_report_export import build_report_history_summary
from paper_report_visualization import build_report_chart_data


def _decimal(value, field):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return number


def _drawdown_data(equity_points):
    """Return peak-relative drawdown series and worst observed drawdowns."""
    peak = None
    drawdowns = []
    worst_amount = Decimal("0")
    worst_pct = None

    for point in equity_points:
        equity = _decimal(point["value"], "equity_usdt")
        peak = equity if peak is None or equity > peak else peak
        amount = equity - peak
        pct = (amount / peak * Decimal("100")) if peak > 0 else None
        if amount < worst_amount:
            worst_amount = amount
        if pct is not None and (worst_pct is None or pct < worst_pct):
            worst_pct = pct
        drawdowns.append({
            "snapshot_id": point["snapshot_id"],
            "captured_at": point["captured_at"],
            "drawdown_usdt": str(amount),
            "drawdown_pct": str(pct) if pct is not None else None,
        })

    return {
        "series": drawdowns,
        "max_drawdown_usdt": str(worst_amount),
        "max_drawdown_pct": str(worst_pct) if worst_pct is not None else None,
    }


def build_report_dashboard_model(history):
    """Combine validated summary, chart series and latest asset allocation.

    Asset equity weights are market value divided by latest total equity.
    They are None when equity is zero or negative. Drawdown is measured from
    the highest equity observed so far in the supplied chronological history.
    """
    summary = build_report_history_summary(history)
    charts = build_report_chart_data(history)

    if not history:
        return {
            "schema_version": 1,
            "snapshot_count": 0,
            "summary": summary,
            "latest_metrics": None,
            "equity_drawdown": {
                "series": [],
                "max_drawdown_usdt": None,
                "max_drawdown_pct": None,
            },
            "latest_assets": [],
            "charts": charts,
        }

    latest_report = history[-1]["report"]
    latest_equity = _decimal(latest_report["equity_usdt"], "latest.equity_usdt")
    latest_metrics = {
        "equity_usdt": str(latest_equity),
        "cash_usdt": str(_decimal(latest_report["cash_usdt"], "latest.cash_usdt")),
        "market_value_usdt": str(_decimal(
            latest_report["market_value_usdt"], "latest.market_value_usdt"
        )),
        "total_pnl_usdt": str(_decimal(
            latest_report["total_pnl_usdt"], "latest.total_pnl_usdt"
        )),
        "total_return_pct": str(_decimal(
            latest_report["total_return_pct"], "latest.total_return_pct"
        )),
    }

    latest_assets = []
    for asset, position in sorted(latest_report.get("positions", {}).items()):
        market_value = _decimal(
            position.get("market_value_usdt"),
            f"latest.positions[{asset}].market_value_usdt",
        )
        weight = (
            market_value / latest_equity * Decimal("100")
            if latest_equity > 0 else None
        )
        latest_assets.append({
            "asset": asset,
            "market_value_usdt": str(market_value),
            "equity_weight_pct": str(weight) if weight is not None else None,
        })

    drawdown = _drawdown_data(charts["series"]["equity_usdt"])
    return {
        "schema_version": 1,
        "snapshot_count": len(history),
        "summary": summary,
        "latest_metrics": latest_metrics,
        "equity_drawdown": drawdown,
        "latest_assets": latest_assets,
        "charts": charts,
    }
