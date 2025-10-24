// files.js: File management for HackRF-CEMA-UI

const socket = io();
const $ = id => document.getElementById(id);

function refreshFileList() {
  socket.emit('request_processed_files');
}

function renderFileList(files) {
  const container = $('fileList');
  container.innerHTML = '';
  if (!files.length) {
    container.innerHTML = '<p class="text-muted">No .raw files found.</p>';
    return;
  }
  // Create table for file metadata
  const table = document.createElement('table');
  table.className = 'table table-dark table-striped table-bordered';
  table.innerHTML = `
    <thead>
      <tr>
        <th></th>
        <th>Filename</th>
        <th>Type</th>
        <th>Size (KB)</th>
        <th>Start Time (UTC)</th>
        <th>End Time (UTC)</th>
        <th>Duration</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody></tbody>
  `;
  const tbody = table.querySelector('tbody');
  files.forEach(file => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td><input type="checkbox" class="file-select" value="${file.name}"></td>
      <td>${file.name}</td>
      <td>${file.type}</td>
      <td>${file.size_kb}</td>
      <td>${file.start_time || '-'}</td>
      <td>${file.end_time || '-'}</td>
      <td>${file.duration || '-'}</td>
      <td>
        <button class="btn btn-sm btn-outline-primary me-2 rename-btn" data-file="${file.name}">Rename</button>
        <button class="btn btn-sm btn-outline-danger delete-btn" data-file="${file.name}">Delete</button>
      </td>
    `;
    tbody.appendChild(row);
  });
  container.appendChild(table);
}

function getSelectedFiles() {
  return Array.from(document.querySelectorAll('.file-select:checked')).map(cb => cb.value);
}

function showRenamePopup(file) {
  const newName = prompt(`Rename "${file}" to:`, file);
  if (newName && newName !== file) {
    socket.emit('rename_file', { oldName: file, newName });
  }
}

function deleteFiles(files) {
  if (!files.length) return;
  if (confirm(`Delete selected file(s)?\n${files.join('\n')}`)) {
    socket.emit('delete_files', { files });
  }
}

document.addEventListener('DOMContentLoaded', () => {
  refreshFileList();

  // Listen for file list updates
  socket.on('processed_files_update', data => {
    renderFileList(data.files || []);
  });

  // Handle rename and delete actions
  $('fileList').addEventListener('click', e => {
    if (e.target.classList.contains('rename-btn')) {
      showRenamePopup(e.target.dataset.file);
    }
    if (e.target.classList.contains('delete-btn')) {
      deleteFiles([e.target.dataset.file]);
    }
  });

  // Bulk delete button
  $('deleteSelectedBtn').onclick = () => {
    const selected = getSelectedFiles();
    deleteFiles(selected);
  };

  // Refresh button
  $('refreshFilesBtn').onclick = refreshFileList;

  // Listen for backend responses
  socket.on('file_action_status', data => {
    alert(data.message || 'File action completed.');
    refreshFileList();
  });
});
