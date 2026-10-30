"""Thin wrapper over pycampbellcr1000 to pull records from a CR300 data table.

Exposes a small, stable interface so the rest of the pipeline does not care
how records are fetched. If you switch to the SerialOut-push method later,
only this file changes (see README, "Fallback").
"""
import datetime as dt
import logging

from pycampbellcr1000 import CR1000

log = logging.getLogger("reader")

# Tables that are not time-series logged data
SYSTEM_TABLES = {"Status", "Public", "DataTableInfo"}


def _s(x):
    return x.decode() if isinstance(x, bytes) else x


class CR300Reader:
    def __init__(self, url: str, table: str | None = None):
        self.url = url          # e.g. "serial:/dev/ttyACM1:38400"
        self.table = table
        self.device = None

    def connect(self):
        log.info("Connecting to CR300 at %s", self.url)
        self.device = CR1000.from_url(self.url)
        tables = [_s(t) for t in self.device.list_tables()]
        log.info("Tables on logger: %s", tables)
        if not self.table:
            for t in tables:
                if t not in SYSTEM_TABLES:
                    self.table = t
                    break
        if self.table not in tables:
            raise RuntimeError(
                f"Table {self.table!r} not found. Available: {tables}"
            )
        log.info("Reading from table: %s", self.table)
        return tables

    def read_since(self, start: dt.datetime, stop: dt.datetime | None = None):
        """Return records with TimeStamp in (start, stop] as list[dict].

        Each dict has a 'Datetime' key (datetime) plus one key per column.
        """
        if self.device is None:
            self.connect()
        stop = stop or dt.datetime.now()
        raw = self.device.get_data(self.table, start, stop)
        out = []
        for rec in raw:
            row = {_s(k): v for k, v in rec.items()}
            out.append(row)
        return out
