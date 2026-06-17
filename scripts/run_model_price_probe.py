"""Run the model price probe with outputs grouped under results/model_prices/."""

from pathlib import Path

import model_price_probe as probe

probe.OUTPUT_DIR = Path(__file__).parent.parent / "results" / "model_prices"
probe.OUTPUT_CSV = probe.OUTPUT_DIR / "model_prices.csv"
probe.SUMMARY_CSV = probe.OUTPUT_DIR / "model_prices_summary.csv"

if __name__ == "__main__":
    probe.main()
