#!/bin/bash
# Start the HackRF-CEMA-UI Flask app in the background, logging output to start_app.log

nohup venv/bin/python3 app.py > start_app.log 2>&1 &
echo $! > app.pid
echo "App started. PID: $(cat app.pid)"
