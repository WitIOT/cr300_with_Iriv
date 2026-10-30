#!/usr/bin/env python3
"""Zero-dependency REST API for CR300 data (reads the collector's CSV files).

Serves data the collector writes to ~/cr300/data/ . No pip installs, no DB.

Endpoints:
  GET /                      -> list of endpoints
  GET /health                -> {"status":"ok", ...}
  GET /latest                -> newest record (from latest.json)
  GET /records?date=YYYY-MM-DD   -> all rows for that day
  GET /records?hours=N           -> rows from the last N hours (default 24)
  GET /records?...&raw=1         -> keep -8190 / blank NAN values (default: dropped)
  GET /fields                -> list of column names seen
  GET /days                  -> list of dates that have data
  GET /csv/YYYY-MM-DD        -> download that day's raw CSV

Config via env:
  DATA_HOME=~/cr300/data   API_HOST=0.0.0.0   API_PORT=8000   STATION=narit_cr300
"""
import csv
import datetime as dt
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HOME = Path(os.path.expanduser(os.getenv("DATA_HOME", "~/cr300/data")))
CSV_DIR = HOME / "csv"
LATEST_FILE = HOME / "latest.json"
HOST = os.getenv("API_HOST", "0.0.0.0")
PORT = int(os.getenv("API_PORT", "8000"))
STATION = os.getenv("STATION", "narit_cr300")
NODATA = "-8190.0"


def day_files():
    if not CSV_DIR.exists():
        return []
    return sorted(CSV_DIR.glob("*.csv"))


def read_day(date_str, drop_nan=True):
    path = CSV_DIR / f"{date_str}.csv"
    if not path.exists():
        return []
    rows = []
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            if drop_nan:
                r = {k: v for k, v in r.items()
                     if v not in ("", NODATA, "nan", "-8190", "-8190.00")}
            rows.append(r)
    return rows


def parse_ts(r):
    ts = r.get("TimeStamp", "")
    try:
        return dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, code=200, ctype="application/json"):
        if ctype == "application/json":
            body = json.dumps(obj, ensure_ascii=False, default=str).encode()
        else:
            body = obj if isinstance(obj, bytes) else str(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass  # quiet

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        drop = q.get("raw", ["0"])[0] not in ("1", "true", "yes")
        try:
            if u.path == "/":
                self._send({"station": STATION, "endpoints": [
                    "/health", "/latest", "/records?hours=24",
                    "/records?date=YYYY-MM-DD", "/fields", "/days",
                    "/csv/YYYY-MM-DD"]})
            elif u.path == "/health":
                self._send({"status": "ok", "station": STATION,
                            "now": dt.datetime.now().isoformat(),
                            "days": len(day_files())})
            elif u.path == "/latest":
                if LATEST_FILE.exists():
                    self._send(json.loads(LATEST_FILE.read_text()))
                else:
                    self._send({"error": "no data yet"}, 503)
            elif u.path == "/days":
                self._send({"days": [p.stem for p in day_files()]})
            elif u.path == "/fields":
                flds = set()
                for p in day_files():
                    with p.open(newline="") as f:
                        flds.update(next(csv.reader(f), []))
                self._send({"fields": sorted(flds)})
            elif u.path == "/records":
                if "date" in q:
                    rows = read_day(q["date"][0], drop)
                else:
                    hours = int(q.get("hours", ["24"])[0])
                    cutoff = dt.datetime.now() - dt.timedelta(hours=hours)
                    rows = []
                    # read last 2 day-files (enough to cover any hours<=48)
                    for p in day_files()[-3:]:
                        for r in read_day(p.stem, drop):
                            ts = parse_ts(r)
                            if ts and ts >= cutoff:
                                rows.append(r)
                    rows.sort(key=lambda r: r.get("TimeStamp", ""))
                self._send({"station": STATION, "count": len(rows),
                            "records": rows})
            elif u.path.startswith("/csv/"):
                name = u.path[len("/csv/"):]
                p = CSV_DIR / f"{name}.csv"
                if p.exists() and p.parent == CSV_DIR:
                    self._send(p.read_bytes(), ctype="text/csv")
                else:
                    self._send({"error": "not found"}, 404)
            else:
                self._send({"error": "unknown endpoint"}, 404)
        except Exception as e:  # noqa: BLE001
            self._send({"error": f"{type(e).__name__}: {e}"}, 500)


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"CR300 API on http://{HOST}:{PORT}  data={HOME}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
