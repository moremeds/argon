#!/usr/bin/env bash
set -u

YTD_PIDFILE=/tmp/uw_historical_alpha_full_backfill.pid
ROOT=/tmp/uw-long-weekend-history
WATCH_LOG=/tmp/uw_long_weekend_chain_watcher.log
CAP=118000

mkdir -p "$ROOT"

log() {
  {
    date -u
    echo "$*"
  } >> "$WATCH_LOG"
}

uw_count() {
  cd ~/projects/argon || return 1
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  curl -sS -D /tmp/uw_chain_headers.txt -o /tmp/uw_chain_probe.json \
    -H "Authorization: Bearer ${UW_SCAN_API_KEY}" \
    "https://api.unusualwhales.com/api/stock/AAPL/volatility/variance-risk-premium" >/dev/null || return 1
  awk 'BEGIN{IGNORECASE=1} /^x-uw-daily-req-count:/ {gsub("\r", "", $2); print $2}' /tmp/uw_chain_headers.txt
}

run_phase() {
  local name="$1"
  local datasets="$2"
  local start="$3"
  local end="$4"
  local before after report stopped rc

  before="$(uw_count || echo unknown)"
  log "phase=${name} before_daily_count=${before} datasets=${datasets} range=${start}..${end}"
  if [[ "$before" =~ ^[0-9]+$ ]] && (( before >= CAP )); then
    log "phase=${name} skipped daily_count=${before} cap=${CAP}"
    return 2
  fi

  cd ~/projects/argon || return 1
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  PYTHONPATH=src .venv/bin/python /tmp/uw_long_weekend_history_backfill.py execute \
    --datasets "$datasets" \
    --start "$start" --end "$end" \
    --max-uw-calls "$CAP" --confirm \
    --output-dir "$ROOT/$name" \
    > "/tmp/uw_long_weekend_${name}.log" 2>&1
  rc=$?

  after="$(uw_count || echo unknown)"
  report="$ROOT/$name/execute-report.json"
  stopped="missing-report"
  if [[ -f "$report" ]]; then
    stopped="$(python3 - "$report" <<'PY' 2>/dev/null || true
import json
import sys
data = json.load(open(sys.argv[1]))
print(data.get("stopped_reason") or "")
PY
)"
  fi
  log "phase=${name} rc=${rc} after_daily_count=${after} stopped_reason=${stopped} report=${report}"

  if (( rc != 0 )); then
    return "$rc"
  fi
  if [[ "$after" =~ ^[0-9]+$ ]] && (( after >= CAP )); then
    return 2
  fi
  if [[ -n "$stopped" && "$stopped" != "None" ]]; then
    return 2
  fi
  return 0
}

log "watching ytd pidfile=$YTD_PIDFILE"
while true; do
  ytd_pid="$(cat "$YTD_PIDFILE" 2>/dev/null || true)"
  if [[ -z "$ytd_pid" ]] || ! kill -0 "$ytd_pid" 2>/dev/null; then
    break
  fi
  sleep 60
done

log "ytd exited; starting chained phases"
run_phase phase-a "market_tide,top_net_impact,gex_levels" "2023-08-03" "2025-12-31" || exit $?
run_phase phase-b "oi_change,oi_by_strike" "2025-01-02" "2026-05-10" || exit $?
run_phase phase-c "flow_bars" "2023-08-03" "2025-12-31" || exit $?
run_phase phase-d "dark_lit" "2023-08-03" "2025-12-31" || exit $?
log "all chained phases completed within daily cap"
