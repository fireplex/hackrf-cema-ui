# --- Production-ready Flask-SocketIO App for HackRF-CEMA-UI ---
import os
import signal
import subprocess
import json
import threading
import datetime
import numpy as np
from scipy.fft import fft
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit
from logging.config import dictConfig

# --- Logging Configuration ---
dictConfig({
    'version': 1,
    'formatters': {'default': {
        'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    }},
    'handlers': {'wsgi': {
        'class': 'logging.StreamHandler',
        'stream': 'ext://flask.logging.wsgi_errors_stream',
        'formatter': 'default'
    }},
    'root': {
        'level': 'INFO',
        'handlers': ['wsgi']
    }
})

# --- Flask App & SocketIO ---
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# --- Constants ---
SETTINGS_FILE_PATH = os.path.join(app.static_folder, 'settings.json')
BYTES_PER_SAMPLE = 2
DEFAULT_SAMPLE_RATE = 2_000_000

# --- Helper Functions ---
def get_latest_recording_file():
    import glob
    files = glob.glob('*.raw')
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]

def get_sample_rate():
    try:
        with open(SETTINGS_FILE_PATH, 'r') as f:
            settings = json.load(f)
            for section in ('recording', 'transmitting'):
                if section in settings and 'sampleRate' in settings[section]:
                    return int(settings[section]['sampleRate'])
    except Exception:
        pass
    return DEFAULT_SAMPLE_RATE

def get_recording_metadata():
    meta_path = os.path.join(os.path.dirname(__file__), 'recording_metadata.json')
    try:
        with open(meta_path, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def update_recording_metadata(filename, start_time=None, end_time=None, duration=None):
    meta_path = os.path.join(os.path.dirname(__file__), 'recording_metadata.json')
    meta = get_recording_metadata()
    if filename not in meta:
        meta[filename] = {}
    if start_time:
        meta[filename]['start_time'] = start_time
    if end_time:
        meta[filename]['end_time'] = end_time
    if duration is not None:
        meta[filename]['duration'] = duration
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)

def get_incremented_filename(filename):
    import glob
    base, ext = os.path.splitext(filename)
    pattern = f"{base}_*{ext}"
    existing = glob.glob(pattern)
    indices = [0] if os.path.exists(filename) else []
    for f in existing:
        try:
            idx = int(f[len(base)+1:-(len(ext))])
            indices.append(idx)
        except Exception:
            continue
    next_idx = max(indices) + 1 if indices else 0
    return filename if next_idx == 0 else f"{base}_{next_idx}{ext}"

# --- Global Process Handles ---
recording_process = None
transmit_process = None

# --- Socket.IO Events ---
@socketio.on('delete_files')
def socket_delete_files(data):
    files = data.get('files', [])
    deleted = []
    failed = []
    for fname in files:
        path = os.path.join(os.path.dirname(__file__), fname)
        try:
            if os.path.exists(path) and fname.endswith('.raw'):
                os.remove(path)
                deleted.append(fname)
            else:
                failed.append(fname)
        except Exception:
            failed.append(fname)
    msg = f"Deleted: {', '.join(deleted)}" if deleted else "No files deleted."
    if failed:
        msg += f" Failed: {', '.join(failed)}"
    socketio.emit('file_action_status', {"message": msg})
    notify_processed_files_update()

@socketio.on('rename_file')
def socket_rename_file(data):
    old_name = data.get('oldName')
    new_name = data.get('newName')
    if not old_name or not new_name or not old_name.endswith('.raw') or not new_name.endswith('.raw'):
        socketio.emit('file_action_status', {"message": "Invalid file name(s)."})
        return
    old_path = os.path.join(os.path.dirname(__file__), old_name)
    new_path = os.path.join(os.path.dirname(__file__), new_name)
    try:
        if os.path.exists(old_path) and not os.path.exists(new_path):
            os.rename(old_path, new_path)
            # Also rename metadata entry
            meta_path = os.path.join(os.path.dirname(__file__), 'recording_metadata.json')
            meta = get_recording_metadata()
            if old_name in meta:
                meta[new_name] = meta.pop(old_name)
                with open(meta_path, 'w') as f:
                    json.dump(meta, f, indent=2)
            msg = f"Renamed {old_name} to {new_name}."
        else:
            msg = "Rename failed: file does not exist or new name already exists."
    except Exception as e:
        msg = f"Rename failed: {str(e)}"
    socketio.emit('file_action_status', {"message": msg})
    notify_processed_files_update()
    
@socketio.on('request_spectrum')
def socket_request_spectrum():
    latest_file = get_latest_recording_file()
    if not latest_file or not os.path.exists(latest_file):
        emit('spectrum_update', {'spectrum': [], 'info': 'No recording file found.'})
        return
    try:
        chunk_size = 4096 * 2
        file_size = os.path.getsize(latest_file)
        if file_size < chunk_size:
            emit('spectrum_update', {'spectrum': [], 'info': 'Not enough data in file.'})
            return
        with open(latest_file, 'rb') as f:
            f.seek(file_size - chunk_size)
            raw = f.read(chunk_size)
        samples = np.frombuffer(raw, dtype=np.int16)
        spectrum = np.abs(fft(samples))[:len(samples)//2]
        spectrum = spectrum / np.max(spectrum)
        spectrum = spectrum.tolist()
        emit('spectrum_update', {'spectrum': spectrum, 'info': f'File: {latest_file} | Samples: {len(samples)}'})
    except Exception as e:
        emit('spectrum_update', {'spectrum': [], 'info': f'Error: {str(e)}'})

@socketio.on('query_recording_status')
def socket_query_recording_status():
    global recording_process
    running = recording_process is not None and recording_process.poll() is None
    emit('recording_status', {'running': running})

@socketio.on('start_record')
def socket_start_recording(data):
    global recording_process
    try:
        with open(SETTINGS_FILE_PATH, 'r') as f:
            settings = json.load(f)
        rx_sn = settings.get('hackrfRxSN')
        if not rx_sn:
            emit('recording_status', {"error": "No receiver (Rx) device selected in settings."})
            return
    except Exception:
        emit('recording_status', {"error": "Settings file not found or is invalid."})
        return
    base_filename = settings.get('recording', {}).get('outputFile', 'output.raw')
    output_filename = get_incremented_filename(base_filename)
    start_time = datetime.datetime.now(datetime.UTC).isoformat() + 'Z'
    update_recording_metadata(output_filename, start_time=start_time)
    if recording_process and recording_process.poll() is None:
        emit('recording_status', {"error": "A recording is already in progress."})
        return
    frequency = settings.get('recording', {}).get('frequency', 101100000)
    lna_gain = settings.get('recording', {}).get('lnaGain', 20)
    vga_gain = settings.get('recording', {}).get('vgaGain', 28)
    squelch_enabled = settings.get('recording', {}).get('squelchEnabled', False)
    if squelch_enabled:
        pipeline = (
            f"sudo hackrf_transfer -r {output_filename} -f {frequency} -s 2000000 -d {rx_sn}"
        )
        try:
            recording_process = subprocess.Popen(
                pipeline,
                shell=True,
                start_new_session=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
        except Exception as e:
            print(f"Failed to start pipeline: {e}")
    else:
        command = [
            'sudo', 'hackrf_transfer', '-r', output_filename,
            '-f', str(frequency), '-l', str(lna_gain), '-g', str(vga_gain), '-d', str(rx_sn)
        ]
        try:
            recording_process = subprocess.Popen(
                command,
                start_new_session=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
        except Exception as e:
            print(f"Failed to start process: {e}")

    emit('recording_status', {"message": f"Recording started. Saving to {output_filename}."})

    # --- Monitor hackrf_transfer stdout and stderr ---
    def monitor_recording_output():
        global recording_process
        if not recording_process:
            return
        # Read both stdout and stderr
        def stream(pipe, is_err=False):
            while True:
                line = pipe.readline()
                if not line:
                    break
                try:
                    decoded = line.decode('utf-8', errors='ignore')
                except Exception:
                    decoded = str(line)
                if is_err and "Couldn't transfer any bytes for one second" in decoded:
                    socketio.emit('recording_status', {"error": "Recording error: Couldn't transfer any bytes for one second."})
                    # Stop the process and reset state
                    try:
                        if recording_process.poll() is None:
                            os.killpg(recording_process.pid, signal.SIGINT)
                    except Exception:
                        pass
                    finally:
                        recording_process = None
                    # Notify frontend to reset buttons
                    socketio.emit('recording_status', {"running": False})
                    break
                socketio.emit('recording_status', {"message": decoded})

        if recording_process.stdout:
            threading.Thread(target=stream, args=(recording_process.stdout, False), daemon=True).start()
        if recording_process.stderr:
            threading.Thread(target=stream, args=(recording_process.stderr, True), daemon=True).start()

    monitor_recording_output()

    # --- Live energy threshold speech detection thread ---
    def speech_energy_monitor():
        import time
        threshold = 5000  # Adjust this value for sensitivity
        chunk_size = 4096 * 2
        while recording_process and recording_process.poll() is None:
            try:
                if os.path.exists(output_filename) and os.path.getsize(output_filename) >= chunk_size:
                    with open(output_filename, 'rb') as f:
                        f.seek(-chunk_size, os.SEEK_END)
                        raw = f.read(chunk_size)
                    samples = np.frombuffer(raw, dtype=np.int16)
                    energy = np.mean(np.abs(samples))
                    if energy > threshold:
                        socketio.emit('speech_energy', {'energy': float(energy), 'detected': True})
                    else:
                        socketio.emit('speech_energy', {'energy': float(energy), 'detected': False})
            except Exception as e:
                pass
            time.sleep(1)
    threading.Thread(target=speech_energy_monitor, daemon=True).start()

@socketio.on('stop_recording')
def socket_stop_recording():
    global recording_process
    meta = get_recording_metadata()
    latest_file = get_latest_recording_file()
    if latest_file and latest_file in meta and 'start_time' in meta[latest_file]:
        stop_time = datetime.datetime.utcnow().isoformat() + 'Z'
        start_time = meta[latest_file]['start_time']
        # Remove timezone info to make both naive
        t1 = datetime.datetime.fromisoformat(start_time.replace('Z',''))
        t2 = datetime.datetime.fromisoformat(stop_time.replace('Z',''))
        if t1.tzinfo is not None:
            t1 = t1.replace(tzinfo=None)
        if t2.tzinfo is not None:
            t2 = t2.replace(tzinfo=None)
        duration = (t2 - t1).total_seconds()
        update_recording_metadata(latest_file, end_time=stop_time, duration=duration)
    if recording_process is None or recording_process.poll() is not None:
        emit('recording_status', {"error": "No active recording process to stop."})
        return
    try:
        os.killpg(recording_process.pid, signal.SIGINT)
        try:
            recording_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            recording_process.kill()
    except Exception as e:
        emit('recording_status', {"error": f"An error occurred while stopping the process: {str(e)}"})
        return
    finally:
        recording_process = None
    emit('recording_status', {"message": "Recording stopped successfully."})
    notify_processed_files_update()

@socketio.on('save_settings')
def socket_save_settings(data):
    new_settings = data
    if not new_settings:
        emit('settings_status', {"status": "error", "message": "No data received"})
        return
    try:
        try:
            with open(SETTINGS_FILE_PATH, 'r') as f:
                settings = json.load(f)
        except Exception:
            settings = {}
        settings.update(new_settings)
        with open(SETTINGS_FILE_PATH, 'w') as f:
            json.dump(settings, f, indent=4)
        emit('settings_status', {"status": "success", "message": "Settings saved successfully!"})
    except Exception as e:
        emit('settings_status', {"status": "error", "message": str(e)})

@socketio.on('start_transmit')
def socket_start_transmit(data):
    global transmit_process
    try:
        with open(SETTINGS_FILE_PATH, 'r') as f:
            settings = json.load(f)
        tx_sn = settings.get('hackrfTxSN')
        if not tx_sn:
            emit('transmit_status', {"error": "No transmitter (Tx) device selected in settings."})
            return
    except Exception:
        emit('transmit_status', {"error": "Settings file not found or is invalid."})
        return
    input_filename = settings.get('transmitting', {}).get('inputFile', 'input.wav')
    if not os.path.exists(input_filename):
        emit('transmit_status', {"error": f"Input file does not exist: {input_filename}"})
        return
    frequency = settings.get('transmitting', {}).get('frequency', 101100000)
    tx_gain = settings.get('transmitting', {}).get('txGain', 40)
    repeat = settings.get('transmitting', {}).get('repeat', False)
    command = [
        'sudo', 'hackrf_transfer', '-t', str(input_filename),
        '-f', str(frequency), '-x', str(tx_gain), '-d', str(tx_sn)
    ]
    if repeat:
        command.append('-R')
    def monitor_transmit(proc):
        proc.wait()
        socketio.emit('transmit_status', {"message": "Transmission finished."})
    try:
        transmit_process = subprocess.Popen(command)
        emit('transmit_status', {"message": f"Transmission started from {input_filename}."})
        threading.Thread(target=monitor_transmit, args=(transmit_process,), daemon=True).start()
    except Exception as e:
        emit('transmit_status', {"error": f"Failed to start process: {str(e)}"})
        
@socketio.on('stop_transmit')
def socket_stop_transmit():
    global transmit_process
    if transmit_process is None or transmit_process.poll() is not None:
        emit('transmit_status', {"error": "No active transmit process to stop."})
        return
    try:
        # Try to send SIGINT to the process only if running
        try:
            os.kill(transmit_process.pid, signal.SIGINT)
        except ProcessLookupError:
            pass  # Process already exited
        try:
            transmit_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            transmit_process.kill()
    except Exception as e:
        emit('transmit_status', {"error": f"An error occurred while stopping transmit: {str(e)}"})
        return
    finally:
        transmit_process = None
    emit('transmit_status', {"message": "Transmit stopped successfully."})

@socketio.on('update_transmit_input')
def socket_update_transmit_input(data):
    input_file = data.get('inputFile')
    if not input_file:
        emit('transmit_input_status', {'error': 'No input file provided'})
        return
    try:
        with open(SETTINGS_FILE_PATH, 'r') as f:
            settings = json.load(f)
        if 'transmitting' not in settings:
            settings['transmitting'] = {}
        settings['transmitting']['inputFile'] = input_file
        with open(SETTINGS_FILE_PATH, 'w') as f:
            json.dump(settings, f, indent=4)
        emit('transmit_input_status', {'status': 'success'})
    except Exception as e:
        emit('transmit_input_status', {'error': str(e)})

@socketio.on('request_processed_files')
def socket_request_processed_files():
    notify_processed_files_update()

# --- Helper: Notify Processed Files Update ---
def notify_processed_files_update():
    import glob
    files = glob.glob(os.path.join(os.path.dirname(__file__), '*.raw'))
    meta = get_recording_metadata()
    file_objs = []
    for f in files:
        stat = os.stat(f)
        name = os.path.basename(f)
        size_kb = stat.st_size // 1024
        info = meta.get(name, {})
        file_objs.append({
            'name': name,
            'type': 'raw',
            'size_kb': size_kb,
            'start_time': info.get('start_time', '-'),
            'end_time': info.get('end_time', '-'),
            'duration': info.get('duration', '-')
        })
    socketio.emit('processed_files_update', {'files': file_objs})

# --- Flask Routes ---
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/files')
def files_page():
    import glob
    filepaths = glob.glob(os.path.join(os.path.dirname(__file__), '*.raw'))
    files = []
    meta = get_recording_metadata()
    sample_rate = get_sample_rate()
    for path in filepaths:
        name = os.path.basename(path)
        size_bytes = os.path.getsize(path)
        size_kb = round(size_bytes / 1024, 2)
        ftype = 'Processed' if '_processed' in name else 'Raw'
        start_time = end_time = duration_str = None
        if name in meta:
            start_time = meta[name].get('start_time')
            end_time = meta[name].get('end_time')
            duration = meta[name].get('duration')
            if duration is not None:
                if duration < 60:
                    duration_str = f"{duration:.3f} s"
                else:
                    mins = int(duration // 60)
                    secs = duration % 60
                    duration_str = f"{mins}:{secs:06.3f} min"
        if duration_str is None:
            duration_sec = size_bytes / (BYTES_PER_SAMPLE * sample_rate)
            if duration_sec < 60:
                duration_str = f"{duration_sec:.3f} s"
            else:
                mins = int(duration_sec // 60)
                secs = duration_sec % 60
                duration_str = f"{mins}:{secs:06.3f} min"
        files.append({
            'name': name,
            'type': ftype,
            'size_kb': size_kb,
            'duration': duration_str,
            'start_time': start_time,
            'end_time': end_time
        })
    return render_template('files.html', files=files)

@app.route('/settings')
def settings():
    return render_template('settings.html')


@app.route('/api/transmit-status', methods=['GET'])
def transmit_status():
    global transmit_process
    running = transmit_process and transmit_process.poll() is None
    return jsonify({"running": running})


@app.route('/api/hackrf-info')
def run_command():
    command = ["sudo", "hackrf_info"]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True
        )
        return jsonify({'status': 'success', 'output': result.stdout})
    except subprocess.CalledProcessError as e:
        return jsonify({'status': 'error', 'output': e.stderr}), 500
    except FileNotFoundError:
        return jsonify({'status': 'error', 'output': 'Command not found.'}), 404

@app.route('/api/processed-files', methods=['GET'])
def list_processed_files():
    import glob
    files = glob.glob(os.path.join(os.path.dirname(__file__), '*.raw'))
    files = [os.path.basename(f) for f in files]
    return jsonify({'files': files})

# --- Main Entrypoint ---
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8080, debug=False, allow_unsafe_werkzeug=True)
