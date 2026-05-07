#!/bin/bash

# Start Django server in background
python detector-service/detector/manage.py runserver 0.0.0.0:8000 &

echo "[DETECTOR] Waiting for Kafka to be ready..."
sleep 30

python -c "
import sys
import time

sys.path.insert(0, '/app/detector-service/detector')
sys.path.insert(0, '/app')

attempt = 1

while True:
    try:
        print(f'[DETECTOR] Starting listener (attempt {attempt})')
        from core.kafka_listener import start_listener
        start_listener()
        print('[DETECTOR] Listener stopped unexpectedly. Restarting in 10 seconds...')
    except Exception as e:
        print(f'[DETECTOR ERROR] Kafka not ready: {e}')
    attempt += 1
    time.sleep(10)

"
