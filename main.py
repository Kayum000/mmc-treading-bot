"""Local signal runner.

This first version reads OHLC CSV files and emits BUY/SELL/NO_TRADE only.
It does not place orders or connect to a broker/exchange.
"""
import argparse

from data.market_data import load_csv
from strategy.signal import generate_signal


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tf15", required=True, help="15m OHLC CSV")
    parser.add_argument("--tf5", required=True, help="5m OHLC CSV")
    parser.add_argument("--tf1", required=True, help="1m OHLC CSV")
    args = parser.parse_args()

    frames = {
        "15m": load_csv(args.tf15),
        "5m": load_csv(args.tf5),
        "1m": load_csv(args.tf1),
    }
    signal = generate_signal(frames)
    print(f"Signal: {signal.action}")
    print(f"Buy score: {signal.buy_score}")
    print(f"Sell score: {signal.sell_score}")
    print(f"Reason: {signal.reason}")


if __name__ == "__main__":
    main()
