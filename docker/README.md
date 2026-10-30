# CR300 pipeline — Docker

Two containers from one image, sharing `./data`:
- **collector** — reads the CR300 over RS-232 (PakBus) → CSV (+ optional InfluxDB)
- **api** — serves the CSV data as a zero-dependency REST API on port 8000

```
CR300 ──RS232──> /dev/cr300 (host) ──device map──> collector ──> ./data ──> api :8000
```

## Files
```
docker/
  Dockerfile
  docker-compose.yml
  .env            # edit this when moving machines
  collector.py
  api.py
  data/           # created on first run: csv/, state.json, latest.json
```

## First run (on the IRIV / any Linux host with Docker)

1. Make the serial device stable (once per host). The CR300's RS-232 is
   USB interface **02** of the CH342 dual-serial chip. This udev rule pins it
   to `/dev/cr300` no matter which ttyACM number it gets:
   ```bash
   sudo tee /etc/udev/rules.d/99-cr300.rules >/dev/null <<'EOF'
   SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="1a86", ENV{ID_MODEL_ID}=="55d2", ENV{ID_USB_INTERFACE_NUM}=="02", SYMLINK+="cr300"
   EOF
   sudo udevadm control --reload-rules
   sudo udevadm trigger --action=add --subsystem-match=tty
   ls -l /dev/cr300      # should point at a ttyACMx
   ```

2. Build and start:
   ```bash
   cd docker
   docker compose up -d --build
   docker compose logs -f collector     # watch it pull records
   ```

3. Test the API:
   ```bash
   curl -s localhost:8000/health
   curl -s "localhost:8000/records?hours=48"
   ```

## API endpoints
- `GET /health`
- `GET /latest`
- `GET /records?hours=24`
- `GET /records?date=YYYY-MM-DD`
- `GET /records?...&raw=1`  (keep -8190 / NAN values)
- `GET /fields`
- `GET /days`
- `GET /csv/YYYY-MM-DD`  (raw CSV download)

Reachable from the LAN at `http://<host-ip>:8000/...`.

## Moving to another machine — full guide

Everything host-specific lives in `.env`, so a move is: copy folder → install
Docker → pin the serial device → bring it up → test. Step by step:

### Step 0 — copy the folder to the new host
From the old host (or a USB drive):
```bash
# over the network (replace user@newhost and the path)
rsync -av ~/cr300/docker/ user@newhost:~/cr300/docker/
#   keep data/ to carry history over; or exclude it to start fresh:
#   rsync -av --exclude data ~/cr300/docker/ user@newhost:~/cr300/docker/
```
Plug the CR300's USB-serial adapter into the new host.

### Step 1 — install Docker (once per host)
```bash
# Debian / Raspberry Pi OS / Ubuntu
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER      # run docker without sudo
# log out and back in (or: newgrp docker) so the group takes effect
docker --version                   # verify
docker compose version             # verify the compose plugin is present
```

### Step 2 — pin the serial device
The CR300's RS-232 is USB **interface 02** of the CH342 chip. Two ways —
pick one:

**A. udev rule → `/dev/cr300` (recommended, survives re-plug/reboot)**
```bash
sudo tee /etc/udev/rules.d/99-cr300.rules >/dev/null <<'EOF'
SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="1a86", ENV{ID_MODEL_ID}=="55d2", ENV{ID_USB_INTERFACE_NUM}=="02", SYMLINK+="cr300"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger --action=add --subsystem-match=tty
ls -l /dev/cr300        # must point at a ttyACMx
```
Keep `SERIAL_DEV=/dev/cr300` in `.env`.

> Different adapter/chip? Find its vendor/model/interface with
> `udevadm info -q property -n /dev/ttyACMx | grep -E "ID_VENDOR_ID|ID_MODEL_ID|ID_USB_INTERFACE_NUM"`
> and put those values in the rule.

**B. by-id path (no rule, but tied to that exact adapter's serial number)**
```bash
ls -l /dev/serial/by-id/
# copy the ...-if02 entry into .env, e.g.:
#   SERIAL_DEV=/dev/serial/by-id/usb-1a86_USB_Dual_Serial_56F3023938-if02
```

### Step 3 — adjust `.env` for the new host
Edit as needed:
- `SERIAL_DEV` — from Step 2 (leave `/dev/cr300` if you used the udev rule)
- `LOGGER_OFFSET_HOURS` — `-7` while the CR300 clock is 7 h fast; `0` after you fix it
- `TZ` — host timezone (affects the API's "last N hours" window)
- `API_PORT` — change if 8000 is taken
- `CR300_TABLE` — `Every60` (hourly) or `Every30`

### Step 4 — build and start
```bash
cd ~/cr300/docker
docker compose up -d --build
```

### Step 5 — test it works
```bash
# containers should both be "running"
docker compose ps

# collector should log the connection + "wrote N row(s)" within a minute
docker compose logs -f collector        # Ctrl+C to stop watching

# API answers locally
curl -s localhost:8000/health
curl -s localhost:8000/latest
curl -s "localhost:8000/records?hours=48"

# and from another PC on the LAN (replace with the new host's IP)
curl -s "http://<newhost-ip>:8000/records?hours=24"
```
Success = `/health` returns `{"status":"ok",...}` and `/records` returns rows
with a recent `TimeStamp`.

### Everyday commands
```bash
docker compose logs -f collector   # live collector log
docker compose restart collector   # after unplug/replug of the USB
docker compose down                # stop both containers
docker compose up -d               # start again (no rebuild)
docker compose up -d --build       # rebuild after editing collector.py/api.py
```

## Notes
- **`LOGGER_OFFSET_HOURS=-7`** corrects the CR300 clock (currently 7 h fast) to
  true local time. If you later fix the CR300 clock via Device Configuration
  Utility, set this to `0`.
- **-8190 / NAN** values (unconnected sensors) are dropped from the API by
  default and left blank in the CSV. They reappear with `&raw=1`.
- **Device re-plug:** if you physically unplug/replug the USB while the
  container runs, the mapped device node goes stale — `docker compose restart
  collector` to re-grab it. A host reboot is handled automatically
  (`restart: unless-stopped` + the udev rule recreates `/dev/cr300`).
- **InfluxDB:** uncomment the `INFLUX_*` lines in `.env` to also write to an
  InfluxDB. To run Influx in the same stack, add an `influxdb` service to
  docker-compose.yml and set `INFLUX_URL=http://influxdb:8086`.
```
