#!/bin/bash

# Start Django server in the background
python loader-service/loader/manage.py runserver 0.0.0.0:8000 &

# Wait for Kafka to be ready
echo "[LOADER] Waiting for Kafka to be ready..."
sleep 30

# Start Kafka listener with retry logic
python -c "
import sys
import time
sys.path.insert(0, '/app/loader-service/loader')
sys.path.insert(0, '/app')

attempt = 1

while True:
    try:
        print(f'[LOADER] Starting listener (attempt {attempt})...')
        from engine.kafka_listener import start_listener
        start_listener()
        print('[LOADER] Listener stopped unexpectedly. Restarting in 10 seconds...')
    except Exception as e:
        print(f'[LOADER ERROR] Failed to connect: {e}')
    attempt += 1
    print('[LOADER] Retrying in 10 seconds...')
    time.sleep(10)
"

