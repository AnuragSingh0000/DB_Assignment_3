#!/usr/bin/env python3

"""
benchmark.py — Measure API endpoint latency before/after SQL indexes.

Usage:
  python benchmark.py --mode before     # baseline: hit all endpoints, save results
  python benchmark.py --slowest         # print top-N slowest from before.json
  python benchmark.py --mode after      # re-bench the slowest N endpoints only
  python benchmark.py --report          # compare before/after, generate report.md
Options:
  --top N     Number of slowest endpoints to focus on (default: 5)
  --n N       Requests per endpoint (default: 100)
"""

import argparse
import json
import statistics
import time
from pathlib import Path
import mysql.connector
import requests

BASE_URL    = "http://localhost:8000"

RESULTS_DIR = Path(__file__).parent / "results"

RESULTS_DIR.mkdir(exist_ok=True)

DB_CONFIG = dict(host="127.0.0.1", user="olympia_app", password="olympia_pass")

CREDENTIALS = {
    "admin":  {"username": "vikram_admin",  "password": "admin123"},
    "coach":  {"username": "raj_coach",     "password": "coach123"},
    "player": {"username": "aarav_player",  "password": "player123"},
}

N_REQUESTS = 100


def get_sample_ids() -> dict:
    """Query the DB for one valid ID per table used in benchmarks."""
    conn = mysql.connector.connect(**DB_CONFIG, database="olympia_track")
    cur  = conn.cursor(dictionary=True)
    ids  = {}
    for table, col in [
        ("Member",     "MemberID"),
        ("Team",       "TeamID"),
        ("Event",      "EventID"),
        ("Tournament", "TournamentID"),
        ("Equipment",  "EquipmentID"),
    ]:
        cur.execute(f"SELECT {col} FROM `{table}` ORDER BY {col} LIMIT 1")
        row = cur.fetchone()
        ids[table] = row[col] if row else 1
    cur.execute("SELECT MemberID FROM Member WHERE Role='Coach' LIMIT 1")
    row = cur.fetchone()
    ids["CoachMemberID"] = row["MemberID"] if row else 2
    cur.execute("SELECT MemberID FROM Member WHERE Role='Player' LIMIT 1")
    row = cur.fetchone()
    ids["PlayerMemberID"] = row["MemberID"] if row else 9
    cur.close()
    conn.close()
    return ids


def run_explain(db_name: str, sql: str, params: tuple = ()) -> list:
    conn = mysql.connector.connect(**DB_CONFIG, database=db_name)
    cur  = conn.cursor(dictionary=True)
    cur.execute(f"EXPLAIN {sql}", params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def fmt_explain(rows: list) -> str:
    if not rows:
        return "  (no rows)"
    lines = []
    for r in rows:
        lines.append(
            f"  table={r.get('table')} | type={r.get('type')} | "
            f"possible_keys={r.get('possible_keys')} | key={r.get('key')} | "
            f"rows={r.get('rows')} | Extra={r.get('Extra')}"
        )
    return "\n".join(lines)


def login(role: str) -> requests.Session:
    s    = requests.Session()
    resp = s.post(f"{BASE_URL}/auth/login", json=CREDENTIALS[role])
    resp.raise_for_status()
    return s


def bench(session: requests.Session, method: str, url: str, n: int = N_REQUESTS) -> dict:
    latencies = []
    errors    = 0
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            resp = session.request(method, url)
            if resp.status_code >= 500:
                errors += 1
        except Exception:
            errors += 1
        latencies.append((time.perf_counter() - t0) * 1000)
    latencies.sort()
    return {
        "min":    round(latencies[0], 2),
        "mean":   round(statistics.mean(latencies), 2),
        "p95":    round(latencies[int(0.95 * n)], 2),
        "max":    round(latencies[-1], 2),
        "errors": errors,
    }


def measure_sql(db_name: str, sql: str, params: tuple, n: int = N_REQUESTS) -> dict:
    """Measure raw SQL execution time."""
    conn = mysql.connector.connect(**DB_CONFIG, database=db_name)
    cur = conn.cursor()
    times = []
    
    # Warmup
    try:
        cur.execute(sql, params)
        cur.fetchall()
    except Exception:
        pass

    for _ in range(n):
        t0 = time.perf_counter()
        try:
            cur.execute(sql, params)
            cur.fetchall()
            times.append((time.perf_counter() - t0) * 1000)
        except Exception:
            pass
    
    cur.close()
    conn.close()

    if not times:
        return {"mean": 0, "p95": 0, "min": 0, "max": 0}

    times.sort()
    return {
        "min":    round(times[0], 3),
        "mean":   round(statistics.mean(times), 3),
        "p95":    round(times[int(0.95 * len(times))], 3),
        "max":    round(times[-1], 3),
    }


def build_endpoints(ids: dict) -> list:
    """Returns list of (label, role, method, path)."""
    mid  = ids["Member"]
    tid  = ids["Team"]
    eid  = ids["Event"]
    tnid = ids["Tournament"]
    pmid = ids["PlayerMemberID"]
    return [
        ("GET /api/members [admin]",                  "admin",  "GET", "/api/members"),
        ("GET /api/members [coach]",                  "coach",  "GET", "/api/members"),
        ("GET /api/members/me [player]",              "player", "GET", "/api/members/me"),
        (f"GET /api/members/{pmid} [admin]",          "admin",  "GET", f"/api/members/{pmid}"),
        (f"GET /api/members/{pmid} [coach]",          "coach",  "GET", f"/api/members/{pmid}"),
        ("GET /api/teams [admin]",                    "admin",  "GET", "/api/teams"),
        (f"GET /api/teams/{tid} [admin]",             "admin",  "GET", f"/api/teams/{tid}"),
        ("GET /api/tournaments [admin]",              "admin",  "GET", "/api/tournaments"),
        ("GET /api/events [admin]",                   "admin",  "GET", "/api/events"),
        (f"GET /api/events?tournament_id={tnid}",     "admin",  "GET", f"/api/events?tournament_id={tnid}"),
        ("GET /api/events?sport_id=1",                "admin",  "GET", "/api/events?sport_id=1"),
        (f"GET /api/events/{eid} [admin]",            "admin",  "GET", f"/api/events/{eid}"),
        ("GET /api/equipment [admin]",                "admin",  "GET", "/api/equipment"),
        ("GET /api/equipment/issues [admin]",         "admin",  "GET", "/api/equipment/issues"),
        ("GET /api/equipment/issues [player]",        "player", "GET", "/api/equipment/issues"),
        ("GET /api/performance-logs [admin]",         "admin",  "GET", "/api/performance-logs"),
        ("GET /api/performance-logs [coach]",         "coach",  "GET", "/api/performance-logs"),
        ("GET /api/performance-logs [player]",        "player", "GET", "/api/performance-logs"),
        (f"GET /api/medical-records/{pmid} [admin]",  "admin",  "GET", f"/api/medical-records/{pmid}"),
        ("GET /admin/audit-log",                      "admin",  "GET", "/admin/audit-log"),
        ("GET /admin/verify-audit",                   "admin",  "GET", "/admin/verify-audit"),
    ]


def build_explain_queries(ids: dict) -> dict:
    """Returns {label: (db_name, sql, params)} for EXPLAIN analysis."""
    tnid = ids["Tournament"]
    cmid = ids["CoachMemberID"]
    pmid = ids["PlayerMemberID"]
    return {
        "GET /api/members [admin]": (
            "olympia_track",
            "SELECT * FROM Member ORDER BY MemberID",
            (),
        ),
        f"GET /api/members/{pmid} [admin]": (
            "olympia_track",
            "SELECT t.TeamID, t.TeamName, tm.Position, tm.IsCaptain, s.SportName "
            "FROM TeamMember tm "
            "JOIN Team t  ON tm.TeamID  = t.TeamID "
            "JOIN Sport s ON t.SportID  = s.SportID "
            "WHERE tm.MemberID = %s",
            (pmid,),
        ),
        "GET /api/teams [admin]": (
            "olympia_track",
            "SELECT t.*, s.SportName, m.Name AS CoachName "
            "FROM Team t "
            "JOIN Sport s ON t.SportID = s.SportID "
            "LEFT JOIN Member m ON t.CoachID = m.MemberID "
            "ORDER BY t.TeamID",
            (),
        ),
        "GET /api/events [admin]": (
            "olympia_track",
            "SELECT e.*, s.SportName, v.VenueName, t.TournamentName "
            "FROM Event e "
            "JOIN Sport s ON e.SportID = s.SportID "
            "JOIN Venue v ON e.VenueID = v.VenueID "
            "LEFT JOIN Tournament t ON e.TournamentID = t.TournamentID "
            "ORDER BY e.EventDate DESC",
            (),
        ),
        f"GET /api/events?tournament_id={tnid}": (
            "olympia_track",
            "SELECT e.*, s.SportName, v.VenueName, t.TournamentName "
            "FROM Event e "
            "JOIN Sport s ON e.SportID = s.SportID "
            "JOIN Venue v ON e.VenueID = v.VenueID "
            "LEFT JOIN Tournament t ON e.TournamentID = t.TournamentID "
            "WHERE e.TournamentID = %s ORDER BY e.EventDate DESC",
            (tnid,),
        ),
        "GET /api/events?sport_id=1": (
            "olympia_track",
            "SELECT e.*, s.SportName, v.VenueName, t.TournamentName "
            "FROM Event e "
            "JOIN Sport s ON e.SportID = s.SportID "
            "JOIN Venue v ON e.VenueID = v.VenueID "
            "LEFT JOIN Tournament t ON e.TournamentID = t.TournamentID "
            "WHERE e.SportID = 1 ORDER BY e.EventDate DESC",
            (),
        ),
        "GET /api/equipment/issues [admin]": (
            "olympia_track",
            "SELECT ei.*, e.EquipmentName, m.Name AS MemberName "
            "FROM EquipmentIssue ei "
            "JOIN Equipment e ON ei.EquipmentID = e.EquipmentID "
            "JOIN Member m    ON ei.MemberID    = m.MemberID "
            "ORDER BY ei.IssueDate DESC",
            (),
        ),
        "GET /api/equipment/issues [player]": (
            "olympia_track",
            "SELECT ei.*, e.EquipmentName, m.Name AS MemberName "
            "FROM EquipmentIssue ei "
            "JOIN Equipment e ON ei.EquipmentID = e.EquipmentID "
            "JOIN Member m    ON ei.MemberID    = m.MemberID "
            "WHERE ei.MemberID = %s ORDER BY ei.IssueDate DESC",
            (pmid,),
        ),
        "GET /api/performance-logs [admin]": (
            "olympia_track",
            "SELECT pl.*, m.Name AS MemberName, s.SportName "
            "FROM PerformanceLog pl "
            "JOIN Member m ON pl.MemberID = m.MemberID "
            "JOIN Sport  s ON pl.SportID  = s.SportID "
            "ORDER BY pl.RecordDate DESC",
            (),
        ),
        "GET /api/performance-logs [coach]": (
            "olympia_track",
            "SELECT pl.*, m.Name AS MemberName, s.SportName "
            "FROM PerformanceLog pl "
            "JOIN Member m ON pl.MemberID = m.MemberID "
            "JOIN Sport  s ON pl.SportID  = s.SportID "
            "WHERE pl.MemberID IN ("
            "  SELECT tm.MemberID FROM TeamMember tm "
            "  JOIN Team t ON tm.TeamID = t.TeamID "
            "  WHERE t.CoachID = %s"
            ") ORDER BY pl.RecordDate DESC",
            (cmid,),
        ),
        "GET /api/performance-logs [player]": (
            "olympia_track",
            "SELECT pl.*, m.Name AS MemberName, s.SportName "
            "FROM PerformanceLog pl "
            "JOIN Member m ON pl.MemberID = m.MemberID "
            "JOIN Sport  s ON pl.SportID  = s.SportID "
            "WHERE pl.MemberID = %s ORDER BY pl.RecordDate DESC",
            (pmid,),
        ),
        f"GET /api/medical-records/{pmid} [admin]": (
            "olympia_track",
            "SELECT * FROM MedicalRecord WHERE MemberID = %s ORDER BY DiagnosisDate DESC",
            (pmid,),
        ),
        "GET /admin/audit-log": (
            "olympia_auth",
            "SELECT * FROM audit_log ORDER BY log_id DESC LIMIT %s",
            (100,),
        ),
    }


def run_mode(mode: str, ids: dict, n_requests: int, endpoints_override: list = None):
    endpoints       = endpoints_override or build_endpoints(ids)
    explain_queries = build_explain_queries(ids)
    print(f"\n{'='*60}")
    print(f"  Mode: {mode.upper()}  |  {n_requests} requests per endpoint")
    print(f"{'='*60}\n")
    sessions = {role: login(role) for role in ("admin", "coach", "player")}
    results = {}
    
    print(f"  Benchmarking API Latency...")
    for label, role, method, path in endpoints:
        url = BASE_URL + path
        print(f"  {label:<52}", end=" ", flush=True)
        stats = bench(sessions[role], method, url, n=n_requests)
        results[label] = stats
        print(f"mean={stats['mean']:6.1f}ms  p95={stats['p95']:6.1f}ms  errors={stats['errors']}")
    
    sql_results = {}
    print(f"\n  Benchmarking SQL Execution Time...")
    for label, (db_name, sql, params) in explain_queries.items():
        print(f"  {label:<52}", end=" ", flush=True)
        stats = measure_sql(db_name, sql, params, n=n_requests)
        sql_results[label] = stats
        print(f"mean={stats['mean']:6.3f}ms  p95={stats['p95']:6.3f}ms")

    explain_out = {}
    print(f"\n  Capturing EXPLAIN plans...")
    for label, (db_name, sql, params) in explain_queries.items():
        try:
            explain_out[label] = run_explain(db_name, sql, params)
        except Exception as ex:
            explain_out[label] = [{"error": str(ex)}]

    out_file = RESULTS_DIR / f"{mode}.json"
    out_file.write_text(json.dumps({
        "results": results, 
        "sql_results": sql_results, 
        "explain": explain_out
    }, indent=2, default=str))
    
    exp_file = RESULTS_DIR / f"{mode}_explain.txt"
    with exp_file.open("w") as f:
        for label, rows in explain_out.items():
            f.write(f"\n{'─'*60}\n{label}\n{'─'*60}\n")
            f.write(fmt_explain(rows) + "\n")
    print(f"\n  Results → {out_file}")
    print(f"  EXPLAIN → {exp_file}")
    return results


def print_slowest(n: int = 5):
    before_file = RESULTS_DIR / "before.json"
    if not before_file.exists():
        print("ERROR: Run --mode before first.")
        return
    results = json.loads(before_file.read_text())["results"]
    ranked  = sorted(results.items(), key=lambda x: x[1]["p95"], reverse=True)
    print(f"\nTop {n} slowest endpoints by p95 latency:\n")
    for i, (label, s) in enumerate(ranked[:n], 1):
        print(f"  {i}. {label}")
        print(f"     mean={s['mean']}ms  p95={s['p95']}ms  max={s['max']}ms\n")


def generate_report():
    before_file = RESULTS_DIR / "before.json"
    after_file  = RESULTS_DIR / "after.json"
    for f in (before_file, after_file):
        if not f.exists():
            print(f"ERROR: {f.name} not found.")
            return
    before_data = json.loads(before_file.read_text())
    after_data  = json.loads(after_file.read_text())
    before      = before_data["results"]
    after       = after_data["results"]
    before_sql  = before_data.get("sql_results", {})
    after_sql   = after_data.get("sql_results", {})
    before_exp  = before_data.get("explain", {})
    after_exp   = after_data.get("explain", {})
    lines = [
        "# SQL Indexing Benchmark Report\n",
        "## Response Time Comparison (ms)\n",
        "| Endpoint | Before mean | After mean | Before p95 | After p95 | Δ p95 (ms) |",
        "|----------|-------------|------------|------------|-----------|------------|",
    ]
    for label in sorted(after.keys(), key=lambda l: before.get(l, {}).get("p95", 0), reverse=True):
        b     = before.get(label, {})
        a     = after[label]
        delta = round(b.get("p95", 0) - a.get("p95", 0), 2)
        sign  = f"+{delta}" if delta > 0 else str(delta)
        lines.append(
            f"| `{label}` | {b.get('mean', '—')} | {a['mean']} "
            f"| {b.get('p95', '—')} | {a['p95']} | {sign} |"
        )

    lines.append("\n## SQL Execution Time Comparison (ms)\n")
    lines.append("| Query | Before mean | After mean | Before p95 | After p95 | Δ p95 |")
    lines.append("|-------|-------------|------------|------------|-----------|-------|")

    # Use keys from before/after combined to cover all cases
    all_sql_keys = set(before_sql.keys()) | set(after_sql.keys())
    for label in sorted(all_sql_keys):
        b = before_sql.get(label, {})
        a = after_sql.get(label, {})
        if not b or not a: 
            continue
        delta = round(b.get("p95", 0) - a.get("p95", 0), 3)
        lines.append(
            f"| `{label}` | {b.get('mean', '-')} | {a.get('mean', '-')} "
            f"| {b.get('p95', '-')} | {a.get('p95', '-')} | {delta} |"
        )

    lines.append("\n## EXPLAIN Access Plan Changes\n")
    for label in sorted(after_exp.keys()):
        b_rows = before_exp.get(label, [])
        a_rows = after_exp.get(label, [])
        lines += [
            f"### `{label}`\n",
            "**Before:**\n```",
            fmt_explain(b_rows),
            "```\n**After:**\n```",
            fmt_explain(a_rows),
            "```\n",
        ]
    report = RESULTS_DIR / "report.md"
    report.write_text("\n".join(lines))
    print(f"Report saved → {report}")


def main():
    parser = argparse.ArgumentParser(description="Olympia Track benchmark tool")
    parser.add_argument("--mode",    choices=["before", "after"],
                        help="before: baseline all endpoints; after: re-bench slowest N")
    parser.add_argument("--report",  action="store_true", help="Generate before/after comparison report")
    parser.add_argument("--slowest", action="store_true", help="Print slowest endpoints from before.json")
    parser.add_argument("--top",     type=int, default=5,   help="N slowest endpoints (default 5)")
    parser.add_argument("--n",       type=int, default=N_REQUESTS, help="Requests per endpoint (default 100)")
    args = parser.parse_args()
    if args.report:
        generate_report()
        return
    if args.slowest:
        print_slowest(args.top)
        return
    ids = get_sample_ids()
    print(f"Sample IDs from DB: {ids}")
    if args.mode == "before":
        run_mode("before", ids, n_requests=args.n)
    elif args.mode == "after":
        before_file = RESULTS_DIR / "before.json"
        if not before_file.exists():
            print("ERROR: Run --mode before first.")
            return
        results = json.loads(before_file.read_text())["results"]
        ranked  = sorted(results.items(), key=lambda x: x[1]["p95"], reverse=True)
        slowest = {label for label, _ in ranked[:args.top]}
        all_eps = build_endpoints(ids)
        eps     = [ep for ep in all_eps if ep[0] in slowest]
        if not eps:
            print("No matching endpoints found — run --mode before again.")
            return
        print(f"Re-benchmarking top {args.top} slowest endpoints:")
        for ep in eps:
            print(f"  {ep[0]}")
        run_mode("after", ids, n_requests=args.n, endpoints_override=eps)
    else:
        parser.print_help()
if __name__ == "__main__":
    main()
