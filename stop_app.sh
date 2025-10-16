#!/bin/bash
# Stop the HackRF-CEMA-UI Flask app using the PID stored in app.pid

if [ -f app.pid ]; then
    kill $(cat app.pid)
    rm app.pid
    echo "App stopped."
else
    echo "No app.pid file found. App may not be running."
fi
