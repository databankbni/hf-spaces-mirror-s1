// Medical Report Upload Functions

function openUploadModal() {
  document.getElementById('uploadModal').style.display = 'flex';
  document.getElementById('uploadResult').style.display = 'none';
  document.getElementById('uploadProgress').style.display = 'none';
}

function closeUploadModal() {
  document.getElementById('uploadModal').style.display = 'none';
}

function closeReportsPanel() {
  document.getElementById('reportsPanel').style.right = '-400px';
}

function openReportsPanel() {
  document.getElementById('reportsPanel').style.right = '0';
  loadReports();
}

function handleDrop(event) {
  event.preventDefault();
  event.stopPropagation();
  const file = event.dataTransfer.files[0];
  if (file) uploadReport(file);
}

function handleFileSelect(event) {
  const file = event.target.files[0];
  if (file) uploadReport(file);
}

async function uploadReport(file) {
  const token = localStorage.getItem('hc_token') || localStorage.getItem('authToken');
  if (!token) {
    alert('Please login to upload reports');
    closeUploadModal();
    document.getElementById('loginModal').style.display = 'flex';
    return;
  }
  
  const validTypes = [
    'application/pdf',
    'image/jpeg', 'image/png', 'image/bmp', 'image/tiff',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'text/plain'
  ];
  const validExts = ['.pdf', '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.doc', '.docx', '.txt'];
  const ext = '.' + file.name.split('.').pop().toLowerCase();
  const normalizedType = (file.type || '').toLowerCase().trim();
  if (!validTypes.includes(normalizedType) && !validExts.includes(ext)) {
    alert('Invalid file type. Please upload PDF, image, DOC, DOCX, or TXT files.');
    return;
  }
  
  if (file.size > 10 * 1024 * 1024) {
    alert('File size must be under 10MB');
    return;
  }
  
  document.getElementById('uploadProgress').style.display = 'block';
  document.getElementById('progressBar').style.width = '30%';
  document.getElementById('progressText').textContent = 'Uploading...';
  
  const formData = new FormData();
  formData.append('file', file);
  
  try {
    const response = await fetch(`/api/upload-report?token=${token}`, {
      method: 'POST',
      body: formData
    });
    
    document.getElementById('progressBar').style.width = '70%';
    document.getElementById('progressText').textContent = 'Analyzing report...';
    
    const data = await response.json();
    
    if (data.status === 'ok') {
      document.getElementById('progressBar').style.width = '100%';
      document.getElementById('progressText').textContent = 'Complete!';
      
      const resultDiv = document.getElementById('uploadResult');
      resultDiv.style.display = 'block';
      resultDiv.innerHTML = `
        <div style="background:var(--g100);border-radius:12px;padding:16px;margin-top:16px;">
          <h4 style="color:var(--g800);margin-bottom:12px;">✅ Analysis Complete</h4>
          ${Object.keys(data.vitals).length > 0 ? `
            <div style="margin-bottom:12px;">
              <strong>Detected Vitals:</strong>
              <ul style="margin-top:8px;color:var(--gray600);">
                ${Object.entries(data.vitals).map(([k,v]) => `<li>${k.replace('_', ' ').toUpperCase()}: ${v}</li>`).join('')}
              </ul>
            </div>
          ` : ''}
          <div style="background:white;border-radius:8px;padding:12px;margin-top:12px;max-height:300px;overflow-y:auto;">
            <strong style="color:var(--g700);">AI Insights:</strong>
            <p style="margin-top:8px;color:var(--gray600);line-height:1.6;">${data.analysis.replace(/\n/g, '<br>')}</p>
          </div>
        </div>
      `;
      
      loadReports();
      showToast('Report uploaded successfully! 📊');
    } else {
      throw new Error(data.detail || 'Upload failed');
    }
  } catch (error) {
    document.getElementById('progressBar').style.width = '0%';
    document.getElementById('progressText').textContent = 'Error: ' + error.message;
    setTimeout(() => {
      document.getElementById('uploadProgress').style.display = 'none';
    }, 3000);
  }
}

async function loadReports() {
  const token = localStorage.getItem('hc_token') || localStorage.getItem('authToken');
  if (!token) {
    document.getElementById('reportsList').innerHTML = `
      <p style="text-align:center;color:var(--gray600);padding:40px 20px;">
        Please login to view your reports
      </p>
    `;
    return;
  }
  
  try {
    const response = await fetch(`/api/reports?token=${token}`);
    const data = await response.json();
    
    if (data.status === 'ok' && data.reports.length > 0) {
      document.getElementById('reportsList').innerHTML = data.reports.map(report => `
        <div style="background:var(--gray50);border-radius:12px;padding:16px;margin-bottom:12px;cursor:pointer;" onclick="viewReport(${report.id})">
          <div style="display:flex;justify-content:space-between;align-items:start;">
            <div style="flex:1;">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <span style="font-size:1.2rem;">${report.file_type.includes('pdf') ? '📄' : '🖼️'}</span>
                <strong style="color:var(--g800);font-size:0.95rem;">${report.filename}</strong>
              </div>
              <p style="color:var(--gray400);font-size:0.85rem;">
                ${report.pages} page${report.pages > 1 ? 's' : ''} • ${formatFileSize(report.file_size)} • ${formatDate(report.uploaded_at)}
              </p>
              ${report.analysis ? `
                <p style="color:var(--gray600);font-size:0.85rem;margin-top:8px;line-height:1.5;">
                  ${report.analysis.substring(0, 100)}...
                </p>
              ` : ''}
            </div>
            <button onclick="event.stopPropagation();deleteReport(${report.id})" 
                    style="color:var(--red);font-size:1.2rem;padding:4px;">🗑️</button>
          </div>
        </div>
      `).join('');
    } else {
      document.getElementById('reportsList').innerHTML = `
        <p style="text-align:center;color:var(--gray400);padding:40px 20px;">
          📋 No reports uploaded yet<br>
          <span style="font-size:0.9rem;">Upload your first medical report to get started</span>
        </p>
      `;
    }
  } catch (error) {
    document.getElementById('reportsList').innerHTML = `
      <p style="text-align:center;color:var(--red);padding:40px 20px;">
        Error loading reports: ${error.message}
      </p>
    `;
  }
}

async function viewReport(reportId) {
  const token = localStorage.getItem('hc_token') || localStorage.getItem('authToken');
  try {
    const response = await fetch(`/api/report/${reportId}?token=${token}`);
    const data = await response.json();
    
    if (data.status === 'ok') {
      const report = data.report;
      alert(`${report.filename}\n\n${report.analysis}`);
    }
  } catch (error) {
    alert('Error loading report: ' + error.message);
  }
}

async function deleteReport(reportId) {
  if (!confirm('Delete this report? This cannot be undone.')) return;
  
  const token = localStorage.getItem('hc_token') || localStorage.getItem('authToken');
  try {
    const response = await fetch(`/api/report/${reportId}?token=${token}`, {
      method: 'DELETE'
    });
    const data = await response.json();
    
    if (data.status === 'ok') {
      loadReports();
      showToast('Report deleted 🗑️');
    } else {
      alert('Error deleting report');
    }
  } catch (error) {
    alert('Error: ' + error.message);
  }
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function formatDate(isoString) {
  const date = new Date(isoString);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}
