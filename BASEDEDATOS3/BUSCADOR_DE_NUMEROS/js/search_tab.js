// js/search_tab.js

let datosOriginales = [];
let datosProcesados = [];

let paginaActual = 1;
let registrosPorPagina = 20;

let estadoColumna = {
  ordenCol: null,
  ordenDir: 'asc',
  filtros: {}
};

document.addEventListener("DOMContentLoaded", () => {
  construirCabecerasDropdown();

  document.getElementById("btnBuscarIndividual")?.addEventListener("click", ejecutarBusquedaIndividual);
  document.getElementById("btnLimpiarIndividual")?.addEventListener("click", limpiarTodasLasConsultas);

  document.getElementById("inputBuscar")?.addEventListener("keyup", (e) => {
    if (e.key === "Enter") ejecutarBusquedaIndividual();
  });

  document.getElementById("selectRegistrosPorPagina")?.addEventListener("change", (e) => {
    registrosPorPagina = parseInt(e.target.value, 10);
    paginaActual = 1;
    guardarEnLocalStorage();
    renderizarPagina();
  });

  // Cargar búsqueda almacenada al cambiar de pestaña y regresar
  cargarDesdeLocalStorage();
});

// Función para restablecer la vista, limpiar el campo de texto y eliminar la caché del navegador
function limpiarTodasLasConsultas() {
  datosOriginales = [];
  datosProcesados = [];
  estadoColumna.filtros = {};
  estadoColumna.ordenCol = null;

  const inputBuscar = document.getElementById("inputBuscar");
  if (inputBuscar) inputBuscar.value = "";

  paginaActual = 1;

  // Eliminar la caché guardada
  localStorage.removeItem("busqueda_individual_cache");

  // Limpiar campos de texto dentro de los dropdowns de cabecera
  document.querySelectorAll("[id^='inputFiltro_']").forEach(input => input.value = "");

  // Ocultar sección de métricas y paginación
  const secMetricas = document.getElementById('seccionMetricasHeader').style.setProperty('display', 'flex', 'important');
  if (secMetricas) secMetricas.style.display = "none";

  const secPaginacion = document.getElementById("seccionPaginacion");
  if (secPaginacion) secPaginacion.style.display = "none";

  // Restablecer el mensaje inicial en la tabla
  const tbody = document.querySelector("#tablaResultados tbody");
  if (tbody) {
    tbody.innerHTML = `
      <tr>
        <td colspan="15" class="text-center py-4 text-muted">
          Realiza una búsqueda para visualizar los datos.
        </td>
      </tr>`;
  }

  actualizarEstilosCabeceras();
}

// Guardar el estado actual en el almacenamiento local
function guardarEnLocalStorage() {
  const datosGuardar = {
    datosOriginales,
    selectCriterio: document.getElementById("selectCriterio")?.value || "index_code",
    inputBuscar: document.getElementById("inputBuscar")?.value || "",
    registrosPorPagina,
    paginaActual,
    estadoColumna
  };
  localStorage.setItem("busqueda_individual_cache", JSON.stringify(datosGuardar));
}

// Recuperar datos previamente almacenados al abrir la vista
function cargarDesdeLocalStorage() {
  const cache = localStorage.getItem("busqueda_individual_cache");
  if (!cache) return;

  try {
    const parsed = JSON.parse(cache);
    datosOriginales = parsed.datosOriginales || [];
    registrosPorPagina = parsed.registrosPorPagina || 20;
    paginaActual = parsed.paginaActual || 1;
    estadoColumna = parsed.estadoColumna || { ordenCol: null, ordenDir: 'asc', filtros: {} };

    if (document.getElementById("selectCriterio") && parsed.selectCriterio) {
      document.getElementById("selectCriterio").value = parsed.selectCriterio;
    }
    if (document.getElementById("inputBuscar") && parsed.inputBuscar) {
      document.getElementById("inputBuscar").value = parsed.inputBuscar;
    }
    if (document.getElementById("selectRegistrosPorPagina")) {
      document.getElementById("selectRegistrosPorPagina").value = registrosPorPagina;
    }

    if (datosOriginales.length > 0) {
      procesarYRenderizar();
    }
  } catch (err) {
    console.error("Error al cargar datos guardados:", err);
  }
}

function construirCabecerasDropdown() {
  const ths = document.querySelectorAll("#headersRow th");

  ths.forEach(th => {
    const colKey = th.getAttribute("data-col");
    const colTitle = th.textContent.trim();

    th.innerHTML = `
      <div class="th-container">
        <span class="th-title-text">${colTitle}</span>
        <div class="dropdown d-inline-block">
          <button class="btn-col-menu" type="button" data-bs-toggle="dropdown" data-bs-auto-close="outside" aria-expanded="false" id="btnDrop_${colKey}">
            <i class="bi bi-three-dots-vertical"></i>
          </button>
          <div class="dropdown-menu dropdown-menu-end p-3 filter-dropdown-menu shadow">
            <h6 class="dropdown-header px-0 text-dark fw-bold border-bottom pb-1 mb-2">${colTitle}</h6>
            
            <button class="dropdown-item py-1 px-2 rounded small" type="button" onclick="ordenarPorColumna('${colKey}', 'asc')">
              <i class="bi bi-sort-alpha-down me-2 text-primary"></i> Ordenar Ascendente (A-Z)
            </button>
            <button class="dropdown-item py-1 px-2 rounded small" type="button" onclick="ordenarPorColumna('${colKey}', 'desc')">
              <i class="bi bi-sort-alpha-up-alt me-2 text-primary"></i> Ordenar Descendente (Z-A)
            </button>
            <button class="dropdown-item py-1 px-2 rounded small text-muted" type="button" onclick="limpiarOrdenColumna()">
              <i class="bi bi-x-circle me-2"></i> Quitar Orden
            </button>

            <div class="dropdown-divider my-2"></div>

            <label class="form-label small fw-bold mb-1 text-muted">Filtrar por texto:</label>

            <div class="input-group input-group-sm mb-2">
              <input type="text" class="form-control" id="inputFiltro_${colKey}" placeholder="Buscar..." value="${estadoColumna.filtros[colKey] || ''}" onkeyup="if(event.key==='Enter') aplicarFiltroColumna('${colKey}')">
            </div>
            <div class="d-flex gap-1">
              <button class="btn btn-primary btn-sm flex-fill" type="button" onclick="aplicarFiltroColumna('${colKey}')">
                <i class="bi bi-funnel-fill me-1"></i> Filtrar
              </button>
              <button class="btn btn-outline-secondary btn-sm flex-fill" type="button" onclick="limpiarFiltroColumna('${colKey}')">
                Limpiar
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
  });
}

function obtenerBadgeStatus(status) {
  const statusUpper = (status || "").toUpperCase().trim();
  if (statusUpper === "ACTIVA" || statusUpper === "ACTIVO") {
    return `<span class="badge bg-success">ACTIVA</span>`;
  } else if (statusUpper === "INACTIVA" || statusUpper === "INACTIVO") {
    return `<span class="badge bg-danger">INACTIVA</span>`;
  } else {
    return `<span class="badge bg-secondary">${statusUpper || '-'}</span>`;
  }
}

async function ejecutarBusquedaIndividual() {
  const campo = document.getElementById("selectCriterio").value;
  const valor = document.getElementById("inputBuscar").value.trim();

  if (!valor) {
    alert("Por favor ingresa un término para buscar.");
    return;
  }

  mostrarSpinner(true);

  try {
    let query = supabaseClient.from('registros_ventas').select('*');

    if (campo === 'index_code') {
      query = query.ilike('index_code', `%${valor}%`);
    } else if (campo === 'nombre') {
      query = query.ilike('nombre', `%${valor}%`);
    } else if (campo === 'numero') {
      query = query.or(`numero_venta.ilike.%${valor}%,confirmado_1.ilike.%${valor}%,confirmado_2.ilike.%${valor}%`);
    }

    const { data, error } = await query.limit(2000);
    if (error) throw error;
    
    datosOriginales = data || [];
    paginaActual = 1;
    guardarEnLocalStorage();
    procesarYRenderizar();

  } catch (err) {
    console.error("Error en consulta:", err);
    alert("Error al realizar la búsqueda: " + err.message);
  } finally {
    mostrarSpinner(false);
  }
}

window.ordenarPorColumna = function(colKey, direccion) {
  estadoColumna.ordenCol = colKey;
  estadoColumna.ordenDir = direccion;
  cerrarDropdown(colKey);
  guardarEnLocalStorage();
  procesarYRenderizar();
};

window.limpiarOrdenColumna = function() {
  estadoColumna.ordenCol = null;
  cerrarDropdowns();
  guardarEnLocalStorage();
  procesarYRenderizar();
};

window.aplicarFiltroColumna = function(colKey) {
  const input = document.getElementById(`inputFiltro_${colKey}`);
  const val = input ? input.value.trim() : "";

  if (val !== "") {
    estadoColumna.filtros[colKey] = val;
  } else {
    delete estadoColumna.filtros[colKey];
  }
  
  cerrarDropdown(colKey);
  paginaActual = 1;
  guardarEnLocalStorage();
  procesarYRenderizar();
};

window.limpiarFiltroColumna = function(colKey) {
  const input = document.getElementById(`inputFiltro_${colKey}`);
  if (input) input.value = "";
  
  delete estadoColumna.filtros[colKey];
  cerrarDropdown(colKey);
  paginaActual = 1;
  guardarEnLocalStorage();
  procesarYRenderizar();
};

function cerrarDropdown(colKey) {
  const btn = document.getElementById(`btnDrop_${colKey}`);
  if (btn && bootstrap.Dropdown.getInstance(btn)) {
    bootstrap.Dropdown.getInstance(btn).hide();
  }
}

function cerrarDropdowns() {
  document.querySelectorAll(".dropdown-menu.show").forEach(el => el.classList.remove("show"));
}

function procesarYRenderizar() {
  let resultado = [...datosOriginales];

  Object.keys(estadoColumna.filtros).forEach(col => {
    const term = estadoColumna.filtros[col].toLowerCase().trim();
    if (!term) return;

    resultado = resultado.filter(row => {
      const val = String(row[col] || "").toLowerCase().trim();

      if (col === 'status' || term === 'activa' || term === 'inactiva' || term === 'activo' || term === 'inactivo') {
        return val === term;
      }

      return val.includes(term);
    });
  });

  if (estadoColumna.ordenCol) {
    const col = estadoColumna.ordenCol;
    const dir = estadoColumna.ordenDir;

    resultado.sort((a, b) => {
      let valA = String(a[col] || "").toLowerCase().trim();
      let valB = String(b[col] || "").toLowerCase().trim();

      const numA = parseFloat(valA);
      const numB = parseFloat(valB);
      if (!isNaN(numA) && !isNaN(numB)) {
        valA = numA;
        valB = numB;
      }

      if (valA < valB) return dir === 'asc' ? -1 : 1;
      if (valA > valB) return dir === 'asc' ? 1 : -1;
      return 0;
    });
  }

  datosProcesados = resultado;
  actualizarEstilosCabeceras();
  renderizarResultados();
}

function actualizarEstilosCabeceras() {
  document.querySelectorAll("#headersRow th").forEach(th => {
    const colKey = th.getAttribute("data-col");
    const btnMenu = th.querySelector(".btn-col-menu");
    const titleText = th.querySelector(".th-title-text");

    let tieneFiltro = !!estadoColumna.filtros[colKey];
    let tieneOrden = estadoColumna.ordenCol === colKey;

    if (tieneFiltro || tieneOrden) {
      titleText?.classList.add("th-active-state");
      if (btnMenu) btnMenu.style.color = "#0d6efd";
    } else {
      titleText?.classList.remove("th-active-state");
      if (btnMenu) btnMenu.style.color = "#adb5bd";
    }
  });
}

function renderizarResultados() {
  const secMetricas = document.getElementById('seccionMetricasHeader').style.setProperty('display', 'flex', 'important');
  if (secMetricas) secMetricas.style.display = "flex";

  const metricEncontrados = document.getElementById("metricEncontrados");
  if (metricEncontrados) metricEncontrados.textContent = datosOriginales.length;

  const metricFiltrados = document.getElementById("metricFiltrados");
  if (metricFiltrados) metricFiltrados.textContent = datosProcesados.length;

  const secPaginacion = document.getElementById("seccionPaginacion");
  if (secPaginacion) secPaginacion.style.display = datosProcesados.length > 0 ? "block" : "none";

  renderizarPagina();
}

function renderizarPagina() {
  const tbody = document.querySelector("#tablaResultados tbody");
  if (!tbody) return;

  tbody.innerHTML = "";

  if (!datosProcesados || datosProcesados.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="15" class="text-center py-4 text-muted fw-bold">
          No se encontraron registros con los filtros aplicados.
        </td>
      </tr>`;
    actualizarPaginador(0);
    return;
  }

  const inicio = (paginaActual - 1) * registrosPorPagina;
  const fin = Math.min(inicio + registrosPorPagina, datosProcesados.length);
  const paginaData = datosProcesados.slice(inicio, fin);

  paginaData.forEach(row => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.archivo_id || '-'}</td>
      <td><strong>${row.index_code || '-'}</strong></td>
      <td>${row.afiliados || '-'}</td>
      <td>${row.index_member || '-'}</td>
      <td><strong>${row.nombre || '-'}</strong></td>
      <td>${row.dob || '-'}</td>
      <td>${row.estado || '-'}</td>
      <td>${row.numero_venta || '-'}</td>
      <td>${row.confirmado_1 || '-'}</td>
      <td>${row.confirmado_2 || '-'}</td>
      <td>${obtenerBadgeStatus(row.status)}</td>
      <td>${row.cia || '-'}</td>
      <td>${row.ultimo_hs || '-'}</td>
      <td>${row.agente || '-'}</td>
      <td>${row.fecha_llamada || '-'}</td>
    `;
    tbody.appendChild(tr);
  });

  actualizarPaginador(datosProcesados.length, inicio + 1, fin);
}

function actualizarPaginador(totalRegistros, desde = 0, hasta = 0) {
  const infoPaginacion = document.getElementById("infoPaginacion");
  if (infoPaginacion) {
    infoPaginacion.textContent = totalRegistros === 0 
      ? "Mostrando 0 de 0" 
      : `Mostrando ${desde}-${hasta} de ${totalRegistros}`;
  }

  const ulPaginacion = document.getElementById("ulPaginacion");
  if (!ulPaginacion) return;

  ulPaginacion.innerHTML = "";
  const totalPaginas = Math.ceil(totalRegistros / registrosPorPagina);

  if (totalPaginas <= 1) return;

  const liPrev = document.createElement("li");
  liPrev.className = `page-item ${paginaActual === 1 ? "disabled" : ""}`;
  liPrev.innerHTML = `<a class="page-link" href="#">&laquo;</a>`;
  liPrev.addEventListener("click", (e) => {
    e.preventDefault();
    if (paginaActual > 1) {
      paginaActual--;
      guardarEnLocalStorage();
      renderizarPagina();
    }
  });
  ulPaginacion.appendChild(liPrev);

  let inicioPag = Math.max(1, paginaActual - 2);
  let finPag = Math.min(totalPaginas, inicioPag + 4);
  if (finPag - inicioPag < 4) {
    inicioPag = Math.max(1, finPag - 4);
  }

  for (let i = inicioPag; i <= finPag; i++) {
    const li = document.createElement("li");
    li.className = `page-item ${i === paginaActual ? "active" : ""}`;
    li.innerHTML = `<a class="page-link" href="#">${i}</a>`;
    li.addEventListener("click", (e) => {
      e.preventDefault();
      paginaActual = i;
      guardarEnLocalStorage();
      renderizarPagina();
    });
    ulPaginacion.appendChild(li);
  }

  const liNext = document.createElement("li");
  liNext.className = `page-item ${paginaActual === totalPaginas ? "disabled" : ""}`;
  liNext.innerHTML = `<a class="page-link" href="#">&raquo;</a>`;
  liNext.addEventListener("click", (e) => {
    e.preventDefault();
    if (paginaActual < totalPaginas) {
      paginaActual++;
      guardarEnLocalStorage();
      renderizarPagina();
    }
  });
  ulPaginacion.appendChild(liNext);
}

function mostrarSpinner(visible) {
  const spinner = document.getElementById("spinnerCarga");
  if (spinner) spinner.style.display = visible ? "block" : "none";
}