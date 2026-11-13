"""Pure, read-only paper execution against a validated Kraken-style order book.

This module never connects to an exchange, persists state, or submits orders.
The caller must supply a locally reconstructed book whose exchange checksum
has already been verified for the latest snapshot/update.
"""
from decimal import Decimal, InvalidOperation


DEFAULT_FEE_RATE = Decimal("0.001")
DEFAULT_MAX_BOOK_AGE_MS = 2_000
DEFAULT_MAX_SERVER_EVENT_AGE_MS = 15_000
DEFAULT_MAX_FUTURE_SKEW_MS = 1_000
DEFAULT_MAX_SLIPPAGE_PCT = Decimal("0.005")
MAX_LEVELS = 10


def _decimal(value, field):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{field} must be numeric")
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return number


def _timestamp(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer millisecond timestamp")
    return value


def _levels(raw_levels, side):
    if not isinstance(raw_levels, (list, tuple)) or not raw_levels:
        raise ValueError(f"{side} book side is empty or invalid")
    if len(raw_levels) > MAX_LEVELS:
        raise ValueError(f"{side} contains more than {MAX_LEVELS} levels")

    parsed = []
    seen = set()
    for index, level in enumerate(raw_levels):
        if not isinstance(level, (list, tuple)) or len(level) != 2:
            raise ValueError(f"{side}[{index}] must be [price, quantity]")
        price = _decimal(level[0], f"{side}[{index}].price")
        quantity = _decimal(level[1], f"{side}[{index}].quantity")
        if price <= 0 or quantity <= 0:
            raise ValueError(f"{side}[{index}] price and quantity must be positive")
        if price in seen:
            raise ValueError(f"{side} contains duplicate price levels")
        seen.add(price)
        parsed.append((price, quantity))

    expected = sorted(parsed, key=lambda item: item[0], reverse=(side == "bids"))
    if parsed != expected:
        raise ValueError(f"{side} levels are not sorted best-to-worst")
    return parsed


def simulate_market_order(
    book,
    side,
    quantity,
    now_ms,
    fee_rate=DEFAULT_FEE_RATE,
    max_book_age_ms=DEFAULT_MAX_BOOK_AGE_MS,
    max_server_event_age_ms=DEFAULT_MAX_SERVER_EVENT_AGE_MS,
    max_slippage_pct=DEFAULT_MAX_SLIPPAGE_PCT,
):
    """Simulate a full-or-reject market order against the visible top-10 book.

    Quantity is in base-asset units. BUY consumes asks; SELL consumes bids.
    No partial fill is returned: insufficient visible depth rejects the order.
    received_at_ms is local receipt time; timestamp_ms is exchange event time.
    """
    try:
        if not isinstance(book, dict):
            raise ValueError("book must be a dictionary")
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        now_ms = _timestamp(now_ms, "now_ms")
        received_at_ms = _timestamp(book.get("received_at_ms"), "received_at_ms")
        timestamp_ms = _timestamp(book.get("timestamp_ms"), "timestamp_ms")

        if book.get("checksum_valid") is not True:
            raise ValueError("book checksum has not been verified")
        if not isinstance(book.get("symbol"), str) or not book["symbol"]:
            raise ValueError("book symbol is missing")

        local_age = now_ms - received_at_ms
        server_age = now_ms - timestamp_ms
        if local_age < -DEFAULT_MAX_FUTURE_SKEW_MS or local_age > max_book_age_ms:
            raise ValueError("locally received book event is stale or from the future")
        if server_age < -DEFAULT_MAX_FUTURE_SKEW_MS or server_age > max_server_event_age_ms:
            raise ValueError("exchange book event timestamp is stale or from the future")

        bids = _levels(book.get("bids"), "bids")
        asks = _levels(book.get("asks"), "asks")
        best_bid = bids[0][0]
        best_ask = asks[0][0]
        if best_bid >= best_ask:
            raise ValueError("book is crossed or locked")

        requested = _decimal(quantity, "quantity")
        fee = _decimal(fee_rate, "fee_rate")
        slippage_limit = _decimal(max_slippage_pct, "max_slippage_pct")
        if requested <= 0:
            raise ValueError("quantity must be positive")
        if fee < 0 or fee >= 1:
            raise ValueError("fee_rate must be between 0 and 1")
        if slippage_limit < 0:
            raise ValueError("max_slippage_pct cannot be negative")

        levels = asks if side == "BUY" else bids
        best_price = levels[0][0]
        remaining = requested
        filled = Decimal("0")
        notional = Decimal("0")
        fills = []

        for price, available in levels:
            if remaining <= 0:
                break
            take = min(remaining, available)
            if take > 0:
                level_notional = take * price
                fills.append({
                    "price": float(price),
                    "quantity": float(take),
                    "notional": float(level_notional),
                })
                filled += take
                notional += level_notional
                remaining -= take

        if remaining > 0:
            raise ValueError("insufficient visible order-book depth for a full fill")

        average_price = notional / filled
        if side == "BUY":
            slippage = (average_price - best_price) / best_price
        else:
            slippage = (best_price - average_price) / best_price
        if slippage > slippage_limit:
            raise ValueError("simulated slippage exceeds configured limit")

        fee_amount = notional * fee
        return {
            "ok": True,
            "symbol": book["symbol"],
            "side": side,
            "requested_quantity": float(requested),
            "filled_quantity": float(filled),
            "average_fill_price": float(average_price),
            "best_executable_price": float(best_price),
            "gross_notional_usdt": float(notional),
            "fee_rate": float(fee),
            "fee_usdt": float(fee_amount),
            "slippage_pct": float(slippage * Decimal("100")),
            "levels_consumed": len(fills),
            "fills": fills,
            "cash_flow_usdt": float(-(notional + fee_amount) if side == "BUY" else notional - fee_amount),
            "book_timestamp_ms": timestamp_ms,
            "book_received_at_ms": received_at_ms,
            "book_age_ms": local_age,
            "checksum_valid": True,
        }
    except (ValueError, TypeError, InvalidOperation, OverflowError) as exc:
        return {"ok": False, "reason": str(exc)}
