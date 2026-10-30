"""Public read API for the CR300 data.

  GET /health              -> service status
  GET /latest              -> newest record (from latest.json)
  GET /records?hours=24    -> time-series from InfluxDB
  GET /records?hours=6&field=AirT_C   -> single field only

Run:  uvicorn api:app --host 0.0.0.0 --port 8000
"""
import datetime as dt
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from influxdb_client import InfluxDBClient

load_dotenv()

LATEST_FILE = Path(os.getenv("LATEST_FILE", "./latest.json"))
INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")
INFLUX_ORG = os.getenv("INFLUX_ORG", "narit")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "cr300")
MEASUREMENT = os.getenv("INFLUX_MEASUREMENT", "weather")
STATION = os.getenv("STATION", "cr300")

app = FastAPI(title="NARIT CR300 Weather API", version="1.0")
_influx = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)


@app.get("/health")
def health():
    return {"status": "ok", "utc": dt.datetime.utcnow().isoformat() + "Z"}


@app.get("/latest")
def latest():
    if not LATEST_FILE.exists():
        raise HTTPException(503, "no data collected yet")
    return json.loads(LATEST_FILE.read_text())


@app.get("/records")
def records(
    hours: int = Query(24, ge=1, le=24 * 30, description="look-back window in hours"),
    field: str | None = Query(None, description="return only this column"),
    limit: int = Query(5000, ge=1, le=50000),
):
    field_filter = f'|> filter(fn: (r) => r._field == "{field}")' if field else ""
    flux = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT}")
  |> filter(fn: (r) => r.station == "{STATION}")
  {field_filter}
  |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
  |> limit(n: {limit})
'''
    try:
        tables = _influx.query_api().query(flux, org=INFLUX_ORG)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"influx query failed: {e}")

    rows = []
    for t in tables:
        for rec in t.records:
            values = dict(rec.values)
            row = {"time": values.pop("_time").isoformat()}
            for k, v in values.items():
                if not k.startswith("_") and k not in ("result", "table", "station"):
                    row[k] = v
            rows.append(row)
    return {"station": STATION, "count": len(rows), "records": rows}
