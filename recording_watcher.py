import os
import time
import threading
import subprocess
import json
import requests
import re

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(OUTPUT_DIR, 'static', 'settings.json')
CHECK_INTERVAL = 2  # seconds
STABLE_TIME = 10   # seconds (how long file size must remain unchanged)
processed_files = set()

# Get output file prefix from settings.json
def get_output_prefix():
    try:
        with open(SETTINGS_PATH, 'r') as f:
            settings = json.load(f)
        output_file = settings.get('recording', {}).get('outputFile', 'output.raw')
        prefix = os.path.splitext(os.path.basename(output_file))[0]
        suffix = os.path.splitext(output_file)[1]
        return prefix, suffix
    except Exception as e:
        print(f"Could not read settings.json: {e}")
        return 'output', '.raw'

def get_base_output_prefix():
    try:
        with open(SETTINGS_PATH, 'r') as f:
            settings = json.load(f)
        output_file = settings.get('recording', {}).get('outputFile', 'output.raw')
        base = os.path.splitext(os.path.basename(output_file))[0]
        return base
    except Exception as e:
        print(f"Could not read settings.json: {e}")
        return 'output'

def post_log(message):
    try:
        requests.post('http://localhost:8080/api/record-log', json={'message': message})
    except Exception as e:
        print(f"Failed to post log: {e}")

def process_file(filepath, on_processed=None):
    print(f"Processing: {filepath}")
    import os
    base = os.path.splitext(filepath)[0]
    # Only process if '_processed' is not in the base name
    if filepath.endswith('.raw') and '_processed' not in base:
        processed_prefix = base + '_processed.raw'
        print(f"Output file will be: {processed_prefix}")  # Debug print
        try:
            pipeline = (
                f"sox -t raw -r 48000 -e signed -b 16 -c 1 {filepath} {processed_prefix} "
                f"silence 1 0.1 1% 1 1.0 1%"
            )
            print(f"Running post-processing pipeline: {pipeline}")
            result = subprocess.run(pipeline, shell=True, check=True, capture_output=True, text=True)
            print(result.stdout)
            print(result.stderr)
            processed_files.add(filepath)
            # Only delete if file still exists
            if os.path.exists(filepath):
                os.remove(filepath)
            if on_processed:
                on_processed()
        except Exception as e:
            print(f"Post-processing failed: {e}")

def watch_recordings(on_processed=None):
    print(f"Watching {OUTPUT_DIR} for finished raw recordings...")
    seen = {}
    while True:
        base_prefix = get_base_output_prefix()
        pattern = re.compile(rf"^{re.escape(base_prefix)}(_\d+)?\.raw$")
        for fname in os.listdir(OUTPUT_DIR):
            if pattern.match(fname):
                fpath = os.path.join(OUTPUT_DIR, fname)
                base = os.path.splitext(fname)[0]
                if '_processed' in base or fpath in processed_files:
                    continue
                size = os.path.getsize(fpath)
                now = time.time()
                if fpath not in seen:
                    seen[fpath] = (size, now)
                else:
                    last_size, last_time = seen[fpath]
                    if size == last_size and now - last_time > STABLE_TIME:
                        processed_files.add(fpath)
                        process_file(fpath, on_processed=on_processed)
                        seen.pop(fpath)
                    elif size != last_size:
                        seen[fpath] = (size, now)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    threading.Thread(target=watch_recordings, daemon=True).start()
    while True:
        time.sleep(10)
