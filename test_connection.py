"""Quick check that RS232 + PakBus works before running the full pipeline.

Run:  python test_connection.py
It lists the tables and prints the most recent few records.
If this fails with your CR300 OS, switch to the SerialOut fallback (README).
"""
import datetime as dt
import logging
import os

from dotenv import load_dotenv

from reader import CR300Reader

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

url = os.getenv("CR300_URL", "serial:/dev/ttyACM1:38400")
table = os.getenv("CR300_TABLE") or None

r = CR300Reader(url, table)
tables = r.connect()

now = dt.datetime.now()
rows = r.read_since(now - dt.timedelta(hours=6), now)
print(f"\nGot {len(rows)} record(s) from table {r.table!r} in the last 6h.")
for row in rows[-3:]:
    ts = row.get("Datetime")
    fields = {k: v for k, v in row.items() if k != "Datetime"}
    print(f"\n{ts}")
    for k, v in fields.items():
        print(f"  {k:<16} {v}")
