#!/usr/bin/env python3
"""CR300 -> CSV (+ optional InfluxDB) collector. Self-contained.

Runs with only pycampbellcr1000 + stdlib. InfluxDB is optional:
set INFLUX_URL + INFLUX_TOKEN env vars to enable it.

Config via env vars (all optional, sane defaults):
  CR300_URL=serial:/dev/ttyACM2:115200
  CR300_TABLE=Every60
  POLL_SECONDS=60
  BACKFILL_HOURS=6
  LOGGER_OFFSET_HOURS=-7     # CR300 clock is 7h fast; -7 corrects to true Thai time
  STATION=narit_cr300
  DATA_HOME=~/cr300_data
  INFLUX_URL= INFLUX_TOKEN= INFLUX_ORG= INFLUX_BUCKET= INFLUX_MEASUREMENT=
"""
import csv
import datetime as dt
import json
import math
import os
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from pycampbellcr1000 import CR1000


def log(m):
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {m}", flush=True)


URL = os.getenv("CR300_URL", "serial:/dev/ttyACM2:115200")
TABLE = os.getenv("CR300_TABLE", "Every60")
POLL = int(os.getenv("POLL_SECONDS", "60"))
BACKFILL_H = int(os.getenv("BACKFILL_HOURS", "6"))
OFFSET = dt.timedelta(hours=float(os.getenv("LOGGER_OFFSET_HOURS", "-7")))
TZ = ZoneInfo(os.getenv("LOGGER_TZ", "Asia/Bangkok"))
UTC = ZoneInfo("UTC")
STATION = os.getenv("STATION", "narit_cr300")

HOME = Path(os.path.expanduser(os.getenv("DATA_HOME", "~/cr300_data")))
DATA_DIR = HOME / "csv"
STATE_FILE = HOME / "state.json"
LATEST_FILE = HOME / "latest.json"
NODATA = -8190.0

# ---- optional InfluxDB ----
influx_write = None
if os.getenv("INFLUX_URL") and os.getenv("INFLUX_TOKEN"):
    try:
        from influxdb_client import InfluxDBClient, Point, WritePrecision
        from influxdb_client.client.write_api import SYNCHRONOUS
        _bucket = os.getenv("INFLUX_BUCKET", "cr300")
        _meas = os.getenv("INFLUX_MEASUREMENT", "weather")
        _client = InfluxDBClient(
            url=os.getenv("INFLUX_URL"),
            token=os.getenv("INFLUX_TOKEN"),
            org=os.getenv("INFLUX_ORG", "narit"),
        )
        _api = _client.write_api(write_options=SYNCHRONOUS)

        def influx_write(fields, utc_time):
            p = Point(_meas).tag("station", STATION).time(utc_time, WritePrecision.S)
            for k, v in fields.items():
                p.field(k, float(v))
            _api.write(bucket=_bucket, record=p)

        log("InfluxDB enabled")
    except Exception as e:
        log(f"InfluxDB disabled ({e}); continuing with CSV only")
else:
    log("InfluxDB not configured; CSV only")


# ---- helpers ----
def ckey(k):
    """Clean a column key: real bytes -> str, and the string form b'Name' -> Name."""
    if isinstance(k, bytes):
        return k.decode(errors="ignore")
    k = str(k)
    if (k.startswith("b'") and k.endswith("'")) or (k.startswith('b"') and k.endswith('"')):
        return k[2:-1]
    return k


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def good(v):
    return is_num(v) and not (isinstance(v, float) and math.isnan(v)) and v != NODATA


def rec_nbr(d):
    for key in ("RecNbr", "RecNum"):
        if key in d:
            try:
                return int(d[key])
            except (TypeError, ValueError):
                pass
    return -1


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_rn": -1, "last_logger_time": None}


# ---- device ops with retry (handles the transient PakBus 8-byte blips) ----
dev = None


def connect():
    global dev
    for i in range(8):
        try:
            dev = CR1000.from_url(URL)
            return dev
        except Exception as e:
            log(f"  connect {i+1}: {type(e).__name__}: {e}")
            time.sleep(2)
    raise RuntimeError("connect failed")


def op(fn):
    global dev
    last = None
    for i in range(4):
        try:
            if dev is None:
                connect()
            return fn(dev)
        except Exception as e:
            last = e
            log(f"  op {i+1}: {type(e).__name__}: {e}")
            dev = None
            time.sleep(2)
    raise RuntimeError(f"op failed: {last}")


def process(raw):
    row = {ckey(k): v for k, v in raw.items()}
    rn = rec_nbr(row)
    logger_dt = row.get("Datetime")
    local = (logger_dt + OFFSET) if isinstance(logger_dt, dt.datetime) else None
    fields = {k: v for k, v in row.items()
              if k not in ("Datetime", "RecNbr", "RecNum") and good(v)}
    return rn, logger_dt, local, row, fields


def write_csv(rn, local, row):
    day = local.strftime("%Y-%m-%d") if local else "unknown"
    path = DATA_DIR / f"{day}.csv"
    out = {"TimeStamp": local.strftime("%Y-%m-%d %H:%M:%S") if local else "",
           "RecNbr": rn}
    for k, v in row.items():
        if k in ("Datetime", "RecNbr", "RecNum"):
            continue
        if isinstance(v, float) and math.isnan(v):
            v = ""
        out[k] = v
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out.keys()), extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(out)


def write_latest(rn, local, fields):
    LATEST_FILE.write_text(json.dumps({
        "station": STATION,
        "RecNbr": rn,
        "time_local": local.strftime("%Y-%m-%d %H:%M:%S") if local else None,
        "fields": fields,
    }, default=str))


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    st = load_state()
    log(f"start URL={URL} TABLE={TABLE} station={STATION} offset={OFFSET} data={HOME}")
    while True:
        try:
            logger_now = op(lambda d: d.gettime())
            if st["last_logger_time"]:
                start = dt.datetime.fromisoformat(st["last_logger_time"])
            else:
                start = logger_now - dt.timedelta(hours=BACKFILL_H)
            stop = logger_now + dt.timedelta(minutes=1)

            raws = op(lambda d: d.get_data(TABLE, start, stop))
            new = [process(r) for r in raws]
            new = [x for x in new if x[0] > st["last_rn"]]
            new.sort(key=lambda x: x[0])

            for rn, logger_dt, local, row, fields in new:
                write_csv(rn, local, row)
                if influx_write and local and fields:
                    try:
                        influx_write(fields, local.replace(tzinfo=TZ).astimezone(UTC))
                    except Exception as e:
                        log(f"  influx write: {e}")
                st["last_rn"] = rn
                if isinstance(logger_dt, dt.datetime):
                    st["last_logger_time"] = logger_dt.isoformat()

            if new:
                rn, logger_dt, local, row, fields = new[-1]
                write_latest(rn, local, fields)
                STATE_FILE.write_text(json.dumps(st))
                log(f"wrote {len(new)} row(s), last RecNbr={st['last_rn']} local={local} fields={list(fields)}")
            else:
                log("no new rows")
        except Exception as e:
            log(f"cycle error: {type(e).__name__}: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
