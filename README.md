# HackRF-CEMA-UI Web Interface

A modern web-based user interface for controlling HackRF SDR devices, recording and transmitting IQ data, and managing SDR files. Built with Flask, Flask-SocketIO, and Bootstrap for a responsive, real-time SDR experience.

## Features

- **Device Control:** Start/stop HackRF recordings and transmissions from your browser.
- **Settings Management:** Configure frequency, gain, squelch, and more via the web UI.
- **Live Spectrum Display:** Real-time FFT spectrum and waterfall visualization of incoming SDR data.
- **File Management:** View, select, and manage all `.raw` SDR files, including file size, type, timestamps and duration.
- **Socket.IO Events:** All actions are event-driven for instant feedback and robust error handling.
- **Responsive UI:** Built with Bootstrap for desktop and mobile use.

## Installation (Debian CLI)


1. **Install System Dependencies:**

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip hackrf sox
```


```bash
git clone https://github.com/fireplex/hackrf-cema-ui.git
cd hackrf-cema-ui
chmod +x start_app.sh stop_app.sh  # Make shell scripts executable
```

3. **Set Up Python Virtual Environment:**

```bash
python3 -m venv venv
source venv/bin/activate
```


4. **Install Python Dependencies:**

```bash
pip install flask flask-socketio numpy scipy requests eventlet
```


5. **Create Default Settings File:**

Copy the default settings template and edit it to add your HackRF serial numbers and desired file names:

```bash
cp static/settings.default.json static/settings.json
# Ensure you set your hackrfRxSN and hackrfTxSN values in the Web UI
```


6. **Run/Stop the Web UI (Recommended):**

To run the app in the background and keep it running after closing your SSH session, use the provided shell scripts:

```bash
chmod +x start_app.sh stop_app.sh  # (first time only)
./start_app.sh                    # Start the app in the background
./stop_app.sh                     # Stop the app
```

The app will log output to `start_app.log` and store its process ID in `app.pid`.

7. **Access the UI:**

Open your browser and go to: https://your-ip:8080

## Usage

- **Home:** Control HackRF, start/stop recording, start/stop transmitting, view live spectrum.
- **Settings:** Configure device S/Ns
- **Files:** View all `.raw` files, with type, size, timestamps and duration as well as delete them.

## Notes
- Requires HackRF hardware and drivers.
- Run as a user with permission to access HackRF USB devices (or use `sudo`).
- For remote access, adjust the `host` in `app.py` as needed.

## License
MIT
