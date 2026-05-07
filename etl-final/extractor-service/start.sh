#!/bin/bash

# Start Django server in the background
python extractor-service/extractor/manage.py runserver 0.0.0.0:8000 &

# Wait for Kafka to be ready
echo "[EXTRACTOR] Waiting for Kafka to be ready..."
sleep 30

# Start Kafka listener with retry logic
python -c "
import sys
import time
sys.path.insert(0, '/app/extractor-service/extractor')
sys.path.insert(0, '/app')

attempt = 1

while True:
    try:
        print(f'[EXTRACTOR] Starting listener (attempt {attempt})...')
        from engine.kafka_listener import start_listener
        start_listener()
        print('[EXTRACTOR] Listener stopped unexpectedly. Restarting in 10 seconds...')
    except Exception as e:
        print(f'[EXTRACTOR ERROR] Failed to connect: {e}')
    attempt += 1
    print('[EXTRACTOR] Retrying in 10 seconds...')
    time.sleep(10)
"

