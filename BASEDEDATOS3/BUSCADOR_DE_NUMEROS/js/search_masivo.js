// js/search_masivo.js

let datosOriginalesMasivo = [];
let datosProcesadosMasivo = [];

let paginaActualMasivo = 1;
let registrosPorPaginaMasivo = 20;

let estadoColumnaMasivo = {
    ordenCol: null,
    ordenDir: 'asc',
    filtros: {}
};

document.addEventListener('DOMContentLoaded', () => {
    construirCabecerasDropdownMasivo();
    inicializarVisibilidadColumnasMasivo();

    // Eventos de botones principales
    document.getElementById('btnBuscarMasivo')?.addEventListener('click', () => ejecutarBusquedaMasiva());
    document.getElementById('btnLimpiarBusqueda')?.addEventListener('click', () => limpiarBusquedaMasiva());
    
    // Switch de Registros Únicos
    document.getElementById('chkRegistrosUnicos')?.addEventListener('change', () => {
        paginaActualMasivo = 1;
        procesarYRenderizarMasivo();
    });

    // Selector de Registros por Página
    document.getElementById('selectRegistrosPorPagina')?.addEventListener('change', (e) => {
        registrosPorPaginaMasivo = parseInt(e.target.value, 10) || 20;
        paginaActualMasivo = 1;
        renderizarTablaMasivoDOM();
    });

    restaurarEstadoMasivo();
});

// -------------------------------------------------------------
// HELPERS Y BADGES
// -------------------------------------------------------------
function obtenerBadgeStatusMasivo(status) {
    const statusUpper = (status || "").toUpperCase().trim();
    if (statusUpper === "ACTIVO" || statusUpper === "ACTIVA") {
        return `<span class="badge bg-success">ACTIVO</span>`;
    } else if (statusUpper === "INACTIVO" || statusUpper === "INACTIVA") {
        return `<span class="badge bg-danger">INACTIVO</span>`;
    } else if (statusUpper === "EN PROCESO" || statusUpper === "PROCESO") {
        return `<span class="badge bg-warning text-dark">EN PROCESO</span>`;
    } else {
        return `<span class="badge bg-secondary">${statusUpper || '-'}</span>`;
    }
}

// -------------------------------------------------------------
// PERSISTENCIA DE ESTADO (sessionStorage)
// -------------------------------------------------------------
function guardarEstadoMasivo() {
    const term = document.getElementById('txtMasivo')?.value || '';
    const chkUnicos = document.getElementById('chkRegistrosUnicos')?.checked || false;
    
    const estado = {
        busqueda: term,
        soloUnicos: chkUnicos,
        datosOriginalesMasivo,
        paginaActualMasivo,
        registrosPorPaginaMasivo,
        estadoColumnaMasivo
    };
    sessionStorage.setItem('masivo_search_tab_state', JSON.stringify(estado));
}

function restaurarEstadoMasivo() {
    const guardado = sessionStorage.getItem('masivo_search_tab_state');
    if (!guardado) return;

    try {
        const estado = JSON.parse(guardado);
        if (estado.busqueda) {
            const textarea = document.getElementById('txtMasivo');
            if (textarea) textarea.value = estado.busqueda;

            const chkUnicos = document.getElementById('chkRegistrosUnicos');
            if (chkUnicos) chkUnicos.checked = !!estado.soloUnicos;

            const selectReg = document.getElementById('selectRegistrosPorPagina');
            if (selectReg && estado.registrosPorPaginaMasivo) {
                selectReg.value = estado.registrosPorPaginaMasivo;
                registrosPorPaginaMasivo = estado.registrosPorPaginaMasivo;
            }

            datosOriginalesMasivo = estado.datosOriginalesMasivo || [];
            paginaActualMasivo = estado.paginaActualMasivo || 1;
            estadoColumnaMasivo = estado.estadoColumnaMasivo || { ordenCol: null, ordenDir: 'asc', filtros: {} };

            if (datosOriginalesMasivo.length > 0) {
                procesarYRenderizarMasivo();
            }
        }
    } catch (e) {
        console.error("Error al restaurar estado de búsqueda masiva:", e);
    }
}

window.limpiarBusquedaMasiva = function() {
    sessionStorage.removeItem('masivo_search_tab_state');
    
    const textarea = document.getElementById('txtMasivo');
    if (textarea) textarea.value = '';

    const chkUnicos = document.getElementById('chkRegistrosUnicos');
    if (chkUnicos) chkUnicos.checked = false;

    paginaActualMasivo = 1;
    datosOriginalesMasivo = [];
    datosProcesadosMasivo = [];
    estadoColumnaMasivo = { ordenCol: null, ordenDir: 'asc', filtros: {} };

    document.querySelectorAll("#headersRow input").forEach(i => i.value = "");
    actualizarEstilosCabecerasMasivo();

    // Ocultar métricas y paginación
    const seccionMetricas = document.getElementById('seccionMetricas');
    const seccionPaginacion = document.getElementById('seccionPaginacion');
    if (seccionMetricas) seccionMetricas.style.display = 'none';
    if (seccionPaginacion) seccionPaginacion.style.display = 'none';

    const tbody = document.querySelector('#tablaResultados tbody');
    if (tbody) {
        tbody.innerHTML = `
            <tr id="filaVacia">
                <td colspan="15" class="empty-state">
                    <i class="bi bi-list-check"></i>
                    <h6 class="fw-bold text-dark mb-1">No hay consultas procesadas</h6>
                    <p class="small mb-0">Ingresa la lista de INDEX o Números en el cuadro superior y haz clic en "Procesar Lista Masiva".</p>
                </td>
            </tr>
        `;
    }
};

// -------------------------------------------------------------
// DROPDOWNS Y CABECERAS (FILTRADO & ORDENAMIENTO POR COLUMNA)
// -------------------------------------------------------------
function construirCabecerasDropdownMasivo() {
    const ths = document.querySelectorAll("#headersRow th");

    ths.forEach(th => {
        const colKey = th.getAttribute("data-col");
        const titleSpan = th.querySelector(".th-header-content span");
        const colTitle = titleSpan ? titleSpan.innerText.trim() : colKey;
        
        if (!colKey) return;

        th.innerHTML = `
            <div class="th-header-content position-relative">
                <span class="th-title-text" title="${colTitle}">${colTitle}</span>
                <div class="dropdown d-inline-block">
                    <button class="btn-col-menu" type="button" data-bs-toggle="dropdown" data-bs-auto-close="outside" aria-expanded="false" id="btnDropMasivo_${colKey}">
                        <i class="bi bi-three-dots-vertical"></i>
                    </button>
                    <div class="dropdown-menu dropdown-menu-end p-3 filter-dropdown-menu shadow">
                        <h6 class="dropdown-header px-0 text-white fw-bold border-bottom border-secondary pb-1 mb-2">${colTitle}</h6>
                        
                        <button class="dropdown-item py-1 px-2 rounded small text-light" type="button" onclick="ordenarPorColumnaMasivo('${colKey}', 'asc')">
                            <i class="bi bi-sort-alpha-down me-2 text-primary"></i> Ordenar Ascendente (A-Z)
                        </button>
                        <button class="dropdown-item py-1 px-2 rounded small text-light" type="button" onclick="ordenarPorColumnaMasivo('${colKey}', 'desc')">
                            <i class="bi bi-sort-alpha-up-alt me-2 text-primary"></i> Ordenar Descendente (Z-A)
                        </button>
                        <button class="dropdown-item py-1 px-2 rounded small text-muted" type="button" onclick="limpiarOrdenColumnaMasivo()">
                            <i class="bi bi-x-circle me-2"></i> Quitar Orden
                        </button>

                        <div class="dropdown-divider my-2 border-secondary"></div>

                        <label class="form-label small fw-bold mb-1 text-muted">Filtrar por texto:</label>

                        <div class="input-group input-group-sm mb-2">
                            <input type="text" class="form-control bg-dark text-white border-secondary" id="inputFiltroMasivo_${colKey}" placeholder="Buscar..." value="${estadoColumnaMasivo.filtros[colKey] || ''}" onkeyup="if(event.key==='Enter') aplicarFiltroColumnaMasivo('${colKey}')">
                        </div>
                        <div class="d-flex gap-1">
                            <button class="btn btn-primary btn-sm flex-fill" type="button" onclick="aplicarFiltroColumnaMasivo('${colKey}')">
                                <i class="bi bi-funnel-fill me-1"></i> Filtrar
                            </button>
                            <button class="btn btn-outline-secondary btn-sm flex-fill" type="button" onclick="limpiarFiltroColumnaMasivo('${colKey}')">
                                Limpiar
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    });
}

window.ordenarPorColumnaMasivo = function(colKey, direccion) {
    estadoColumnaMasivo.ordenCol = colKey;
    estadoColumnaMasivo.ordenDir = direccion;
    cerrarDropdownMasivo(colKey);
    procesarYRenderizarMasivo();
};

window.limpiarOrdenColumnaMasivo = function() {
    estadoColumnaMasivo.ordenCol = null;
    cerrarDropdownsMasivo();
    procesarYRenderizarMasivo();
};

window.aplicarFiltroColumnaMasivo = function(colKey) {
    const input = document.getElementById(`inputFiltroMasivo_${colKey}`);
    const val = input ? input.value.trim() : "";

    if (val !== "") {
        estadoColumnaMasivo.filtros[colKey] = val;
    } else {
        delete estadoColumnaMasivo.filtros[colKey];
    }
    
    cerrarDropdownMasivo(colKey);
    paginaActualMasivo = 1;
    procesarYRenderizarMasivo();
};

window.limpiarFiltroColumnaMasivo = function(colKey) {
    const input = document.getElementById(`inputFiltroMasivo_${colKey}`);
    if (input) input.value = "";
    
    delete estadoColumnaMasivo.filtros[colKey];
    cerrarDropdownMasivo(colKey);
    paginaActualMasivo = 1;
    procesarYRenderizarMasivo();
};

function cerrarDropdownMasivo(colKey) {
    const btn = document.getElementById(`btnDropMasivo_${colKey}`);
    if (btn && bootstrap.Dropdown.getInstance(btn)) {
        bootstrap.Dropdown.getInstance(btn).hide();
    }
}

function cerrarDropdownsMasivo() {
    document.querySelectorAll("#headersRow .dropdown-menu.show").forEach(el => el.classList.remove("show"));
}

function actualizarEstilosCabecerasMasivo() {
    document.querySelectorAll("#headersRow th").forEach(th => {
        const colKey = th.getAttribute("data-col");
        const btnMenu = th.querySelector(".btn-col-menu");

        let tieneFiltro = !!estadoColumnaMasivo.filtros[colKey];
        let tieneOrden = estadoColumnaMasivo.ordenCol === colKey;

        if (btnMenu) {
            btnMenu.style.color = (tieneFiltro || tieneOrden) ? "#38bdf8" : "#94a3b8";
        }
    });
}

// -------------------------------------------------------------
// CONTROL VISIBILIDAD DE COLUMNAS (Selector de Columnas / Persistencia localStorage)
// -------------------------------------------------------------
function aplicarVisibilidadColumnaMasivo(colName, isVisible) {
    const ths = document.querySelectorAll(`#tablaResultados th[data-col="${colName}"]`);
    ths.forEach(th => th.classList.toggle('d-none', !isVisible));

    const tds = document.querySelectorAll(`#tablaResultados td[data-col="${colName}"]`);
    tds.forEach(td => td.classList.toggle('d-none', !isVisible));
}

function inicializarVisibilidadColumnasMasivo() {
    const STORAGE_KEY = 'masivo_table_columns_state';
    const savedState = JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
    const checkboxes = document.querySelectorAll('.col-toggle-masivo, .col-toggle');

    checkboxes.forEach(chk => {
        const colName = chk.value;
        if (savedState.hasOwnProperty(colName)) {
            chk.checked = savedState[colName];
        }
        aplicarVisibilidadColumnaMasivo(colName, chk.checked);

        chk.addEventListener('change', (e) => {
            const isChecked = e.target.checked;
            aplicarVisibilidadColumnaMasivo(colName, isChecked);

            const currentState = JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
            currentState[colName] = isChecked;
            localStorage.setItem(STORAGE_KEY, JSON.stringify(currentState));
        });
    });
}

function reaplicarVisibilidadActualMasivo() {
    const checkboxes = document.querySelectorAll('.col-toggle-masivo, .col-toggle');
    checkboxes.forEach(chk => {
        aplicarVisibilidadColumnaMasivo(chk.value, chk.checked);
    });
}

// -------------------------------------------------------------
// BÚSQUEDA SUPABASE
// -------------------------------------------------------------
async function ejecutarBusquedaMasiva() {
    const textarea = document.getElementById('txtMasivo');
    const tbody = document.querySelector('#tablaResultados tbody');
    const spinner = document.getElementById('spinnerCarga');
    
    if (!tbody || !textarea) return;

    const textoEntrada = textarea.value.trim();
    if (!textoEntrada) {
        alert("⚠️ Por favor ingresa al menos un INDEX o Número en el área de texto.");
        return;
    }

    const listaEntrada = textoEntrada
        .split(/[\n,\r\t]+/)
        .map(item => item.trim())
        .filter(item => item.length > 0);

    if (listaEntrada.length === 0) {
        alert("⚠️ No se detectaron valores válidos en la entrada.");
        return;
    }

    if (spinner) spinner.style.display = 'block';

    try {
        // Consulta multitabla/columna a Supabase (busca por index_code, numero_venta, confirmado_1, confirmado_2, etc.)
        const { data, error } = await supabaseClient
            .from('registros_ventas') // Ajusta según el nombre real de tu tabla si difiere
            .select('*')
            .or(`index_code.in.("${listaEntrada.join('","')}"),numero_venta.in.("${listaEntrada.join('","')}"),confirmado_1.in.("${listaEntrada.join('","')}"),confirmado_2.in.("${listaEntrada.join('","')}")`)
            .limit(3000);

        if (error) throw error;

        datosOriginalesMasivo = data || [];
        paginaActualMasivo = 1;

        guardarEstadoMasivo();
        procesarYRenderizarMasivo();

    } catch (err) {
        console.error("Error en búsqueda masiva:", err);
        tbody.innerHTML = `<tr><td colspan="15" class="text-center text-danger py-4">Error al ejecutar la búsqueda: ${err.message}</td></tr>`;
    } finally {
        if (spinner) spinner.style.display = 'none';
    }
}

// -------------------------------------------------------------
// FILTRADO LOCAL Y PROCESAMIENTO
// -------------------------------------------------------------
function procesarYRenderizarMasivo() {
    let resultado = [...datosOriginalesMasivo];

    // 1. Filtrar solo registros únicos (Si está activo el Switch)
    const soloUnicos = document.getElementById('chkRegistrosUnicos')?.checked;
    if (soloUnicos) {
        const mapaUnico = new Map();
        resultado.forEach(row => {
            const clave = row.index_code || row.numero_venta || row.id;
            if (!mapaUnico.has(clave)) {
                mapaUnico.set(clave, row);
            }
        });
        resultado = Array.from(mapaUnico.values());
    }

    // 2. Aplicar Filtros Locales de Dropdown
    Object.keys(estadoColumnaMasivo.filtros).forEach(col => {
        const term = estadoColumnaMasivo.filtros[col].toLowerCase().trim();
        if (!term) return;

        resultado = resultado.filter(row => {
            const val = String(row[col] || "").toLowerCase().trim();
            return val.includes(term);
        });
    });

    // 3. Aplicar Ordenamiento Local
    if (estadoColumnaMasivo.ordenCol) {
        const col = estadoColumnaMasivo.ordenCol;
        const dir = estadoColumnaMasivo.ordenDir;

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

    datosProcesadosMasivo = resultado;
    actualizarEstilosCabecerasMasivo();
    renderizarTablaMasivoDOM();
}

// -------------------------------------------------------------
// RENDERIZADO DOM Y PAGINACIÓN
// -------------------------------------------------------------
function renderizarTablaMasivoDOM() {
    const tbody = document.querySelector('#tablaResultados tbody');
    const seccionMetricas = document.getElementById('seccionMetricas');
    const seccionPaginacion = document.getElementById('seccionPaginacion');
    const metricEncontrados = document.getElementById('metricEncontrados');
    const metricFiltrados = document.getElementById('metricFiltrados');

    if (!tbody) return;
    tbody.innerHTML = '';

    // Actualizar Muestras y Métricas
    if (seccionMetricas) seccionMetricas.style.display = 'flex';
    if (metricEncontrados) metricEncontrados.innerText = datosOriginalesMasivo.length.toLocaleString();
    if (metricFiltrados) metricFiltrados.innerText = datosProcesadosMasivo.length.toLocaleString();

    if (!datosProcesadosMasivo || datosProcesadosMasivo.length === 0) {
        tbody.innerHTML = '<tr><td colspan="15" class="text-center text-muted py-4">No se encontraron registros para los criterios especificados.</td></tr>';
        if (seccionPaginacion) seccionPaginacion.style.display = 'none';
        return;
    }

    if (seccionPaginacion) seccionPaginacion.style.display = 'flex';

    // Paginación Matemáticas
    const totalPaginas = Math.ceil(datosProcesadosMasivo.length / registrosPorPaginaMasivo) || 1;
    if (paginaActualMasivo > totalPaginas) paginaActualMasivo = totalPaginas;

    const inicio = (paginaActualMasivo - 1) * registrosPorPaginaMasivo;
    const fin = Math.min(inicio + registrosPorPaginaMasivo, datosProcesadosMasivo.length);
    const paginaData = datosProcesadosMasivo.slice(inicio, fin);

    // Texto descriptivo "Mostrando X-Y de Z"
    const infoPaginacion = document.getElementById('infoPaginacion');
    if (infoPaginacion) {
        infoPaginacion.innerText = `Mostrando ${inicio + 1}-${fin} de ${datosProcesadosMasivo.length}`;
    }

    const fragmento = document.createDocumentFragment();

    paginaData.forEach(m => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td data-col="archivo_id" class="text-muted small">${m.archivo_id || '-'}</td>
            <td data-col="index_code" class="fw-bold text-primary">${m.index_code || '-'}</td>
            <td data-col="afiliados">${m.afiliados || '-'}</td>
            <td data-col="index_member">${m.index_member || '-'}</td>
            <td data-col="nombre" class="fw-bold text-dark text-start">${m.nombre || '-'}</td>
            <td data-col="dob">${m.dob || '-'}</td>
            <td data-col="estado"><span class="badge bg-secondary">${m.estado || '-'}</span></td>
            <td data-col="numero_venta" class="fw-semibold">${m.numero_venta || '-'}</td>
            <td data-col="confirmado_1">${m.confirmado_1 || '-'}</td>
            <td data-col="confirmado_2">${m.confirmado_2 || '-'}</td>
            <td data-col="status">${obtenerBadgeStatusMasivo(m.status)}</td>
            <td data-col="cia"><span class="badge bg-primary-subtle text-primary border border-primary-subtle">${m.cia || m.compania || '-'}</span></td>
            <td data-col="ultimo_hs">${m.ultimo_hs || '-'}</td>
            <td data-col="agente">${m.agente || m.asesor || '-'}</td>
            <td data-col="fecha_llamada" class="text-muted small">${m.fecha_llamada || '-'}</td>
        `;
        fragmento.appendChild(tr);
    });

    tbody.appendChild(fragmento);
    
    renderizarControlesPaginacion(totalPaginas);
    reaplicarVisibilidadActualMasivo();
}

function renderizarControlesPaginacion(totalPaginas) {
    const ulPaginacion = document.getElementById('ulPaginacion');
    if (!ulPaginacion) return;

    ulPaginacion.innerHTML = '';

    // Botón Anterior
    const liPrev = document.createElement('li');
    liPrev.className = `page-item ${paginaActualMasivo === 1 ? 'disabled' : ''}`;
    liPrev.innerHTML = `<a class="page-link" href="#" onclick="event.preventDefault(); cambiarPaginaMasivo(-1);">&laquo;</a>`;
    ulPaginacion.appendChild(liPrev);

    // Páginas numéricas
    for (let i = 1; i <= totalPaginas; i++) {
        if (i === 1 || i === totalPaginas || (i >= paginaActualMasivo - 1 && i <= paginaActualMasivo + 1)) {
            const li = document.createElement('li');
            li.className = `page-item ${paginaActualMasivo === i ? 'active' : ''}`;
            li.innerHTML = `<a class="page-link" href="#" onclick="event.preventDefault(); irAPaginaMasivo(${i});">${i}</a>`;
            ulPaginacion.appendChild(li);
        } else if (i === paginaActualMasivo - 2 || i === paginaActualMasivo + 2) {
            const li = document.createElement('li');
            li.className = 'page-item disabled';
            li.innerHTML = `<span class="page-link">...</span>`;
            ulPaginacion.appendChild(li);
        }
    }

    // Botón Siguiente
    const liNext = document.createElement('li');
    liNext.className = `page-item ${paginaActualMasivo === totalPaginas ? 'disabled' : ''}`;
    liNext.innerHTML = `<a class="page-link" href="#" onclick="event.preventDefault(); cambiarPaginaMasivo(1);">&raquo;</a>`;
    ulPaginacion.appendChild(liNext);
}

// -------------------------------------------------------------
// EVENTOS DE PAGINACIÓN LOCAL
// -------------------------------------------------------------
window.cambiarPaginaMasivo = function(delta) {
    const totalPaginas = Math.ceil(datosProcesadosMasivo.length / registrosPorPaginaMasivo) || 1;
    const nuevaPagina = paginaActualMasivo + delta;

    if (nuevaPagina >= 1 && nuevaPagina <= totalPaginas) {
        paginaActualMasivo = nuevaPagina;
        guardarEstadoMasivo();
        renderizarTablaMasivoDOM();
    }
};

window.irAPaginaMasivo = function(numPagina) {
    paginaActualMasivo = numPagina;
    guardarEstadoMasivo();
    renderizarTablaMasivoDOM();
};