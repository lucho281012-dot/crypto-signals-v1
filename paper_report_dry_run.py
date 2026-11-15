"""Read-only report preview for the active legacy Paper simulator.

This entry point reads the existing state file and fetches only public ticker
prices needed to value currently open positions. It never saves state or
report history and never opens or closes a paper position.
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


def _read_state_without_side_effects():
    """Read the simulator state without invoking load_state's mkdir behavior."""
    from paper_trading import INITIAL_BALANCE, STATE_FILE

    if STATE_FILE.exists():
        with STATE_FILE.open("r", encoding="utf-8") as file:
            state = json.load(file)
        if not isinstance(state, dict):
            raise ValueError("paper state must be a JSON object")
        state.setdefault("positions", {})
        state.setdefault("history", [])
        return state

    return {
        "initial_balance": INITIAL_BALANCE,
        "cash_usdt": INITIAL_BALANCE,
        "positions": {},
        "history": [],
    }


def run_read_only_report(state=None, market_data=None):
    """Read current inputs and perform no writes or unnecessary network calls."""
    if state is None:
        state = _read_state_without_side_effects()

    if not isinstance(state, dict):
        raise ValueError("state must be a dictionary")
    positions = state.get("positions")
    if not isinstance(positions, dict):
        raise ValueError("state.positions must be a dictionary")

    if market_data is None:
        market_data = {}
        if positions:
            from market_data import get_market_price
            for symbol in sorted(positions):
                price = get_market_price(symbol)
                market_data[symbol] = {"price": price}

    return build_read_only_report(state, market_data)


def main():
    report = run_read_only_report()
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
