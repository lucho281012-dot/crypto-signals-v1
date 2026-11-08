
import json
from collections import defaultdict

from historical_data import download_historical_candles
from backtest import simulate



def summarize(trades):
    if not trades:
        return {
            "trades": 0,
            "message": "No trades"
        }

    returns = [t["net_return_pct"] for t in trades]

    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x < 0]

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(
            len(wins) / len(trades) * 100, 2
        ),
        "average_win_pct": round(
            sum(wins) / len(wins), 4
        ) if wins else 0,
        "average_loss_pct": round(
            sum(losses) / len(losses), 4
        ) if losses else 0,
        "average_net_return_pct": round(
            sum(returns) / len(returns), 4
        ),
        "total_net_return_pct": round(
            sum(returns), 4
        )
    }

        "Exit analysis is diagnostic. UNKNOWN means "
        "the trade did not contain a recognized exit reason."
    )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
