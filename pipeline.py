"""Collector daemon.

Loop: pull new records from the CR300 over RS232 (PakBus) ->
  1. append to a daily CSV file  (data/YYYY-MM-DD.csv)
  2. write points to InfluxDB
  3. write latest.json (served by api.py)

New records are de-duplicated by RecNum so nothing is written twice.
"""
import csv
import datetime as dt
import json
import logging
import os
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from reader import CR300Reader

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pipeline")

URL = os.getenv("CR300_URL", "serial:/dev/ttyACM1:38400")
TABLE = os.getenv("CR300_TABLE") or None
POLL = int(os.getenv("POLL_SECONDS", "60"))
BACKFILL_H = int(os.getenv("BACKFILL_HOURS", "2"))
STATION = os.getenv("STATION", "cr300")
LOGGER_TZ = ZoneInfo(os.getenv("LOGGER_TZ", "Asia/Bangkok"))
UTC = ZoneInfo("UTC")

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
STATE_FILE = Path(os.getenv("STATE_FILE", "./state.json"))
LATEST_FILE = Path(os.getenv("LATEST_FILE", "./latest.json"))

INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")
INFLUX_ORG = os.getenv("INFLUX_ORG", "narit")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "cr300")
MEASUREMENT = os.getenv("INFLUX_MEASUREMENT", "weather")

DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------- helpers ----------
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_recnum": -1, "last_time": None}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state))


def recnum(row):
    try:
        return int(row.get("RecNum", -1))
    except (TypeError, ValueError):
        return -1


def to_utc(d: dt.datetime) -> dt.datetime:
    if d.tzinfo is None:
        d = d.replace(tzinfo=LOGGER_TZ)
    return d.astimezone(UTC)


def jsonable(row):
    out = {}
    for k, v in row.items():
        out[k] = v.isoformat() if isinstance(v, dt.datetime) else v
    return out


def write_csv(row):
    ts = row.get("Datetime")
    day = ts.strftime("%Y-%m-%d") if isinstance(ts, dt.datetime) else "unknown"
    path = DATA_DIR / f"{day}.csv"
    # stable column order: RecNum, TimeStamp/Datetime first, then the rest
    keys = list(row.keys())
    head = [k for k in ("RecNum", "TimeStamp", "Datetime") if k in keys]
    rest = [k for k in keys if k not in head]
    fields = head + rest
    new_file = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new_file:
            w.writeheader()
        w.writerow({k: (v.isoformat() if isinstance(v, dt.datetime) else v)
                    for k, v in row.items()})


def to_point(row):
    ts = row.get("Datetime")
    p = Point(MEASUREMENT).tag("station", STATION)
    if isinstance(ts, dt.datetime):
        p.time(to_utc(ts), WritePrecision.S)
    for k, v in row.items():
        if k in ("Datetime", "TimeStamp"):
            continue
        if isinstance(v, bool):
            p.field(k, v)
        elif isinstance(v, (int, float)):
            p.field(k, float(v))
        # non-numeric strings are skipped; add p.field(k, str(v)) if you want them
    return p


# ---------- main loop ----------
def main():
    reader = CR300Reader(URL, TABLE)
    influx = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api = influx.write_api(write_options=SYNCHRONOUS)
    state = load_state()
    log.info("Starting. state=%s", state)

    while True:
        try:
            if reader.device is None:
                reader.connect()

            now = dt.datetime.now()
            if state["last_time"]:
                start = dt.datetime.fromisoformat(state["last_time"])
            else:
                start = now - dt.timedelta(hours=BACKFILL_H)

            rows = reader.read_since(start, now)
            new = [r for r in rows if recnum(r) > state["last_recnum"]]
            new.sort(key=recnum)

            for row in new:
                write_csv(row)
                write_api.write(bucket=INFLUX_BUCKET, record=to_point(row))
                state["last_recnum"] = recnum(row)
                ts = row.get("Datetime")
                if isinstance(ts, dt.datetime):
                    state["last_time"] = ts.isoformat()

            if new:
                LATEST_FILE.write_text(json.dumps(jsonable(new[-1]), default=str))
                save_state(state)
                log.info("Wrote %d new record(s), last RecNum=%s",
                         len(new), state["last_recnum"])
            else:
                log.debug("No new records")

        except Exception:
            log.exception("Cycle failed; will reconnect next loop")
            reader.device = None  # force reconnect

        time.sleep(POLL)


if __name__ == "__main__":
    main()
