#!/usr/bin/env bash
# Download FREE historical data from Dukascopy into Backend/data as CSV,
# then it's ready for POST /strategy/backtest_csv.
#
# Dukascopy offers free tick + OHLC history (majors, metals, indices, crypto)
# back to ~2003. This wrapper uses the `dukascopy-node` CLI (no account needed).
# Requires Node.js; the CLI is fetched on demand via npx.
#
# Usage:
#   tools/fetch_dukascopy.sh <instrument> <timeframe> <from> [to]
#
# Examples:
#   tools/fetch_dukascopy.sh xauusd d1 2023-01-01                 # daily gold
#   tools/fetch_dukascopy.sh eurusd h1 2024-01-01 2024-12-31      # hourly EUR/USD
#   tools/fetch_dukascopy.sh btcusd m15 2025-01-01                # 15-min BTC (intraday)
#
# Instruments: xauusd xagusd eurusd gbpusd usdjpy audusd btcusd ethusd ... (Dukascopy symbol)
# Timeframes:  tick m1 m5 m15 m30 h1 h4 d1 mn1
set -euo pipefail

INSTRUMENT="${1:-xauusd}"
TIMEFRAME="${2:-d1}"
FROM="${3:-2023-01-01}"
TO="${4:-$(date +%F)}"
OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/Backend/data"

mkdir -p "$OUT_DIR"
echo "Fetching Dukascopy $INSTRUMENT $TIMEFRAME  $FROM → $TO  into $OUT_DIR"

npx --yes dukascopy-node \
  -i "$INSTRUMENT" \
  -from "$FROM" \
  -to "$TO" \
  -t "$TIMEFRAME" \
  -f csv \
  -dir "$OUT_DIR" \
  -bv true \
  --date-format "YYYY-MM-DDTHH:mm:ss.SSS[Z]"

echo
echo "Done. Backtest it with:"
echo "  curl --data-binary @\"$OUT_DIR/$INSTRUMENT-$TIMEFRAME-bid-$FROM-$TO.csv\" \\"
echo "    'http://127.0.0.1:8000/strategy/backtest_csv?horizon=long-term'"
