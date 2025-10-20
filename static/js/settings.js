// settings.js: Settings page logic for HackRF-CEMA-UI
// All code moved from settings.html <script> block
// (Full migration will be performed in the next step)

// settings.js: Restore HackRF serial dropdown logic and settings save

document.addEventListener('DOMContentLoaded', function () {
    // Elements
    const rxSelect = document.getElementById('hackrfRxSN');
    const txSelect = document.getElementById('hackrfTxSN');
    const saveStatus = document.getElementById('saveStatus');
    const form = document.getElementById('general');

    // Fetch available HackRF serials from backend
    fetch('/api/hackrf-info')
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success') {
                // Parse serials from hackrf_info output
                const serials = [];
                const lines = data.output.split('\n');
                for (const line of lines) {
                    const m = line.match(/Serial number\s*:\s*([0-9a-fA-F]+)/);
                    if (m) serials.push(m[1]);
                }
                // Populate dropdowns
                [rxSelect, txSelect].forEach(select => {
                    select.innerHTML = '<option disabled>Select one</option>';
                    serials.forEach(sn => {
                        const opt = document.createElement('option');
                        opt.value = sn;
                        opt.textContent = sn;
                        select.appendChild(opt);
                    });
                });
                // Fetch current settings to select current values
                fetch('/static/settings.json')
                    .then(res => res.json())
                    .then(settings => {
                        if (settings.hackrfRxSN) rxSelect.value = settings.hackrfRxSN;
                        if (settings.hackrfTxSN) txSelect.value = settings.hackrfTxSN;
                    });
            } else {
                saveStatus.textContent = 'Error fetching HackRF info: ' + data.output;
            }
        });

    // Save settings on change
    form.addEventListener('change', function () {
        const newSettings = {
            hackrfRxSN: rxSelect.value,
            hackrfTxSN: txSelect.value
        };
        window.socket = window.socket || io();
        window.socket.emit('save_settings', newSettings);
    });

    // Force save button logic
    const forceSaveBtn = document.getElementById('forceSaveBtn');
    if (forceSaveBtn) {
        forceSaveBtn.addEventListener('click', function () {
            const newSettings = {
                hackrfRxSN: rxSelect.value,
                hackrfTxSN: txSelect.value
            };
            window.socket = window.socket || io();
            window.socket.emit('save_settings', newSettings);
            saveStatus.textContent = 'Force saving settings...';
            saveStatus.className = 'text-info';
        });
    }

    // Listen for save status
    window.socket = window.socket || io();
    window.socket.on('settings_status', function (data) {
        if (data.status === 'success') {
            saveStatus.textContent = 'Settings saved!';
            saveStatus.className = 'text-success';
        } else {
            saveStatus.textContent = 'Error: ' + data.message;
            saveStatus.className = 'text-danger';
        }
        setTimeout(() => { saveStatus.textContent = ''; }, 3000);
    });
});
