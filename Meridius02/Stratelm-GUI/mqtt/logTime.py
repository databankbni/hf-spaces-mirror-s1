import paho.mqtt.client as mqtt
import json
import csv
import os
import datetime
import socket

# ---------------------------------------------------------------------------
# logTime.py  —  sama seperti log.py TAPI menambahkan 3 kolom timestamp WIB
# pada setiap baris CSV yang disimpan:
#
#   received_at_wib   : waktu perangkat PC menerima pesan  (ISO 8601, WIB)
#   received_date_wib : tanggal saja  (YYYY-MM-DD)
#   received_time_wib : jam saja      (HH:MM:SS.ffffff)
#
# Ini berguna untuk:
#   1. Mendeteksi clock drift MCU vs waktu real WIB
#   2. Menghitung offset antara timestamp MCU dan waktu penerimaan
#   3. Memberi anchor waktu absolut tanpa bergantung pada RTC MCU
#
# Jalankan paralel dengan log.py di terminal terpisah.
# client_id berbeda ("..._02") agar broker tidak saling kick.
# SAVE_DIR berbeda agar file CSV tidak bentrok.
# ---------------------------------------------------------------------------

BROKER = socket.gethostbyname("broker.hivemq.com")
PORT   = 1883

# Dua topic: data mobil (current/tegangan/daya) dan data GPS (track).
# Sesuaikan namanya dengan yang dipakai publisher. Tiap topic otomatis
# disimpan ke CSV terpisah (falcon_current.csv, falcon_track.csv).
# Alternatif: ["falcon/#"] menangkap semua subtopic falcon apa pun namanya.
TOPICS = ["gabungan_datasensor", "race/falcon/gps"]

# Direktori terpisah agar tidak bentrok dengan log.py
SAVE_DIR         = "data/race_day/attempt_05/logTime"
NOT_JSON_SAVE_DIR = os.path.join(SAVE_DIR, "notJson")

# Offset WIB = UTC+7 (tanpa library pytz, pakai timedelta)
WIB_OFFSET = datetime.timezone(datetime.timedelta(hours=7))

# ---------------------------------------------------------------------------

def _now_wib() -> datetime.datetime:
    """Return current time in WIB (UTC+7)."""
    return datetime.datetime.now(tz=WIB_OFFSET)


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to MQTT Broker!")
        # QoS 1: at-least-once delivery, persistent session ensures no message
        # is lost even if this logger briefly disconnects.
        for t in TOPICS:
            client.subscribe(t, qos=1)
            print(f"Subscribed to topic: {t} with QoS 1")
    else:
        print(f"Failed to connect, return code {rc}")


def on_message(client, userdata, msg):
    payload = msg.payload.decode("utf-8")
    topic   = msg.topic

    # ----- Capture WIB receive-time FIRST, before any processing -----
    now_wib = _now_wib()
    received_at_wib   = now_wib.isoformat()           # e.g. 2026-07-13T23:18:57.123456+07:00
    received_date_wib = now_wib.strftime("%Y-%m-%d")  # e.g. 2026-07-13
    received_time_wib = now_wib.strftime("%H:%M:%S.%f")  # e.g. 23:18:57.123456

    print(f"[{received_time_wib} WIB] {topic}: {payload}")

    try:
        data = json.loads(payload)

        # Inject WIB timestamp columns BEFORE writing to CSV
        data["received_at_wib"]   = received_at_wib
        data["received_date_wib"] = received_date_wib
        data["received_time_wib"] = received_time_wib

        os.makedirs(SAVE_DIR, exist_ok=True)
        csv_file = os.path.join(SAVE_DIR, f"{topic.replace('/', '_')}.csv")

        file_exists = os.path.isfile(csv_file)

        headers = []
        # Read existing headers so new columns don't get lost on append
        if file_exists and os.path.getsize(csv_file) > 0:
            with open(csv_file, mode='r') as file:
                reader = csv.reader(file)
                try:
                    headers = next(reader)
                except StopIteration:
                    pass

        # First message: use JSON keys (+ injected WIB keys) as headers
        if not headers:
            headers = list(data.keys())

        with open(csv_file, mode='a', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=headers, extrasaction='ignore')

            if not file_exists or os.path.getsize(csv_file) == 0:
                writer.writeheader()

            # Write the data row. extrasaction='ignore' prevents errors if
            # the MCU sends unexpected new fields mid-session.
            writer.writerow(data)

            # Flush to disk immediately — prevent data loss on crash/disconnect
            file.flush()
            os.fsync(file.fileno())

    except json.JSONDecodeError:
        print(f"Warning: Payload on {topic} is not valid JSON. Saving to notJson folder.")
        os.makedirs(NOT_JSON_SAVE_DIR, exist_ok=True)
        not_json_file = os.path.join(NOT_JSON_SAVE_DIR, f"{topic.replace('/', '_')}_raw.csv")
        file_exists = os.path.isfile(not_json_file)
        with open(not_json_file, mode='a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=["received_at_wib", "topic", "raw_payload"])
            if not file_exists or os.path.getsize(not_json_file) == 0:
                writer.writeheader()
            writer.writerow({
                "received_at_wib": received_at_wib,
                "topic":           topic,
                "raw_payload":     payload,
            })
            f.flush()
            os.fsync(f.fileno())

    except Exception as e:
        print(f"Error writing to CSV for topic {topic}: {e}")


# ---------------------------------------------------------------------------
# Persistent session ("..._02") — DIFFERENT client_id from log.py ("..._01")
# so both can connect simultaneously without the broker kicking either one.
# ---------------------------------------------------------------------------
client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION1,
    client_id="falcon_logger_persistent_02",
    clean_session=False,
)
client.on_message = on_message
client.on_connect = on_connect

try:
    client.connect(BROKER, PORT, 60)
    client.loop_forever()
except KeyboardInterrupt:
    print("Disconnecting...")
    client.disconnect()


# USERNAME = "antasena"
# PASSWORD = "NANTI"
