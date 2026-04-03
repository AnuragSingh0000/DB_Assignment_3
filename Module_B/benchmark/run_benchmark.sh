#!/usr/bin/env bash
# run_benchmark.sh — Full before/after SQL index benchmark pipeline
# Usage: bash run_benchmark.sh [N_REQUESTS]   (default: 30)

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_B="$SCRIPT_DIR/.."
N=${1:-30}

MYSQL="mysql --connect-timeout=5 -u olympia_app -proot"

echo "========================================"
echo "  Olympia Track — Index Benchmark Run"
echo "  Requests per endpoint: $N"
echo "========================================"

# ── 1. Server check ──────────────────────────────────────────────────────────
echo ""
echo "[1/6] Checking server..."
if ! curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "  Server not running. Starting uvicorn in background..."
    cd "$MODULE_B"
    uvicorn app.main:app --port 8000 > /tmp/uvicorn_bench.log 2>&1 &
    UVICORN_PID=$!
    echo "  PID=$UVICORN_PID — waiting 3s for startup..."
    sleep 3
    if ! curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "  ERROR: Server failed to start. Check /tmp/uvicorn_bench.log"
        exit 1
    fi
    echo "  Server started."
    STARTED_SERVER=1
else
    echo "  Server already running."
    STARTED_SERVER=0
fi

# ── 2. Drop indexes (clean baseline) ─────────────────────────────────────────
echo ""
echo "[2/6] Dropping indexes for clean baseline..."
$MYSQL olympia_track -e "DROP INDEX IF EXISTS idx_perf_recdate ON PerformanceLog;" 2>/dev/null || true
$MYSQL olympia_track -e "DROP INDEX IF EXISTS idx_perf_memberid_recdate ON PerformanceLog;" 2>/dev/null || true
$MYSQL olympia_track -e "DROP INDEX IF EXISTS idx_event_sportid_eventdate ON Event;" 2>/dev/null || true
$MYSQL olympia_track -e "DROP INDEX IF EXISTS idx_event_tournamentid_eventdate ON Event;" 2>/dev/null || true
$MYSQL olympia_track -e "DROP INDEX IF EXISTS idx_eqissue_eqid_issuedate ON EquipmentIssue;" 2>/dev/null || true
echo "  Indexes dropped."

# ── 3. Benchmark BEFORE ───────────────────────────────────────────────────────
echo ""
echo "[3/6] Running BEFORE benchmark ($N req/endpoint)..."
cd "$SCRIPT_DIR"
python benchmark.py --mode before --n "$N"

# ── 4. Print slowest ──────────────────────────────────────────────────────────
echo ""
echo "[4/6] Top 5 slowest endpoints (before):"
python benchmark.py --slowest --top 5

# ── 5. Apply indexes ──────────────────────────────────────────────────────────
echo ""
echo "[5/6] Applying indexes..."
$MYSQL olympia_track < "$MODULE_B/sql/05_indexes.sql" 2>/dev/null || true
echo "  Indexes applied."

# ── 6. Benchmark AFTER ────────────────────────────────────────────────────────
echo ""
echo "[6/6] Running AFTER benchmark ($N req/endpoint, top 5 slowest only)..."
python benchmark.py --mode after --n "$N" --top 5

# ── Report ────────────────────────────────────────────────────────────────────
echo ""
echo "Generating report..."
python benchmark.py --report

echo ""
echo "========================================"
echo "  Done! Results in benchmark/results/"
echo "    before.json / after.json"
echo "    before_explain.txt / after_explain.txt"
echo "    report.md"
echo "========================================"

# ── Cleanup ───────────────────────────────────────────────────────────────────
if [ "$STARTED_SERVER" = "1" ]; then
    echo ""
    echo "Stopping server (PID=$UVICORN_PID)..."
    kill "$UVICORN_PID" 2>/dev/null || true
fi
