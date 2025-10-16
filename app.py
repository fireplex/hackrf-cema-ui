
import os
import datetime
import numpy as np
from scipy.fft import fft
from flask_socketio import SocketIO, emit

socketio = SocketIO(cors_allowed_origins="*")

# Helper to get latest recording file
def get_latest_recording_file():
    import glob
    files = glob.glob('*.raw')
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]

# Socket.IO event to emit spectrum data
@socketio.on('request_spectrum')
def socket_request_spectrum():
    latest_file = get_latest_recording_file()
    if not latest_file or not os.path.exists(latest_file):
        emit('spectrum_update', {'spectrum': [], 'info': 'No recording file found.'})
        return
    try:
        # Read the last chunk of samples (e.g., last 4096 samples)
        chunk_size = 4096 * 2  # 16-bit samples
        file_size = os.path.getsize(latest_file)
        if file_size < chunk_size:
            emit('spectrum_update', {'spectrum': [], 'info': 'Not enough data in file.'})
            return
        with open(latest_file, 'rb') as f:
            f.seek(file_size - chunk_size)
            raw = f.read(chunk_size)
        samples = np.frombuffer(raw, dtype=np.int16)
        # Compute FFT
        spectrum = np.abs(fft(samples))[:len(samples)//2]
        spectrum = spectrum / np.max(spectrum)
        spectrum = spectrum.tolist()
        emit('spectrum_update', {'spectrum': spectrum, 'info': f'File: {latest_file} | Samples: {len(samples)}'})
    except Exception as e:
        emit('spectrum_update', {'spectrum': [], 'info': f'Error: {str(e)}'})
import signal
import subprocess
import json
import threading
from flask import Flask, jsonify, render_template, request, send_from_directory
from logging.config import dictConfig
from recording_watcher import watch_recordings

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

# Initialize the Flask application
app = Flask(__name__)
socketio.init_app(app, cors_allowed_origins="*")

# Route to delete a selected .raw file and its metadata
@app.route('/delete-file', methods=['POST'])
def delete_file():
    filename = request.form.get('filename')
    if not filename:
        return "No file selected", 400
    # Delete the .raw file
    file_path = os.path.join(os.path.dirname(__file__), filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    # Delete metadata if present
    meta_path = os.path.join(os.path.dirname(__file__), 'recording_metadata.json')
    try:
        if os.path.exists(meta_path):
            with open(meta_path, 'r') as f:
                meta = json.load(f)
            if filename in meta:
                del meta[filename]
                with open(meta_path, 'w') as f:
                    json.dump(meta, f, indent=2)
    except Exception as e:
        print(f"Failed to update metadata on delete: {e}")
    # Rebuild the files list for rendering (duplicate logic from files_page)
    import glob
    filepaths = glob.glob(os.path.join(os.path.dirname(__file__), '*.raw'))
    files = []
    BYTES_PER_SAMPLE = 2
    settings_sample_rate = None
    try:
        with open(SETTINGS_FILE_PATH, 'r') as f:
            settings = json.load(f)
            for section in ('recording', 'transmitting'):
                if section in settings and 'sampleRate' in settings[section]:
                    try:
                        settings_sample_rate = int(settings[section]['sampleRate'])
                        break
                    except Exception:
                        continue
    except Exception:
        pass
    DEFAULT_SAMPLE_RATE = 2_000_000
    meta_path = os.path.join(os.path.dirname(__file__), 'recording_metadata.json')
    try:
        with open(meta_path, 'r') as f:
            meta = json.load(f)
    except Exception:
        meta = {}
    for path in filepaths:
        name = os.path.basename(path)
        size_bytes = os.path.getsize(path)
        size_kb = round(size_bytes / 1024, 2)
        if '_processed' in name:
            ftype = 'Processed'
        else:
            ftype = 'Raw'
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
            sample_rate = settings_sample_rate or DEFAULT_SAMPLE_RATE
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

# Global variable to hold the recording process object
recording_process = None

# Socket.IO event to check if a recording is running
@socketio.on('query_recording_status')
def socket_query_recording_status():
    global recording_process
    running = recording_process is not None and recording_process.poll() is None
    emit('recording_status', {'running': running})

# Route to serve the main web page (index.html)
@app.route('/')
def home():
    # render_template looks for files in a 'templates' folder
    return render_template('index.html')

# Route to display all saved .raw files in a formatted table
@app.route('/files')
def files_page():
    import glob
    filepaths = glob.glob(os.path.join(os.path.dirname(__file__), '*.raw'))
    files = []
    # HackRF default: 8-bit I/Q interleaved, so 2 bytes per sample (I then Q)
    BYTES_PER_SAMPLE = 2  # 8-bit I/Q = 2 bytes/sample; for 16-bit I/Q use 4
    # Try to load sample rate from settings.json if available
    settings_sample_rate = None
    try:
        with open(SETTINGS_FILE_PATH, 'r') as f:
            settings = json.load(f)
            # Try to get sample rate from recording or transmitting section
            settings_sample_rate = None
            for section in ('recording', 'transmitting'):
                if section in settings and 'sampleRate' in settings[section]:
                    try:
                        settings_sample_rate = int(settings[section]['sampleRate'])
                        break
                    except Exception:
                        continue
    except Exception:
        pass
    DEFAULT_SAMPLE_RATE = 2_000_000
    meta_path = os.path.join(os.path.dirname(__file__), 'recording_metadata.json')
    try:
        with open(meta_path, 'r') as f:
            meta = json.load(f)
    except Exception:
        meta = {}
    for path in filepaths:
        name = os.path.basename(path)
        size_bytes = os.path.getsize(path)
        size_kb = round(size_bytes / 1024, 2)
        # Type: processed/raw based on filename
        if '_processed' in name:
            ftype = 'Processed'
        else:
            ftype = 'Raw'
        # Use metadata if available
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
            # fallback: estimate duration as before
            sample_rate = settings_sample_rate or DEFAULT_SAMPLE_RATE
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

@socketio.on('start_record')
def socket_start_recording(data):
    import datetime
    # Read the selected Rx device from settings
    try:
        with open(SETTINGS_FILE_PATH, 'r') as f:
            settings = json.load(f)
        rx_sn = settings.get('hackrfRxSN')
        if not rx_sn:
            emit('recording_status', {"error": "No receiver (Rx) device selected in settings."})
            return
    except (FileNotFoundError, json.JSONDecodeError):
        emit('recording_status', {"error": "Settings file not found or is invalid."})
        return

    # Define the command to run with sudo
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
        if next_idx == 0:
            return filename
        else:
            return f"{base}_{next_idx}{ext}"

    base_filename = settings.get('recording', {}).get('outputFile', 'output.raw')
    output_filename = get_incremented_filename(base_filename)

    # Record start time in metadata (now that output_filename is known)
    start_time = datetime.datetime.utcnow().isoformat() + 'Z'
    meta_path = os.path.join(os.path.dirname(__file__), 'recording_metadata.json')
    try:
        if os.path.exists(meta_path):
            with open(meta_path, 'r') as f:
                meta = json.load(f)
        else:
            meta = {}
        meta[output_filename] = {"start_time": start_time}
        with open(meta_path, 'w') as f:
            json.dump(meta, f, indent=2)
    except Exception as e:
        print(f"Failed to write recording metadata: {e}")
    """Starts a hackrf_transfer recording process."""
    global recording_process
    if recording_process and recording_process.poll() is None:
        emit('recording_status', {"error": "A recording is already in progress."})
        return

    # Read the selected Rx device from settings
    try:
        with open(SETTINGS_FILE_PATH, 'r') as f:
            settings = json.load(f)
        rx_sn = settings.get('hackrfRxSN')
        if not rx_sn:
            emit('recording_status', {"error": "No receiver (Rx) device selected in settings."})
            return
    except (FileNotFoundError, json.JSONDecodeError):
        emit('recording_status', {"error": "Settings file not found or is invalid."})
        return


    # Define the command to run with sudo
    def get_incremented_filename(filename):
        import glob
        base, ext = os.path.splitext(filename)
        pattern = f"{base}_*{ext}"
        existing = glob.glob(pattern)
        # Also check the base file itself
        indices = [0] if os.path.exists(filename) else []
        for f in existing:
            try:
                idx = int(f[len(base)+1:-(len(ext))])
                indices.append(idx)
            except Exception:
                continue
        next_idx = max(indices) + 1 if indices else 0
        if next_idx == 0:
            return filename
        else:
            return f"{base}_{next_idx}{ext}"

    base_filename = settings.get('recording', {}).get('outputFile', 'output.raw')
    output_filename = get_incremented_filename(base_filename)
    frequency = settings.get('recording', {}).get('frequency', 101100000) # Default to 101.1 MHz
    lna_gain = settings.get('recording', {}).get('lnaGain', 20) # Default LNA gain
    vga_gain = settings.get('recording', {}).get('vgaGain', 28) # Default VGA gain
    squelch_enabled = settings.get('recording', {}).get('squelchEnabled', False)
    # squelch_threshold = settings.get('recording', {}).get('squelchThreshold', '-10')

    if squelch_enabled:
        # Only save the raw output; processing is handled by the watcher
        pipeline = (
            f"sudo hackrf_transfer -r {output_filename} -f {frequency} -s 2000000 -d {rx_sn}"
        )
        print(f"Starting recording with pipeline: {pipeline}")
        try:
            recording_process = subprocess.Popen(pipeline, shell=True, start_new_session=True)
        except Exception as e:
            print(f"Failed to start pipeline: {e}")
    else:
        command = [
            'sudo',
            'hackrf_transfer',
            '-r', output_filename,
            '-f', frequency,
            '-l', lna_gain,
            '-g', vga_gain,
            '-d', rx_sn
        ]
        print(f"Starting recording with command: {' '.join(str(x) for x in command)}")
        try:
            recording_process = subprocess.Popen(command, start_new_session=True)
        except Exception as e:
            print(f"Failed to start process: {e}")

    emit('recording_status', {"message": f"Recording started. Saving to {output_filename}."})

@socketio.on('stop_recording')
def socket_stop_recording():
    import datetime
    # Record stop time and duration in metadata
    meta_path = os.path.join(os.path.dirname(__file__), 'recording_metadata.json')
    try:
        if os.path.exists(meta_path):
            with open(meta_path, 'r') as f:
                meta = json.load(f)
        else:
            meta = {}
        # Find the most recent file (should match the one just recorded)
        latest_file = get_latest_recording_file()
        if latest_file and latest_file in meta and 'start_time' in meta[latest_file]:
            stop_time = datetime.datetime.utcnow().isoformat() + 'Z'
            start_time = meta[latest_file]['start_time']
            # Calculate duration in seconds
            t1 = datetime.datetime.fromisoformat(start_time.replace('Z',''))
            t2 = datetime.datetime.fromisoformat(stop_time.replace('Z',''))
            duration = (t2 - t1).total_seconds()
            meta[latest_file]['end_time'] = stop_time
            meta[latest_file]['duration'] = duration
            with open(meta_path, 'w') as f:
                json.dump(meta, f, indent=2)
    except Exception as e:
        print(f"Failed to update recording metadata: {e}")
    """Stops the currently running hackrf_transfer process."""
    import signal
    import datetime
    global recording_process
    if recording_process is None or recording_process.poll() is not None:
        emit('recording_status', {"error": "No active recording process to stop."})
        return
    try:
        print("Sending SIGINT to process group to stop recording...")
        os.killpg(recording_process.pid, signal.SIGINT)
        try:
            recording_process.wait(timeout=5) # Wait up to 5 seconds for it to terminate
            print("Recording process group terminated.")
        except subprocess.TimeoutExpired:
            print("Process group did not terminate gracefully, killing it.")
            recording_process.kill() # Force kill if it doesn't respond
    except Exception as e:
        emit('recording_status', {"error": f"An error occurred while stopping the process: {str(e)}"})
        return
    finally:
        recording_process = None
    emit('recording_status', {"message": "Recording stopped successfully."})
    # Emit updated file list for transmit selector
    notify_processed_files_update()

# Define the path to the settings file within the static folder
SETTINGS_FILE_PATH = os.path.join(app.static_folder, 'settings.json')

@socketio.on('save_settings')
def socket_save_settings(data):
    """Receives form data as JSON and saves it to a file."""
    
    # Get the JSON data sent from the frontend
    new_settings = data
    if not new_settings:
        emit('settings_status', {"status": "error", "message": "No data received"})
        return

    try:
        # Try to read existing settings
        try:
            with open(SETTINGS_FILE_PATH, 'r') as f:
                settings = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # If the file doesn't exist or is empty, start with an empty dictionary
            settings = {}
        # Update existing settings with the new data
        settings.update(new_settings)
        # Write the updated settings back to the file
        with open(SETTINGS_FILE_PATH, 'w') as f:
            json.dump(settings, f, indent=4)
        print(f"Settings saved successfully: {settings}")
        emit('settings_status', {"status": "success", "message": "Settings saved successfully!"})
    except Exception as e:
        print(f"Error saving settings: {e}")
        emit('settings_status', {"status": "error", "message": str(e)})
    
transmit_process = None  # Global variable to hold the transmit process object

@socketio.on('start_transmit')
def socket_start_transmit(data):
    print('[SocketIO] Received start_transmit event')
    """Starts a hackrf_transfer transmitting process."""
    # Accept empty or missing JSON body; all parameters are loaded from settings.json

    # Read the selected Tx device from settings
    try:
        with open(SETTINGS_FILE_PATH, 'r') as f:
            settings = json.load(f)
        tx_sn = settings.get('hackrfTxSN')
        if not tx_sn:
            emit('transmit_status', {"error": "No transmitter (Tx) device selected in settings."})
            return
    except (FileNotFoundError, json.JSONDecodeError):
        emit('transmit_status', {"error": "Settings file not found or is invalid."})
        return

    # Define the command to run with sudo
    input_filename = settings.get('transmitting', {}).get('inputFile', 'input.wav')
    # If the input file is transmission.raw or a similar default, increment to avoid overwrite
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
        if next_idx == 0:
            return filename
        else:
            return f"{base}_{next_idx}{ext}"

    # Use the exact file selected in the UI (do not increment)
    # Only transmit if the file exists
    if not os.path.exists(input_filename):
        emit('transmit_status', {"error": f"Input file does not exist: {input_filename}"})
        return
    frequency = settings.get('transmitting', {}).get('frequency', 101100000) # Default to 101.1 MHz
    tx_gain = settings.get('transmitting', {}).get('txGain', 40) # Default TX gain
    repeat = settings.get('transmitting', {}).get('repeat', False) # Default to not repeat
    command = [
        'sudo',
        'hackrf_transfer',
        '-t', str(input_filename),
        '-f', str(frequency),
        '-x', str(tx_gain),
        '-d', str(tx_sn)
    ]
    if repeat:
        command.append('-R')

    global transmit_process
    import threading
    def monitor_transmit(proc):
        proc.wait()
        socketio.emit('transmit_status', {"message": "Transmission finished."})

    try:
        transmit_process = subprocess.Popen(command)
        emit('transmit_status', {"message": f"Transmission started from {input_filename}."})
        # Start a thread to monitor when the process finishes
        threading.Thread(target=monitor_transmit, args=(transmit_process,), daemon=True).start()
    except FileNotFoundError:
        emit('transmit_status', {"error": "'hackrf_transfer' command not found. Is it in your system's PATH?"})
    except Exception as e:
        emit('transmit_status', {"error": f"Failed to start process: {str(e)}"})
    
@socketio.on('stop_transmit')
def socket_stop_transmit():
    print('[SocketIO] Received stop_transmit event')
    """Stops all running hackrf_transfer transmitting processes."""
    global transmit_process
    try:
        subprocess.run(['sudo', 'pkill', '-f', 'hackrf_transfer -t'], check=True)
        if transmit_process:
            transmit_process = None
        emit('transmit_status', {"message": "All transmissions stopped successfully."})
    except subprocess.CalledProcessError as e:
        emit('transmit_status', {"error": f"Failed to stop transmissions: {str(e)}"})

# Transmit status endpoint for polling
@app.route('/api/transmit-status', methods=['GET'])
def transmit_status():
    global transmit_process
    running = False
    if transmit_process and transmit_process.poll() is None:
        running = True
    return jsonify({"running": running})

# Route to the settings.html page
@app.route('/settings')
def settings():
    return render_template('settings.html')

@app.route('/api/update-settings', methods=['POST'])
def update_settings():
    """
    API endpoint to update the settings.json file.
    Expects a JSON payload with 'hackrfRxSN' and 'hackrfTxSN'.
    """
    # --- 1. Get and Validate Incoming Data ---
    # Ensure the request contains JSON data
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request: No JSON payload found."}), 400

    # Ensure the required keys are in the JSON payload
    rx_sn = data.get('hackrfRxSN')
    tx_sn = data.get('hackrfTxSN')
    if not rx_sn or not tx_sn:
        return jsonify({"error": "Invalid request: Missing 'hackrfRxSN' or 'hackrfTxSN'."}), 400

    # --- 2. Read Existing Settings ---
    current_settings = {}
    try:
        # If settings.json exists, load its content
        if os.path.exists(SETTINGS_FILE_PATH):
            with open(SETTINGS_FILE_PATH, 'r') as f:
                current_settings = json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        # Handle cases where the file is corrupt or unreadable
        print(f"Error reading settings.json: {e}")
        return jsonify({"error": "Could not read existing settings file."}), 500

    # --- 3. Update and Write New Settings ---
    # Update the dictionary with the new values from the request
    current_settings['hackrfRxSN'] = rx_sn
    current_settings['hackrfTxSN'] = tx_sn

    try:
        # Write the updated dictionary back to the file with pretty printing
        with open(SETTINGS_FILE_PATH, 'w') as f:
            json.dump(current_settings, f, indent=4)
    except IOError as e:
        # Handle cases where the file cannot be written
        print(f"Error writing to settings.json: {e}")
        return jsonify({"error": "Could not save new settings."}), 500
        
    # --- 4. Return Success Response ---
    return jsonify({"message": "Settings updated successfully."}), 200

# Route to stream hackrf_info to web UI
@app.route('/api/hackrf-info')
def run_command():
    # The command to execute. For security, it's best to build the command as a list.
    command = ["sudo", "hackrf_info"]

    try:
        # Execute the command
        result = subprocess.run(
            command,
            capture_output=True, # Capture stdout and stderr
            text=True,           # Decode output as text
            check=True           # Raise an exception if the command fails
        )

        # Return the standard output as JSON
        return jsonify({
            'status': 'success',
            'output': result.stdout
        })

    except subprocess.CalledProcessError as e:
        # If the command returns a non-zero exit code, it's an error
        return jsonify({
            'status': 'error',
            'output': e.stderr
        }), 500
    except FileNotFoundError:
        # If the command itself isn't found
        return jsonify({
            'status': 'error',
            'output': 'Command not found.'
        }), 404

@app.route('/api/processed-files', methods=['GET'])
def list_processed_files():
    import glob
    files = glob.glob(os.path.join(os.path.dirname(__file__), '*.raw'))
    files = [os.path.basename(f) for f in files]
    return jsonify({'files': files})

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


# --- WebSocket event for processed file updates ---
def notify_processed_files_update():
    import glob, os
    files = glob.glob(os.path.join(os.path.dirname(__file__), '*.raw'))
    files = [os.path.basename(f) for f in files]
    socketio.emit('processed_files_update', {'files': files})

# Socket.IO event to request processed files (for initial load)
@socketio.on('request_processed_files')
def socket_request_processed_files():
    notify_processed_files_update()

# --- Patch watcher to call notify_processed_files_update ---
def start_watcher():
    from recording_watcher import watch_recordings
    def callback():
        notify_processed_files_update()
    watch_recordings(callback)

if __name__ == '__main__':
    # Start the recording watcher in the background, passing callback
    # threading.Thread(target=start_watcher, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=8080, debug=True)
