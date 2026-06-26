#!/usr/bin/env bash
# dev_memwatch.sh — memory flight-recorder for the local dev stack.
#
# Run this in a SEPARATE terminal *alongside* `bash scripts/dev.sh`. It samples
# per-process RSS + system memory/swap every MEMWATCH_INTERVAL seconds and
# appends each sample to a CSV on disk, calling sync() after every write so the
# trace SURVIVES a hard crash or reboot (terminal scrollback does not). When
# free memory runs low it writes a full forensic `ps`/`vm_stat` snapshot, and —
# unless you disable it — stops the dev stack a hair before the OS would hard-
# crash, preserving both the trace and your Mac.
#
# After a crash, read:  logs/memwatch/mem-<stamp>.csv   (the growth curve — find
# the process whose column climbs without bound = the leak) and
# logs/memwatch/snapshot-<stamp>.txt (the heavy-process dump near the edge).
# Complement with macOS's own black box (the OS logs which process IT killed):
#   ls -lt /Library/Logs/DiagnosticReports/*.ips | head
#   log show --last 30m --predicate 'eventMessage CONTAINS[c] "memorystatus" OR eventMessage CONTAINS[c] "jetsam"'
#   sysctl vm.swapusage
#
# Env knobs:
#   MEMWATCH_INTERVAL  sample seconds            (default 2)
#   MEMWATCH_OUT       output dir                (default logs/memwatch)
#   MEMWATCH_FLOOR_MB  protective stop when system available < this MB
#                      (default 1500; set 0 to DISABLE the stop and capture a
#                      full hard crash — not recommended, you may lose the Mac)
set -uo pipefail
cd "$(dirname "$0")/.."

INTERVAL="${MEMWATCH_INTERVAL:-2}"
OUTDIR="${MEMWATCH_OUT:-logs/memwatch}"
FLOOR_MB="${MEMWATCH_FLOOR_MB:-1500}"
PAGE="$(sysctl -n hw.pagesize)"
mkdir -p "$OUTDIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
CSV="$OUTDIR/mem-$STAMP.csv"
SNAP="$OUTDIR/snapshot-$STAMP.txt"

echo "[memwatch] recording to $CSV"
echo "[memwatch] interval=${INTERVAL}s  protective-stop floor=${FLOOR_MB}MB (0=disabled)"
echo "[memwatch] snapshots -> $SNAP ; macOS jetsam log -> /Library/Logs/DiagnosticReports/*.ips"

# Append a line and flush filesystem buffers so a hard crash can't lose it.
emit() { printf '%s\n' "$*" >> "$CSV"; sync; }

sys_avail_mb() {
  vm_stat | awk -v p="$PAGE" '
    /Pages free/{f=$3}/Pages inactive/{i=$3}/Pages speculative/{s=$3}/Pages purgeable/{u=$3}
    END{gsub(/\./,"",f);gsub(/\./,"",i);gsub(/\./,"",s);gsub(/\./,"",u);
        printf "%d",(f+i+s+u)*p/1048576}'
}
swap_used_mb() { sysctl -n vm.swapusage | awk '{for(n=1;n<=NF;n++) if($n=="used"){gsub(/[A-Za-z]/,"",$(n+2)); printf "%d",$(n+2); exit}}'; }

# Label an argon process. Schedulers are indistinguishable in argv, so read the
# worker role/index out of the process environment via `ps eww`.
label_for() {
  local pid="$1" cmd="$2"
  case "$cmd" in
    *massive_ws_consumer*) echo "ws"; return;;
    *uvicorn*)             echo "api"; return;;
    *"next dev"*|*next-server*) echo "next"; return;;
  esac
  if [[ "$cmd" == *uw_scan.worker.scheduler* ]]; then
    local env role idx
    env="$(ps eww -o command= -p "$pid" 2>/dev/null)"
    role="$(printf '%s' "$env" | grep -oE 'UW_SCAN_WORKER_ROLE=[^ ]+' | head -1 | cut -d= -f2)"
    idx="$(printf '%s' "$env" | grep -oE 'UW_SCAN_WORKER_INDEX=[0-9]+' | head -1 | cut -d= -f2)"
    echo "sched-${role:-?}-${idx:-?}"; return
  fi
  echo "other"
}

snapshot() {
  { echo "=== $(date '+%F %T')  reason=$1  sys_avail=${2}MB  swap_used=${3}MB ==="
    echo "-- top 25 by RSS --"
    ps -axo pid,rss,%cpu,command | sort -rn -k2 | head -25 \
      | awk '{printf "%8.0fMB cpu=%5s pid=%-7s %s\n",$2/1024,$3,$1,substr($0,index($0,$4))}' | cut -c1-160
    echo "-- vm_stat --"; vm_stat
    echo "-- swap --"; sysctl -n vm.swapusage; echo
  } >> "$SNAP"; sync
}

emit "ts,uptime_s,sys_avail_mb,swap_used_mb,argon_total_mb,breakdown"
trap 'echo "[memwatch] stopped; trace in $CSV"; exit 0' INT TERM
start="$(date +%s)"; warned=0
while :; do
  now="$(date +%s)"; el=$((now-start))
  avail="$(sys_avail_mb)"; swap="$(swap_used_mb)"
  total=0; breakdown=""
  while read -r pid rss rest; do
    [ -z "${pid:-}" ] && continue
    lbl="$(label_for "$pid" "$rest")"
    mb=$((rss/1024)); total=$((total+mb))
    breakdown="$breakdown ${lbl}=${mb}"
  done < <(ps -axo pid,rss,command | grep -E 'uw_scan|uvicorn|next dev|next-server|massive_ws' | grep -v grep)
  emit "$(date '+%FT%T'),$el,$avail,$swap,$total,${breakdown# }"

  # Detailed forensic snapshot once we're within ~1GB of the stop floor.
  if [ "$avail" -lt $((FLOOR_MB + 1000)) ]; then
    [ "$warned" -eq 0 ] && { echo "[memwatch] WARNING low memory: ${avail}MB avail, swap ${swap}MB"; warned=1; }
    snapshot "low-mem" "$avail" "$swap"
  fi

  # Protective stop: capture a final snapshot, then take the dev stack down
  # before the OS hard-crashes. Disable with MEMWATCH_FLOOR_MB=0.
  if [ "$FLOOR_MB" -gt 0 ] && [ "$avail" -lt "$FLOOR_MB" ]; then
    echo "[memwatch] !!! avail ${avail}MB < floor ${FLOOR_MB}MB — final snapshot + stopping dev stack"
    snapshot "STOP-floor-breach" "$avail" "$swap"
    pkill -f "uw_scan.worker" 2>/dev/null
    pkill -f "uvicorn uw_scan" 2>/dev/null
    pkill -f "next dev" 2>/dev/null
    pkill -f "concurrently" 2>/dev/null
    emit "STOPPED at ${el}s avail=${avail}MB"
    echo "[memwatch] stack stopped. Leak culprit = whichever column in $CSV climbed without bound."
    break
  fi
  sleep "$INTERVAL"
done
