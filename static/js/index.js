// index.js: Main UI logic for HackRF-CEMA-UI
// All code moved from index.html <script> block

// Initialize Socket.IO client
const socket = io();
const $ = id => document.getElementById(id);

// ...existing code from index.html <script> block will be moved here...
// (Full migration will be performed in the next step)
// Manual refresh button for transmit input files
document.getElementById('refreshInputFilesBtn').onclick = function () {
  socket.emit('request_processed_files');
};

function parseHackrfInfo(rawText) {
  const result = { devices: [] };
  const [headerBlock, ...blocks] = rawText.trim().split('Found HackRF');
  headerBlock.trim().split('\n').forEach(line => {
    const [key, ...rest] = line.split(':');
    if (rest.length) result[key.trim()] = rest.join(':').trim();
  });
  blocks.forEach(block => {
    const device = {};
    block.trim().split('\n').forEach(line => {
      const [key, ...rest] = line.split(':');
      if (rest.length) device[key.trim()] = rest.join(':').trim();
    });
    if (Object.keys(device).length) result.devices.push(device);
  });
  return result;
}

function displayHackrfInfo(data, elementId) {
  const el = $(elementId);
  if (!el) return;
  let html = '<h3>System Information</h3>';
  Object.entries(data).forEach(([k, v]) => {
    if (k !== 'devices') html += `<strong>${k}:</strong> ${v}<br>`;
  });
  data.devices.forEach((dev, i) => {
    html += `<div class="device-block"><h3>Device ${i + 1}</h3>`;
    Object.entries(dev).forEach(([k, v]) => html += `<strong>${k}:</strong> ${v}<br>`);
    html += `</div>`;
  });
  el.innerHTML = html;
}

async function hackrfRefresh() {
  const el = $('hackrf-info');
  el.textContent = 'Running command...';
  const response = await fetch('/api/hackrf-info');
  const data = await response.json();
  displayHackrfInfo(parseHackrfInfo(data.output), 'hackrf-info');
}

async function populateForm() {
  try {
    const response = await fetch('/static/settings.json');
    if (!response.ok) return;
    const { recording, transmitting } = await response.json();
    if (recording) {
      $('outputFile').value = recording.outputFile || '';
      $('lnaGain').value = recording.lnaGain || 0;
      $('vgaGain').value = recording.vgaGain || 0;
      $('recordSettingsForm').querySelector('#frequency').value = recording.frequency || 0;
      $('squelchEnabled').checked = recording.squelchEnabled || false;
      $('squelchThreshold').value = recording.squelchThreshold || '';
    }

    if (transmitting) {
      const selector = $('transmitInputFile');
      if (selector && transmitting.inputFile) {
        selector.value = transmitting.inputFile;
      }
      $('txGain').value = transmitting.txGain || 0;
      $('transmitSettingsForm').querySelector('#frequency').value = transmitting.frequency || 0;
      $('repeat').checked = transmitting.repeat || false;
    }
  } catch (e) { console.error('Could not load or parse settings:', e); }
}

document.addEventListener('DOMContentLoaded', () => {
  // Speech energy indicator setup
  const speechIndicator = document.createElement('span');
  speechIndicator.id = 'speechIndicator';
  speechIndicator.className = 'ms-3 fw-bold';
  speechIndicator.style.fontSize = '1.1em';
  speechIndicator.textContent = '';
  const spectrumInfo = document.getElementById('spectrumInfo');
  if (spectrumInfo && spectrumInfo.parentNode) {
    spectrumInfo.parentNode.insertBefore(speechIndicator, spectrumInfo.nextSibling);
  }

  socket.on('speech_energy', function(data) {
    if (data.detected) {
      speechIndicator.textContent = 'Speech Detected!';
      speechIndicator.style.color = '#0f0';
    } else {
      speechIndicator.textContent = 'No Speech';
      speechIndicator.style.color = '#888';
    }
    // Optionally show energy value for debugging
    // speechIndicator.title = `Energy: ${data.energy.toFixed(0)}`;
  });
  // --- Socket.IO event handlers that need DOM elements ---
  socket.on('recording_status', function (data) {
    if (data.hasOwnProperty('running')) {
      // This is a status query response
      if (data.running) {
        startRxBtn.disabled = true;
        stopRxBtn.disabled = false;
      } else {
        startRxBtn.disabled = false;
        stopRxBtn.disabled = true;
      }
      return;
    }
    if (data.error) {
      logToBox(recordLogBox, `Error: ${data.error}`, 'text-danger');
      startRxBtn.disabled = false;
      stopRxBtn.disabled = true;
    }
    if (data.message) {
      logToBox(recordLogBox, data.message, 'text-success');
      //console.log("Recording status message:", data.message);
      const msg = data.message.toLowerCase();
      if (msg.includes('started')) {
        startRxBtn.disabled = true;
        stopRxBtn.disabled = false;
      } else if (msg.includes('stopped')) {
        startRxBtn.disabled = false;
        stopRxBtn.disabled = true;
      }
    }
  });
  // Query backend for current recording state on load (after socket is initialized)
  socket.emit('query_recording_status');
  // Display HackRF info on page load
  hackrfRefresh();
  // Record section
  const startRxBtn = $('startRecordButton');
  const stopRxBtn = $('stopRecordButton');
  const recordLogBox = $('recordLog');
  // Transmit section
  const startTxBtn = $('startTransmitButton');
  const stopTxBtn = $('stopTransmitButton');
  const transmitLogBox = $('transmitLog');
  let transmitPolling = null;

  // Generic log function for any log box
  const logToBox = (logBox, msg, color = 'text-white-50') => {
    if (logBox.children.length === 1 && logBox.firstChild.textContent.includes('...')) logBox.innerHTML = '';
    const ts = new Date().toLocaleTimeString();
    logBox.insertAdjacentHTML('beforeend', `<p class="mb-1"><span class="text-secondary">${ts}</span> &gt; <span class="${color}">${msg}</span></p>`);
    logBox.scrollTop = logBox.scrollHeight;
    // Autoscroll page if logbox is below viewport
    const rect = logBox.getBoundingClientRect();
    if (rect.bottom > window.innerHeight) {
      logBox.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  };

  // Record handlers
  startRxBtn.onclick = () => {
    const outputFile = $('outputFile').value || 'unknown';
    logToBox(recordLogBox, `Starting recording to <strong>${outputFile}</strong>...`, 'text-warning');
    startRxBtn.disabled = true;
    stopRxBtn.disabled = false;
    socket.emit('start_record', {});
  };
  stopRxBtn.onclick = () => {
    const outputFile = $('outputFile').value || 'unknown';
    logToBox(recordLogBox, `Stopping recording to <strong>${outputFile}</strong>...`, 'text-warning');
    stopRxBtn.disabled = true;
    startRxBtn.disabled = false;
    socket.emit('stop_recording');
  };
  // Transmit handlers
  startTxBtn.onclick = () => {
    const selector = $('transmitInputFile');
    const inputFile = selector ? selector.value : '';
    logToBox(transmitLogBox, `Starting transmission from <strong>${inputFile}</strong>...`, 'text-warning');
    startTxBtn.disabled = true;
    stopTxBtn.disabled = false;
    socket.emit('start_transmit', {});
  };
  stopTxBtn.onclick = () => {
    const selector = $('transmitInputFile');
    const inputFile = selector ? selector.value : '';
    logToBox(transmitLogBox, `Stopping transmission from <strong>${inputFile}</strong>...`, 'text-warning');
    stopTxBtn.disabled = true;
    startTxBtn.disabled = false;
    socket.emit('stop_transmit');
  };

  // Transmit status event handler (mirror record logic)
  socket.on('transmit_status', function (data) {
    // Always log any backend info to the transmit log box
    if (data.hasOwnProperty('running')) {
      logToBox(transmitLogBox, data.running ? 'Transmission is running.' : 'Transmission is stopped.', 'text-info');
      if (data.running) {
        startTxBtn.disabled = true;
        stopTxBtn.disabled = false;
      } else {
        startTxBtn.disabled = false;
        stopTxBtn.disabled = true;
      }
    }
    if (data.error) {
      logToBox(transmitLogBox, `Error: ${data.error}`, 'text-danger');
      startTxBtn.disabled = false;
      stopTxBtn.disabled = true;
    }
    if (data.message) {
      logToBox(transmitLogBox, data.message, 'text-success');
      const msg = data.message.toLowerCase();
      if (msg.includes('started')) {
        startTxBtn.disabled = true;
        stopTxBtn.disabled = false;
      } else if (msg.includes('stopped') || msg.includes('finished')) {
        startTxBtn.disabled = false;
        stopTxBtn.disabled = true;
      }
    }
  });
  // Query backend for current transmit state on load
  socket.emit('query_transmit_status');

  // --- Socket.IO for processed file updates ---
  function updateTransmitInputSelector(files) {
    const selector = document.getElementById('transmitInputFile');
    const current = selector.value;
    selector.innerHTML = '';
    files.forEach(file => {
      const option = document.createElement('option');
      option.value = file.name || file;
      option.textContent = file.name || file;
      selector.appendChild(option);
    });
    // Try to keep the current selection
    if (current && files.includes(current)) {
      selector.value = current;
    } else if (files.length > 0) {
      selector.value = files[0];
    }
  }

  socket.on('processed_files_update', function (data) {
    updateTransmitInputSelector(data.files);
    // Optionally, update selector value if new file appeared
    const selector = $('transmitInputFile');
    if (selector && data.files.length > 0 && !data.files.includes(selector.value)) {
      selector.value = data.files[data.files.length - 1];
    }
  });

  // On initial load, fetch processed files in case no event arrives
  window.addEventListener('DOMContentLoaded', function () {
    // On initial load, request processed files via socket
    socket.emit('request_processed_files');
  });

  // --- Spectrum Display ---
  const spectrumCanvas = document.getElementById('spectrumDisplay');
  let spectrumCtx = null;
  if (spectrumCanvas) {
    spectrumCtx = spectrumCanvas.getContext('2d');
  }
  const WATERFALL_HEIGHT = spectrumCanvas ? spectrumCanvas.height : 200;
  const WATERFALL_HISTORY = WATERFALL_HEIGHT;
  let waterfall = [];
  let peakHold = null;
  function drawSpectrum(data) {
    if (!spectrumCtx) return;
    // Black background
    spectrumCtx.fillStyle = '#000';
    spectrumCtx.fillRect(0, 0, spectrumCanvas.width, spectrumCanvas.height);
    // Waterfall: add new spectrum to history
    if (data && data.length) {
      waterfall.unshift([...data]);
      if (waterfall.length > WATERFALL_HISTORY) waterfall.pop();
      // Peak hold
      if (!peakHold || peakHold.length !== data.length) {
        peakHold = [...data];
      } else {
        for (let i = 0; i < data.length; i++) {
          if (data[i] > peakHold[i]) peakHold[i] = data[i];
        }
      }
    }
    // Draw waterfall (KrakenSDR style: color-mapped, scrolls down)
    for (let row = 0; row < waterfall.length; row++) {
      const spectrum = waterfall[row];
      for (let i = 0; i < spectrum.length; i++) {
        const x = (i / spectrum.length) * spectrumCanvas.width;
        // KrakenSDR color mapping: blue (low) to cyan/green/yellow (high)
        const v = Math.max(0, Math.min(1, spectrum[i]));
        let r = 0, g = 0, b = 0;
        if (v < 0.33) {
          b = 255 * (0.5 + v * 1.5);
          g = 255 * (v * 1.5);
        } else if (v < 0.66) {
          g = 255 * (0.5 + (v - 0.33) * 1.5);
          b = 255 * (1 - (v - 0.33) * 1.5);
        } else {
          r = 255 * ((v - 0.66) * 3);
          g = 255;
        }
        const color = `rgb(${Math.floor(r)},${Math.floor(g)},${Math.floor(b)})`;
        spectrumCtx.fillStyle = color;
        spectrumCtx.fillRect(x, row, spectrumCanvas.width / spectrum.length, 1);
      }
    }
    // Vertical grid lines (KrakenSDR: faint, spaced)
    spectrumCtx.strokeStyle = 'rgba(80,80,80,0.5)';
    spectrumCtx.lineWidth = 1;
    for (let i = 0; i <= 8; i++) {
      let x = (i / 8) * spectrumCanvas.width;
      spectrumCtx.beginPath();
      spectrumCtx.moveTo(x, 0);
      spectrumCtx.lineTo(x, spectrumCanvas.height);
      spectrumCtx.stroke();
    }
    // Draw spectrum line (KrakenSDR: cyan)
    spectrumCtx.beginPath();
    spectrumCtx.strokeStyle = '#00ffe7';
    spectrumCtx.lineWidth = 2.5;
    for (let i = 0; i < data.length; i++) {
      const x = (i / data.length) * spectrumCanvas.width;
      const y = spectrumCanvas.height - (data[i] * spectrumCanvas.height);
      if (i === 0) spectrumCtx.moveTo(x, y);
      else spectrumCtx.lineTo(x, y);
    }
    spectrumCtx.stroke();
    // Draw peak hold line (KrakenSDR: yellow)
    if (peakHold && peakHold.length === data.length) {
      spectrumCtx.beginPath();
      spectrumCtx.strokeStyle = '#ffff00';
      spectrumCtx.lineWidth = 1.5;
      for (let i = 0; i < peakHold.length; i++) {
        const x = (i / peakHold.length) * spectrumCanvas.width;
        const y = spectrumCanvas.height - (peakHold[i] * spectrumCanvas.height);
        if (i === 0) spectrumCtx.moveTo(x, y);
        else spectrumCtx.lineTo(x, y);
      }
      spectrumCtx.stroke();
    }
    // Flash refresh indicator
    spectrumCtx.fillStyle = 'rgba(0,255,255,0.10)';
    spectrumCtx.fillRect(0, 0, spectrumCanvas.width, 10);
  }
  socket.on('spectrum_update', function (data) {
    if (data.spectrum && Array.isArray(data.spectrum)) {
      drawSpectrum(data.spectrum);
      const infoElem = document.getElementById('spectrumInfo');
      if (infoElem) infoElem.textContent = data.info || '';
      // Flash refresh indicator
      const indicator = document.getElementById('spectrumRefreshIndicator');
      if (indicator) {
        indicator.style.color = '#ff0';
        indicator.textContent = '(Live: Refreshed)';
        setTimeout(() => {
          indicator.style.color = '#0ff';
          indicator.textContent = '(Live)';
        }, 350);
      }
    }
  });
  // --- Live spectrum polling ---
  setInterval(() => {
    socket.emit('request_spectrum');
  }, 1000);

});

populateForm();

$('recordSettingsForm').addEventListener('change', () => {
  const data = {
    recording: {
      outputFile: $('outputFile').value,
      lnaGain: $('lnaGain').value || '0',
      vgaGain: $('vgaGain').value || '0',
      frequency: $('frequency').value || '0',
      squelchEnabled: $('squelchEnabled').checked,
      squelchThreshold: $('squelchThreshold').value
    }
  };
  socket.emit('save_settings', data);
});

$('transmitSettingsForm').addEventListener('change', () => {
  const selector = $('transmitInputFile');
  const data = {
    transmitting: {
      inputFile: selector ? selector.value : '',
      txGain: $('txGain').value || '0',
      frequency: $('transmitSettingsForm').querySelector('#frequency').value || '0',
      repeat: $('repeat').checked
    }
  };
  socket.emit('save_settings', data);
});
// When selector changes, save to settings.json via socket NEW <<<<<<<<<<<<<<<<<<<
document.getElementById('transmitInputFile').addEventListener('change', function () {
  socket.emit('update_transmit_input', { inputFile: this.value });
});
socket.on('settings_status', function (data) {
  if (data.status === 'error') {
    alert(data.message || 'Failed to save settings.');
  }
});
socket.on('transmit_input_status', function (data) {
  if (data.error) {
    alert(data.error);
  }
});