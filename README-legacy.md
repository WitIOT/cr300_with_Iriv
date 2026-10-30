# CR300 → IRIV PiControl pipeline — ไฟล์ทั้งหมด

ระบบดึงข้อมูล Campbell CR300 ผ่าน RS-232 → CSV → REST API (+ InfluxDB ได้)

## มี 2 แบบ deploy เลือกใช้อย่างใดอย่างหนึ่ง

### A) รันตรงบน Pi ด้วย systemd (ที่ใช้งานอยู่ตอนนี้)
- `collector_standalone.py` — ตัวเก็บข้อมูลหลัก (RS-232 → CSV + latest.json), retry เอง, แก้ key byte-string, กรอง -8190/nan, ชดเชยเวลา -7 ชม. เป็น ~/cr300/collector.py บน Pi
- `api_stdlib.py` — REST API แบบไม่ต้องลง package (stdlib ล้วน) อ่านจาก CSV เป็น ~/cr300/api.py บน Pi

### B) Docker (พร้อมย้ายเครื่อง) — โฟลเดอร์ docker/
- `docker/Dockerfile`, `docker/docker-compose.yml`, `docker/.env`
- `docker/collector.py`, `docker/api.py` (สำเนาของ A)
- `docker/README.md` — คู่มือ deploy + ย้ายเครื่องแบบครบ (ติดตั้ง Docker, udev, build, ทดสอบ)

## ชุดเดิม (เวอร์ชันแรก — ใช้ pycampbellcr1000 lib + InfluxDB โดยตรง)
- `reader.py`, `pipeline.py`, `api.py` (เวอร์ชัน InfluxDB), `test_connection.py`
- `requirements.txt`, `README.md`
เก็บไว้อ้างอิง แต่แนะนำใช้ชุด A หรือ B ซึ่งทนทานกว่าและไม่ต้องพึ่ง InfluxDB

## ค่าคอนฟิกสำคัญ (จากการติดตั้งจริง)
- พอร์ต RS-232 บน IRIV = interface 02 ของ CH342 → udev rule ผูกเป็น /dev/cr300
- สาย: CAT6 เข้า DB9  ขา2=ขาวส้ม+ส้ม(TX) ขา3=ขาวเขียว+เขียว(RX) ขา5=ขาวน้ำตาล+น้ำตาล(GND)
- baud 115200, PakBus addr 1, security 0
- table: Every60 (ทุกชั่วโมง), Every30 (ทุก 30 นาที)
- LOGGER_OFFSET_HOURS=-7 (นาฬิกา CR300 เร็วไป 7 ชม.)
