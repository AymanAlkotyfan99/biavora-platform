#!/bin/bash

# Start Django server in the background
python metadata-service/metadata/manage.py runserver 0.0.0.0:8000 &

# Wait for Kafka to be ready
echo "[METADATA] Waiting for Kafka to be ready..."
sleep 30

# Start Kafka listener with retry logic
python -c "
import sys
import time
sys.path.insert(0, '/app/metadata-service/metadata')
sys.path.insert(0, '/app')

attempt = 1

while True:
    try:
        print(f'[METADATA] Starting listener (attempt {attempt})...')
        from api.kafka_listener import start_listener
        start_listener()
        print('[METADATA] Listener stopped unexpectedly. Restarting in 10 seconds...')
    except Exception as e:
        print(f'[METADATA ERROR] Failed to connect: {e}')
    attempt += 1
    print('[METADATA] Retrying in 10 seconds...')
    time.sleep(10)
"

