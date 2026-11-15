"""btc-cent-forecast-01 entry: volatility-gated mean-reversion to the 24h MA.

Forecast for the price 240 minutes after the checkpoint:

    dev  = log(last) - log(MA24)          # displacement from the 24h mean
    vol  = stdev(1-min log returns, last 24h) * sqrt(240)   # 4h volatility
    z    = |dev| / vol                     # displacement in vol units
    s    = 0            if z <= 1
         = (z - 1)     if 1 < z < 2        # ramp: partial reversion
         = 1            if z >= 2
    forecast = last * exp(-KAPPA * s * dev),   KAPPA = 0.40, adj capped at +/-1%

Why this: plain mean-reversion (k=0.25, ungated) won the 64-point
walk-forward (MAE 40,651 vs persistence 42,871 cents, -5.2%) but LOST on
the six practice checkpoints (49,153 vs 47,055 cents) -- in that window
the price was in a steady down-leg and small displacements from the MA
were just trend noise, so pulling back toward the mean hurt. The gate
fixes exactly that: only revert when the displacement is large relative
to recent volatility (|z| > 1), i.e. when the price is genuinely stretched
away from its mean, and revert fully only at |z| >= 2. On the practice
cases the gate stays OFF for p00/p01/p04/p05 (z = 0.17/0.50/0.73/0.71,
forecast = persistence) and fires only on p02 (z = 1.75) and p03
(z = 1.90), where it is right on p03 and wrong on p02 -- net dev win.

The parameters sit in the middle of a broad plateau, not on a spike:
across k in {0.30..0.50} x (zlo, zhi) in {(0.5,1.5),(0.75,1.5),(0.75,2),
(1,1.5),(1,2),(1.25,2.25)} every combination beats persistence on BOTH
walk-forward (WF60 39,525-40,724) and dev-5 (43,360-46,816). Chosen
k=0.40, zlo=1, zhi=2 is the round centre of that plateau.

Scores for the chosen variant (cents):
    walk-forward 64 pts, step 60min:  39,645 vs persist 42,871  (-7.5%)
    walk-forward 16 pts, step 240min: 36,775 vs persist 41,768  (-12.0%)
    split halves (step 60):  half1 36,772 vs 40,356; half2 42,900 vs 45,721
    last-24 WF points:           43,715 vs persist 47,242  (-7.5%)
    dev p00-p04:                 44,103 vs persist 47,055  (-6.3%)
      p00 $317 (=persist), p01 $767 (=persist), p02 $771 (vs $470),
      p03 $119 (vs $567), p04 $231 (=persist)
    dev p05: gate off, forecast = last close, error $318.56 either way
      (identical to persistence -- the only honest claim for p05).

Deterministic: pure function of the input prices, no randomness, no clock,
no dict-order dependence. Stdlib only, no network. Runs in ~0.05 s/case.
"""

import json
import math
import os
from pathlib import Path

INPUT_DIR = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")

MIN_PRICE = 0.00001
MAX_PRICE = 9_999_999.99999

# Mean-reversion strength toward the 24h moving average (log space),
# applied only when the volatility gate below is (partly) open.
KAPPA = 0.40
# Minutes of history averaged (24 hours) and used for the volatility estimate.
MA_MINUTES = 1440
# Gate thresholds on |dev| / (4h volatility): no reversion below Z_LO,
# full reversion above Z_HI, linear ramp between.
Z_LO = 1.0
Z_HI = 2.0
# Largest allowed |log| adjustment, as a fraction of price.
MAX_LOG_ADJ = 0.01


def price5(x):
    """Clamp to the scorer's (0, 10,000,000) range on the 5-decimal grid."""
    return round(min(MAX_PRICE, max(MIN_PRICE, x)) * 1e5) / 1e5


def forecast(prices):
    """Forecast the close 240 minutes after the last price in `prices`."""
    last = prices[-1]
    if len(prices) < 2:
        return price5(last)
    window = prices[-MA_MINUTES:]
    mean = math.fsum(window) / len(window)
    if not (mean > 0.0) or not math.isfinite(mean):
        return price5(last)
    dev = math.log(last) - math.log(mean)
    # 4h volatility from 1-minute log returns over the same window.
    logs = [math.log(x) for x in window]
    rets = [logs[i] - logs[i - 1] for i in range(1, len(logs))]
    if len(rets) < 2:
        return price5(last)
    m = math.fsum(rets) / len(rets)
    var = math.fsum((r - m) ** 2 for r in rets) / len(rets)
    vol4 = math.sqrt(var) * math.sqrt(240)
    if not (vol4 > 0.0) or not math.isfinite(vol4):
        return price5(last)
    z = abs(dev) / vol4
    if z <= Z_LO:
        scale = 0.0
    elif z >= Z_HI:
        scale = 1.0
    else:
        scale = (z - Z_LO) / (Z_HI - Z_LO)
    adj = -KAPPA * scale * dev
    if adj > MAX_LOG_ADJ:
        adj = MAX_LOG_ADJ
    elif adj < -MAX_LOG_ADJ:
        adj = -MAX_LOG_ADJ
    return price5(last * math.exp(adj))


def main():
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    in_dir = Path(INPUT_DIR)
    inputs = sorted(p for p in in_dir.iterdir() if p.name.endswith(".in"))
    for path in inputs:
        case_id = path.name[: -len(".in")]
        with open(path, "r", encoding="utf-8") as f:
            case = json.load(f)
        markets = case.get("markets")
        if not isinstance(markets, list) or len(markets) != 1:
            raise ValueError(f"{path.name} does not hold exactly one market")
        prices = markets[0].get("prices")
        if not isinstance(prices, list) or not prices:
            raise ValueError(f"{path.name} market has no prices")
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in prices):
            raise ValueError(f"{path.name} market has non-finite prices")
        guess = forecast(prices)
        payload = {"forecasts": [{"case": case_id, "price": guess}]}
        with open(out_dir / f"{case_id}.out", "w", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")


if __name__ == "__main__":
    main()
