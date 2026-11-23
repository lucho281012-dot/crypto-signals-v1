"""Read-only report preview for the active legacy Paper simulator.

This entry point reads the current simulator state and public market marks,
then prints a dashboard-compatible report. It never saves state or report
history and never opens or closes a paper position.
"""
import json


def build_read_only_report(state, market_data):
    """Build a report from supplied state and market data without mutation."""
    if not isinstance(market_data, dict):
        raise ValueError("market_data must be a dictionary")

    positions = state.get("positions")
    if not isinstance(positions, dict):
        raise ValueError("state.positions must be a dictionary")

    marks = {}
    for symbol in positions:
        market = market_data.get(symbol)
        if not isinstance(market, dict) or market.get("price") is None:
            raise ValueError(f"missing public market price for open position {symbol}")
        marks[symbol] = market["price"]

    from paper_legacy_report_adapter import build_legacy_paper_report
    return build_legacy_paper_report(state, marks)


def run_read_only_report(state=None, market_data=None):
    """Load current inputs when omitted; perform no writes."""
    if state is None:
        from paper_trading import load_state
        state = load_state()
    if market_data is None:
        from market_data import get_all_market_data
        market_data = get_all_market_data()
    return build_read_only_report(state, market_data)


def main():
    report = run_read_only_report()
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
