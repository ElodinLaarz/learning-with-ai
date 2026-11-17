"""Local web application: IPO evaluator + Historical Validation dashboard.

    python -m ipo_app.server            # http://127.0.0.1:8765

Standard library only. The evaluator runs the same engine and rule files as the backtest.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from dataclasses import fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .engine import recommend as R
from .engine.calc import IPOInput

ROOT = Path(__file__).resolve().parents[1]
WEB = Path(__file__).resolve().parent / "web"
RESULTS = ROOT / "results"
RUNS = RESULTS / "runs"
DOWNLOADABLE = {"decisions.csv", "summary.json", "manifest.json", "walkforward_decisions.csv"}
_INPUT_FIELDS = {f.name: f for f in fields(IPOInput)}


def _safe(o):
    if isinstance(o, dict):
        return {k: _safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_safe(v) for v in o]
    if isinstance(o, float) and not math.isfinite(o):
        return "inf" if o > 0 else None
    return o


def read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def list_runs() -> list[dict]:
    out = []
    if RUNS.exists():
        for d in sorted(RUNS.iterdir()):
            m = read_json(d / "manifest.json")
            if m:
                m["files"] = sorted(f.name for f in d.iterdir() if f.name in DOWNLOADABLE)
                out.append(m)
    return sorted(out, key=lambda m: m.get("created_at", ""), reverse=True)


def validation_status() -> dict:
    v = read_json(RESULTS / "verdict.json")
    if not v:
        return {"label": "NOT HISTORICALLY VALIDATED", "verdict": "NO TEST RUN",
                "summary": "No held-out test run has been recorded for any rule version."}
    return v


def parse_input(body: dict) -> IPOInput:
    """Build an IPOInput from a JSON body. Empty strings mean 'not provided' (None), never zero."""
    kw = {}
    for k, v in body.items():
        if k not in _INPUT_FIELDS:
            continue
        if v == "" or v is None:
            continue
        t = _INPUT_FIELDS[k].type
        if k == "dilutive":
            kw[k] = [d for d in v if d.get("count") not in ("", None)]
            for d in kw[k]:
                d["count"], d["strike"] = float(d["count"]), float(d.get("strike") or 0.0)
        elif "bool" in str(t):
            kw[k] = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
        elif "str" in str(t) and "float" not in str(t) and "int" not in str(t):
            kw[k] = str(v)
        elif k == "sic":
            kw[k] = int(float(v))
        else:
            kw[k] = float(v)
    return IPOInput(**kw)


def evaluate_request(body: dict) -> dict:
    version = body.get("rule_version") or default_rule_version()
    rules = R.load_rules(version)
    inp = parse_input(body)
    res = R.evaluate(inp, rules)
    res["max_buy_price"] = R.max_buy_price(inp, rules) if inp.price else None
    ladder = []
    if inp.price and inp.price > 0:
        for mult in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0):
            e = R.evaluate(inp, rules, price=inp.price * mult, explain=False)
            ladder.append({"price": inp.price * mult, "recommendation": e["recommendation"],
                           "probability": e["probability"], "ev_sales": e["metrics"].get("ev_sales"),
                           "market_cap_diluted": e["metrics"].get("market_cap_diluted")})
    res["price_ladder"] = ladder
    res["validation_status"] = validation_status()
    res["rules_frozen"] = rules.get("frozen", False)
    return _safe(res)


def default_rule_version() -> str | None:
    vs = [v for v in R.list_rule_versions() if "error" not in v]
    frozen = [v for v in vs if v.get("frozen")]
    pick = (frozen or vs)
    return pick[-1]["version"] if pick else None


def decisions_page(run_id: str, q: dict) -> dict:
    name = "walkforward_decisions.csv" if q.get("set", [""])[0] == "walkforward" else "decisions.csv"
    p = RUNS / run_id / name
    if not p.exists():
        return {"rows": [], "total": 0}
    mode, rec, action = q.get("mode", [""])[0], q.get("rec", [""])[0], q.get("action", [""])[0]
    text = q.get("q", [""])[0].lower()
    offset, limit = int(q.get("offset", ["0"])[0]), min(int(q.get("limit", ["50"])[0]), 500)
    keep = ["symbol", "name", "priced_date", "sector", "mode", "recommendation", "probability", "action", "wait_bars",
            "gates", "no_decision_reason", "decision_price", "offer_price", "strat_entry_date", "strat_ret_1m",
            "strat_ret_3m", "strat_ret_6m", "strat_ret_12m", "strat_spy_12m", "strat_sector_12m", "strat_status_12m",
            "base_ret_12m", "base_spy_12m", "base_status_12m", "price_status", "sec_outcome", "screen", "wf_year"]
    rows, total = [], 0
    with p.open(newline="") as f:
        for r in csv.DictReader(f):
            if mode and r.get("mode") != mode:
                continue
            if rec and r.get("recommendation") != rec:
                continue
            if action and r.get("action") != action:
                continue
            if text and text not in (r.get("symbol", "") + " " + r.get("name", "")).lower():
                continue
            if offset <= total < offset + limit:
                rows.append({k: r.get(k, "") for k in keep})
            total += 1
    return {"rows": rows, "total": total, "offset": offset, "limit": limit}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else (json.dumps(body).encode() if ctype == "application/json" else body.encode())
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") or ctype.endswith("json") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        try:
            if not parts:
                return self._send(200, (WEB / "index.html").read_bytes(), "text/html")
            if parts == ["api", "status"]:
                led = read_json(RESULTS / "freeze_ledger.json", {"freezes": [], "unsealings": []})
                return self._send(200, {"validation": validation_status(), "rule_versions": R.list_rule_versions(),
                                        "default_rule_version": default_rule_version(), "ledger": led,
                                        "coverage": read_json(ROOT / "data" / "processed" / "coverage.json"),
                                        "provenance": read_json(ROOT / "data" / "processed" / "provenance.json"),
                                        "snapshot_present": (ROOT / "data" / "snapshot" / "prices.csv.gz").exists()})
            if parts == ["api", "runs"]:
                return self._send(200, list_runs())
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and (RUNS / parts[2]).is_dir():
                if parts[3] == "summary":
                    return self._send(200, read_json(RUNS / parts[2] / "summary.json", {}))
                if parts[3] == "decisions":
                    return self._send(200, decisions_page(parts[2], parse_qs(u.query)))
            if len(parts) == 3 and parts[0] == "download" and parts[2] in DOWNLOADABLE and (RUNS / parts[1] / parts[2]).is_file():
                ctype = "text/csv" if parts[2].endswith(".csv") else "application/json"
                return self._send(200, (RUNS / parts[1] / parts[2]).read_bytes(), ctype,
                                  {"Content-Disposition": f'attachment; filename="{parts[1]}-{parts[2]}"'})
            if parts == ["download", "VALIDATION_REPORT.md"] and (RESULTS / "VALIDATION_REPORT.md").exists():
                return self._send(200, (RESULTS / "VALIDATION_REPORT.md").read_bytes(), "text/markdown",
                                  {"Content-Disposition": 'attachment; filename="VALIDATION_REPORT.md"'})
            return self._send(404, {"error": "not found"})
        except Exception as e:                                  # surface errors to the UI instead of hanging
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        if urlparse(self.path).path != "/api/evaluate":
            return self._send(404, {"error": "not found"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
            return self._send(200, evaluate_request(body))
        except (ValueError, TypeError, KeyError, FileNotFoundError) as e:
            return self._send(400, {"error": f"{type(e).__name__}: {e}"})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"IPO Evaluator running at http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
