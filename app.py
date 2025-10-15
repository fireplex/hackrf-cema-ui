import subprocess
import time
from flask import Flask, jsonify, render_template

# Initialize the Flask application
app = Flask(__name__)

# Route to serve the main web page (index.html)
@app.route('/')
def home():
    # render_template looks for files in a 'templates' folder
    return render_template('index.html')

# Route to the settings.html page
@app.route('/settings')
def settings():
    return render_template('settings.html')

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
