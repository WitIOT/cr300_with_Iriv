#!/usr/bin/env python3
"""Zero-dependency REST API for CR300 data (reads the collector's CSV files).

Serves both data streams the collector writes under DATA_HOME:
  - averaged : data/csv/      (Every60, hourly)  -> default stream
  - live     : data/public/   (Public snapshots) -> ?stream=live

No pip installs, no DB.

Endpoints:
  GET /                           -> list of endpoints
  GET /health                     -> {"status":"ok", ...}
  GET /latest                     -> newest averaged record (latest.json)
  GET /live                       -> newest live snapshot (latest_public.json)
  GET /records?hours=N            -> averaged rows, last N hours (default 24)
  GET /records?date=YYYY-MM-DD    -> averaged rows for that day
  GET /records?stream=live&...    -> same queries against the live stream
  GET /records?...&raw=1          -> keep -8190 / blank NAN values
  GET /fields?stream=live|averaged
  GET /days?stream=live|averaged
  GET /csv/YYYY-MM-DD?stream=live|averaged   -> raw CSV download

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
DIRS = {"averaged": HOME / "csv", "live": HOME / "public"}
LATEST = {"averaged": HOME / "latest.json", "live": HOME / "latest_public.json"}
HOST = os.getenv("API_HOST", "0.0.0.0")
PORT = int(os.getenv("API_PORT", "8000"))
STATION = os.getenv("STATION", "narit_cr300")
NODATA = "-8190.0"


def stream_of(q):
    s = q.get("stream", ["averaged"])[0]
    return s if s in DIRS else "averaged"


def day_files(stream):
    d = DIRS[stream]
    return sorted(d.glob("*.csv")) if d.exists() else []


def read_day(stream, date_str, drop_nan=True):
    path = DIRS[stream] / f"{date_str}.csv"
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
    try:
        return dt.datetime.strptime(r.get("TimeStamp", ""), "%Y-%m-%d %H:%M:%S")
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
        pass

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        drop = q.get("raw", ["0"])[0] not in ("1", "true", "yes")
        stream = stream_of(q)
        try:
            if u.path == "/":
                self._send({"station": STATION, "streams": list(DIRS),
                            "endpoints": [
                                "/health", "/latest", "/live",
                                "/records?hours=24", "/records?stream=live&hours=2",
                                "/records?date=YYYY-MM-DD", "/fields", "/days",
                                "/csv/YYYY-MM-DD"]})
            elif u.path == "/health":
                self._send({"status": "ok", "station": STATION,
                            "now": dt.datetime.now().isoformat(),
                            "averaged_days": len(day_files("averaged")),
                            "live_days": len(day_files("live"))})
            elif u.path == "/latest":
                f = LATEST["averaged"]
                self._send(json.loads(f.read_text()) if f.exists()
                           else {"error": "no data yet"}, 200 if f.exists() else 503)
            elif u.path == "/live":
                f = LATEST["live"]
                self._send(json.loads(f.read_text()) if f.exists()
                           else {"error": "no live data yet"}, 200 if f.exists() else 503)
            elif u.path == "/days":
                self._send({"stream": stream,
                            "days": [p.stem for p in day_files(stream)]})
            elif u.path == "/fields":
                flds = set()
                for p in day_files(stream):
                    with p.open(newline="") as f:
                        flds.update(next(csv.reader(f), []))
                self._send({"stream": stream, "fields": sorted(flds)})
            elif u.path == "/records":
                if "date" in q:
                    rows = read_day(stream, q["date"][0], drop)
                else:
                    hours = int(q.get("hours", ["24"])[0])
                    cutoff = dt.datetime.now() - dt.timedelta(hours=hours)
                    rows = []
                    for p in day_files(stream)[-3:]:
                        for r in read_day(stream, p.stem, drop):
                            ts = parse_ts(r)
                            if ts and ts >= cutoff:
                                rows.append(r)
                    rows.sort(key=lambda r: r.get("TimeStamp", ""))
                self._send({"station": STATION, "stream": stream,
                            "count": len(rows), "records": rows})
            elif u.path.startswith("/csv/"):
                name = u.path[len("/csv/"):]
                p = DIRS[stream] / f"{name}.csv"
                if p.exists() and p.parent == DIRS[stream]:
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
