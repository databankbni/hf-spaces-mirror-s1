import paho.mqtt.client as mqtt
import json
import csv
import os
import socket

BROKER = socket.gethostbyname("broker.hivemq.com")
PORT = 1883
# Dua topic: data mobil (current/tegangan/daya) dan data GPS (track).
# Sesuaikan namanya dengan yang dipakai publisher. Tiap topic otomatis
# disimpan ke CSV terpisah (falcon_current.csv, falcon_track.csv) — setelah
# sesi selesai gabungkan dengan merge_topics.py sebelum clean_telemetry.py.
# Alternatif: ["falcon/#"] menangkap semua subtopic falcon apa pun namanya.
TOPICS = ["falcon/current", "race/falcon/gps"]
SAVE_DIR = "data/race_day/attempt_01/qos0" # Directory to save the CSV files
NOT_JSON_SAVE_DIR = os.path.join(SAVE_DIR, "notJson") # Directory for non-JSON messages

def on_connect(client,userdata,flags,rc):
    if rc == 0:
        print("Connected to MQTT Broker!")
        # QoS 0 is fire-and-forget: fastest, but messages can be lost if we disconnect briefly
        for t in TOPICS:
            client.subscribe(t, qos=0)
            print(f"Subscribed to topic: {t} with QoS 0")
    else:
        print(f"Failed to connect, return code {rc}")

def on_message(client,userdata,msg):
    payload = msg.payload.decode("utf-8")
    topic = msg.topic
    print(f"Received message on topic {topic}: {payload}")

    try:
        # Parse JSON payload
        data = json.loads(payload)

        # Generate CSV filename dynamically based on the topic
        # e.g., 'falcon/data' -> 'data/raceday/falcon_data.csv'
        os.makedirs(SAVE_DIR, exist_ok=True)
        csv_file = os.path.join(SAVE_DIR, f"{topic.replace('/', '_')}.csv")

        file_exists = os.path.isfile(csv_file)

        headers = []
        # If the file already exists, read the existing headers from it
        if file_exists and os.path.getsize(csv_file) > 0:
            with open(csv_file, mode='r') as file:
                reader = csv.reader(file)
                try:
                    headers = next(reader)
                except StopIteration:
                    pass

        # If no headers found (e.g. new file), use the JSON keys as headers
        if not headers:
            headers = list(data.keys())

        # Append data to CSV
        with open(csv_file, mode='a', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=headers, extrasaction='ignore')

            if not file_exists or os.path.getsize(csv_file) == 0:
                writer.writeheader()

            # Write the data. If data is missing some keys, they will be empty.
            # extrasaction='ignore' prevents errors if data has new unexpected keys.
            writer.writerow(data)

            # Force write to disk immediately to prevent data loss on sudden disconnect/crash
            file.flush()
            os.fsync(file.fileno())

    except json.JSONDecodeError:
        print(f"Warning: Received payload on {topic} is not valid JSON. Saving to notJson folder.")
        import datetime
        os.makedirs(NOT_JSON_SAVE_DIR, exist_ok=True)
        not_json_file = os.path.join(NOT_JSON_SAVE_DIR, f"{topic.replace('/', '_')}_raw.csv")
        file_exists = os.path.isfile(not_json_file)
        with open(not_json_file, mode='a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "topic", "raw_payload"])
            if not file_exists or os.path.getsize(not_json_file) == 0:
                writer.writeheader()
            writer.writerow({
                "timestamp": datetime.datetime.now().isoformat(),
                "topic": topic,
                "raw_payload": payload
            })
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        print(f"Error writing to CSV for topic {topic}: {e}")

# clean_session=False has no queuing benefit at QoS 0 (broker never queues QoS 0 messages
# for offline clients), but a distinct client_id keeps this session separate from the QoS 1 logger.
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id="falcon_logger_persistent_01_qos0", clean_session=False)
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
