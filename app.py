import signal
import subprocess
import os
import json
from flask import Flask, jsonify, render_template, request, send_from_directory
from logging.config import dictConfig

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

# Route to serve the main web page (index.html)
@app.route('/')
def home():
    # render_template looks for files in a 'templates' folder
    return render_template('index.html')

# Global variable to hold the recording process object
recording_process = None

@app.route('/api/start-recording', methods=['POST'])
def start_recording():
    """Starts a hackrf_transfer recording process."""
    global recording_process

    if recording_process and recording_process.poll() is None:
        return jsonify({"error": "A recording is already in progress."}), 409 # Conflict

    # Read the selected Rx device from settings
    try:
        with open(SETTINGS_FILE_PATH, 'r') as f:
            settings = json.load(f)
        rx_sn = settings.get('hackrfRxSN')
        if not rx_sn:
            return jsonify({"error": "No receiver (Rx) device selected in settings."}), 400
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify({"error": "Settings file not found or is invalid."}), 500

    # Define the command to run with sudo
    output_filename = settings.get('recording', {}).get('outputFile', 'output.wav')
    frequency = settings.get('recording', {}).get('frequency', 101100000) # Default to 101.1 MHz
    lna_gain = settings.get('recording', {}).get('lnaGain', 20) # Default LNA gain
    vga_gain = settings.get('recording', {}).get('vgaGain', 28) # Default VGA gain
    command = [
        'sudo',
        'hackrf_transfer',
        '-r', output_filename,
        '-f', frequency,
        '-l', lna_gain,
        '-g', vga_gain,
        '-d', rx_sn
    ]

    try:
        print(f"Starting recording with command: {' '.join(command)}")
        # Use Popen to run the command in the background
        recording_process = subprocess.Popen(command)
        return jsonify({"message": f"Recording started. Saving to {output_filename}."}), 200
    except FileNotFoundError:
        return jsonify({"error": "'hackrf_transfer' command not found. Is it in your system's PATH?"}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to start process: {str(e)}"}), 500

@app.route('/api/stop-recording', methods=['POST'])
def stop_recording():
    """Stops the currently running hackrf_transfer process."""
    global recording_process
    
    if recording_process is None or recording_process.poll() is not None:
        return jsonify({"error": "No active recording process to stop."}), 404 # Not Found
        
    try:
        print("Sending interrupt signal to stop recording...")
        # Send SIGINT (Ctrl+C) for a graceful shutdown, allowing the file to be finalized
        recording_process.send_signal(signal.SIGINT)
        recording_process.wait(timeout=5) # Wait up to 5 seconds for it to terminate
        print("Recording process terminated.")
    except subprocess.TimeoutExpired:
        print("Process did not terminate gracefully, killing it.")
        recording_process.kill() # Force kill if it doesn't respond
    except Exception as e:
        return jsonify({"error": f"An error occurred while stopping the process: {str(e)}"}), 500
    finally:
        recording_process = None

    return jsonify({"message": "Recording stopped successfully."}), 200

# Define the path to the settings file within the static folder
SETTINGS_FILE_PATH = os.path.join(app.static_folder, 'settings.json')

@app.route('/save-settings', methods=['POST'])
def save_settings():
    """Receives form data as JSON and saves it to a file."""
    
    # Get the JSON data sent from the frontend
    new_settings = request.get_json()
    
    if not new_settings:
        return jsonify({"status": "error", "message": "No data received"}), 400

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
        return jsonify({"status": "success", "message": "Settings saved successfully!"})

    except Exception as e:
        print(f"Error saving settings: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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

# Run the app when the script is executed
if __name__ == '__main__':
    # host='0.0.0.0' makes it accessible on your network
    app.run(host='0.0.0.0', port=8080, debug=True)
