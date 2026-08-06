// Tab switching
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
  });
});

// Sync slider value display
function syncVal(id){
  const input = document.getElementById(id);
  const out = document.getElementById('val-' + id);
  let v = parseFloat(input.value);
  if(id === 'pengeluaran'){
    out.textContent = Math.round(v).toLocaleString('id-ID');
  } else {
    out.textContent = v.toFixed(1);
  }
}
['p0','ipm','lama_sekolah','uhh','sanitasi','air_minum','pengeluaran','tpak','tpt'].forEach(syncVal);

// Preset scenarios
const presets = {
  tinggi: { p0:18.5, ipm:62.5, lama_sekolah:6.5, uhh:65.2, sanitasi:45.0, air_minum:55.0, pengeluaran:8500, tpak:65.0, tpt:8.5, pdrb:"15.000.000" },
  rendah: { p0:3.5, ipm:82.5, lama_sekolah:11.5, uhh:74.5, sanitasi:95.0, air_minum:98.0, pengeluaran:18000, tpak:72.0, tpt:4.5, pdrb:"85.000.000" }
};

function applyPreset(name){
  const p = presets[name];
  Object.keys(p).forEach(k => {
    if(k === 'pdrb'){
      document.getElementById('pdrb').value = p[k];
    } else {
      document.getElementById(k).value = p[k];
      syncVal(k);
    }
  });
  // reset result panel back to waiting state when preset changes
  document.getElementById('waitingBox').style.display = 'block';
  document.getElementById('resultPoor').style.display = 'none';
  document.getElementById('resultNotPoor').style.display = 'none';
  updatePlot();
}

// Panggil API prediksi dari Flask
async function showResult(){
  document.getElementById('waitingBox').style.display = 'none';
  document.getElementById('resultPoor').style.display = 'none';
  document.getElementById('resultNotPoor').style.display = 'none';

  const data = {
      p0: parseFloat(document.getElementById('p0').value),
      lama_sekolah: parseFloat(document.getElementById('lama_sekolah').value),
      pengeluaran: parseFloat(document.getElementById('pengeluaran').value),
      ipm: parseFloat(document.getElementById('ipm').value),
      uhh: parseFloat(document.getElementById('uhh').value),
      sanitasi: parseFloat(document.getElementById('sanitasi').value),
      air_minum: parseFloat(document.getElementById('air_minum').value),
      tpt: parseFloat(document.getElementById('tpt').value),
      tpak: parseFloat(document.getElementById('tpak').value),
      pdrb: parseFloat(document.getElementById('pdrb').value.replace(/\./g, ''))
  };

  try {
      const response = await fetch('/predict', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
      });
      const result = await response.json();
      
      if (result.error) {
          alert('Error: ' + result.error);
          document.getElementById('waitingBox').style.display = 'block';
          return;
      }

      if (result.prediction === 1) {
          document.getElementById('resultPoor').style.display = 'block';
          document.querySelector('#resultPoor .conf-label').innerText = 'Keyakinan Model (Probabilitas): ' + (result.probability * 100).toFixed(1) + '%';
          document.querySelector('#resultPoor .conf-bar-fill').style.width = (result.probability * 100) + '%';
      } else {
          document.getElementById('resultNotPoor').style.display = 'block';
          const probNotPoor = 1 - result.probability;
          document.querySelector('#resultNotPoor .conf-label').innerText = 'Keyakinan Model (Probabilitas): ' + (probNotPoor * 100).toFixed(1) + '%';
          document.querySelector('#resultNotPoor .conf-bar-fill').style.width = (probNotPoor * 100) + '%';
      }
      
  } catch (e) {
      alert('Gagal memanggil backend model');
      document.getElementById('waitingBox').style.display = 'block';
  }
}

// Panggil API plot dari Flask
async function updatePlot() {
  const feature = document.getElementById('featSelect').value;
  let current_value = 0;
  
  if (feature === 'Persentase Penduduk Miskin (P0)') current_value = parseFloat(document.getElementById('p0').value);
  else if (feature === 'Pengeluaran per Kapita') current_value = parseFloat(document.getElementById('pengeluaran').value);
  else if (feature === 'Indeks Pembangunan Manusia (IPM)') current_value = parseFloat(document.getElementById('ipm').value);
  else if (feature === 'Umur Harapan Hidup (UHH)') current_value = parseFloat(document.getElementById('uhh').value);

  try {
      const response = await fetch('/plot', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ feature: feature, current_value: current_value })
      });
      const result = await response.json();
      
      if (result.image) {
          const chartPlaceholder = document.querySelector('.chart-placeholder');
          chartPlaceholder.innerHTML = `<img src="data:image/png;base64,${result.image}" style="width:100%; height:auto;" />`;
          // Re-apply background style since it's a card
          chartPlaceholder.style.padding = '0';
      }
  } catch (e) {
      console.error('Failed to load plot', e);
  }
}

document.getElementById('featSelect').addEventListener('change', updatePlot);

// Update plot when slider is released (change event)
['p0','ipm','lama_sekolah','uhh','sanitasi','air_minum','pengeluaran','tpak','tpt'].forEach(id => {
    document.getElementById(id).addEventListener('change', updatePlot);
});

window.addEventListener('load', updatePlot);
