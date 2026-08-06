// js/cross_project_search.js

// Variables globales de Paginación y Datos
let datosCruzadosGlobales = [];
let datosFiltradosCruzados = [];
let paginaActual = 1;
const registrosPorPagina = 15;

// Helper para dar formato visual (badges) a los estados
function renderStatusBadge(statusText) {
    if (!statusText || statusText === '-' || statusText === 'N/A') {
        return `<span class="badge bg-secondary text-light">-</span>`;
    }

    const textUpper = String(statusText).toUpperCase().trim();

    // Casos Activo / Vigente / Aprobado (Verde)
    if (textUpper.includes('ACTIVO') || textUpper.includes('ACTIVE') || textUpper.includes('APROBADO') || textUpper.includes('EFFECTIVE') || textUpper.includes('VIGENTE')) {
        return `<span class="badge bg-success-subtle text-success border border-success-subtle"><i class="bi bi-check-circle-fill me-1"></i>${statusText}</span>`;
    }

    // Casos Cancelado / Terminado / Inactivo (Rojo)
    if (textUpper.includes('CANCEL') || textUpper.includes('TERMINAT') || textUpper.includes('INACTIVO') || textUpper.includes('RECHAZADO') || textUpper.includes('DISENROLLED')) {
        return `<span class="badge bg-danger-subtle text-danger border border-danger-subtle"><i class="bi bi-x-circle-fill me-1"></i>${statusText}</span>`;
    }

    // Casos Pendiente / En proceso (Amarillo/Naranja)
    if (textUpper.includes('PEND') || textUpper.includes('PROCESO') || textUpper.includes('REVISION') || textUpper.includes('SUBMITTED')) {
        return `<span class="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle"><i class="bi bi-clock-history me-1"></i>${statusText}</span>`;
    }

    // Por defecto (Azul/Gris)
    return `<span class="badge bg-info-subtle text-info-emphasis border border-info-subtle">${statusText}</span>`;
}

// Inicialización de escuchadores al cargar el DOM
document.addEventListener('DOMContentLoaded', () => {
    // Escuchar cambios en los checkboxes de visualización de columnas
    document.querySelectorAll('.col-toggle-cruzado').forEach(checkbox => {
        checkbox.addEventListener('change', aplicarVisibilidadColumnasCruzado);
    });

    // Escuchar el checkbox maestro "Seleccionar Todos"
    const checkAll = document.getElementById('check-all-cruzado');
    if (checkAll) {
        checkAll.addEventListener('change', (e) => {
            toggleSelectAllCruzado(e.target);
        });
    }

    // Permitir búsqueda al presionar Enter en el input individual
    const inputIndividual = document.getElementById('txt-busqueda-cruzada');
    if (inputIndividual) {
        inputIndividual.addEventListener('keyup', (e) => {
            if (e.key === 'Enter') ejecutarBusquedaCruzada();
        });
    }

    // Filtros Rápidos en Pantalla
    const quickInput = document.getElementById('quick-filter-input');
    const quickStatus = document.getElementById('quick-filter-status');
    const btnClearQuick = document.getElementById('btn-clear-quick-filters');

    quickInput?.addEventListener('input', aplicarFiltrosRapidos);
    quickStatus?.addEventListener('change', aplicarFiltrosRapidos);
    btnClearQuick?.addEventListener('click', () => {
        if (quickInput) quickInput.value = '';
        if (quickStatus) quickStatus.value = '';
        aplicarFiltrosRapidos();
    });
});

// 1. BÚSQUEDA INDIVIDUAL
async function ejecutarBusquedaCruzada() {
    const input = document.getElementById('txt-busqueda-cruzada');
    const tbody = document.getElementById('tbody-cruzado');

    if (!input || !tbody) return;

    const term = input.value.trim();
    if (!term) {
        alert("⚠️ Ingresa un término para realizar la búsqueda.");
        return;
    }

    tbody.innerHTML = '<tr><td colspan="16" class="text-center text-muted py-4"><div class="spinner-border spinner-border-sm text-primary me-2"></div>Buscando coincidencias...</td></tr>';

    try {
        const client = typeof supabaseVentas !== 'undefined' ? supabaseVentas : supabaseClient;
        const { data, error } = await client
            .from('coincidencias_ventas_miembros')
            .select('*')
            .or(`nombres.ilike.%${term}%,id_member.ilike.%${term}%,index_code.ilike.%${term}%`)
            .limit(1000);

        if (error) throw error;

        datosCruzadosGlobales = data || [];
        poblarOpcionesStatusQuick();
        aplicarFiltrosRapidos();

    } catch (err) {
        console.error("Error al buscar:", err);
        tbody.innerHTML = `<tr><td colspan="16" class="text-center text-danger py-4">Error al realizar la consulta: ${err.message}</td></tr>`;
    }
}

// 2. BÚSQUEDA MASIVA
async function ejecutarBusquedaCruzadaMasiva() {
    const textarea = document.getElementById('txt-busqueda-masiva-cruzada');
    const tbody = document.getElementById('tbody-cruzado');

    if (!textarea || !tbody) return;

    const terminosRaw = textarea.value.split('\n').map(t => t.trim()).filter(t => t.length > 0);
    const terminos = [...new Set(terminosRaw)];

    if (terminos.length === 0) {
        alert("⚠️ Por favor pega al menos un término para buscar.");
        return;
    }

    tbody.innerHTML = `<tr><td colspan="16" class="text-center text-muted py-4"><div class="spinner-border spinner-border-sm text-primary me-2"></div>Consultando ${terminos.length} códigos/nombres...</td></tr>`;

    try {
        let resultadosTotales = [];
        const mapaUnicos = new Map();

        const tamanoBloque = 5;
        const client = typeof supabaseVentas !== 'undefined' ? supabaseVentas : supabaseClient;

        for (let i = 0; i < terminos.length; i += tamanoBloque) {
            const bloque = terminos.slice(i, i + tamanoBloque);
            
            const condiciones = [];
            bloque.forEach(t => {
                const termLimpio = t.replace(/[,()]/g, '');
                if (termLimpio) {
                    condiciones.push(`index_code.eq.${termLimpio}`);
                    condiciones.push(`id_member.eq.${termLimpio}`);
                    condiciones.push(`nombres.ilike.%${termLimpio}%`);
                }
            });

            if (condiciones.length > 0) {
                const { data, error } = await client
                    .from('coincidencias_ventas_miembros')
                    .select('*')
                    .or(condiciones.join(','));

                if (error) throw error;

                if (data) {
                    data.forEach(item => {
                        const key = item.id ? String(item.id) : `${item.index_code}_${item.id_member}`;
                        if (!mapaUnicos.has(key)) {
                            mapaUnicos.set(key, item);
                            resultadosTotales.push(item);
                        }
                    });
                }
            }
        }

        datosCruzadosGlobales = resultadosTotales;
        poblarOpcionesStatusQuick();
        aplicarFiltrosRapidos();

    } catch (err) {
        console.error("Error en búsqueda masiva:", err);
        tbody.innerHTML = `<tr><td colspan="16" class="text-center text-danger py-4">Error en búsqueda masiva: ${err.message}</td></tr>`;
    }
}

// 3. FILTROS RÁPIDOS Y DINÁMICOS
function poblarOpcionesStatusQuick() {
    const selectStatus = document.getElementById('quick-filter-status');
    if (!selectStatus) return;

    const statuses = new Set();
    datosCruzadosGlobales.forEach(item => {
        if (item.status_venta) statuses.add(item.status_venta);
        if (item.status_miembro) statuses.add(item.status_miembro);
    });

    selectStatus.innerHTML = '<option value="">Status: Todos</option>';
    statuses.forEach(st => {
        const opt = document.createElement('option');
        opt.value = st;
        opt.textContent = st;
        selectStatus.appendChild(opt);
    });
}

function aplicarFiltrosRapidos() {
    const qText = document.getElementById('quick-filter-input')?.value.toLowerCase().trim() || '';
    const qStatus = document.getElementById('quick-filter-status')?.value.toLowerCase().trim() || '';

    datosFiltradosCruzados = datosCruzadosGlobales.filter(item => {
        const matchText = !qText || 
            (item.nombres && item.nombres.toLowerCase().includes(qText)) ||
            (item.id_member && item.id_member.toLowerCase().includes(qText)) ||
            (item.index_code && item.index_code.toLowerCase().includes(qText)) ||
            (item.compania && item.compania.toLowerCase().includes(qText));

        const matchStatus = !qStatus || 
            (item.status_venta && item.status_venta.toLowerCase() === qStatus) ||
            (item.status_miembro && item.status_miembro.toLowerCase() === qStatus);

        return matchText && matchStatus;
    });

    paginaActual = 1;
    renderizarTablaConPaginacion();
}

// 4. GENERADOR DE FILAS CON ACCIONES
function renderizarFilaCruzada(row) {
    if (!row) return '';

    const rowId = row.id ? row.id : `${row.index_code}_${row.id_member}`;
    const safeId = String(row.id || '').replace(/'/g, "\\'");
    const safeIndex = String(row.index_code || '').replace(/'/g, "\\'");
    const safeMember = String(row.id_member || '').replace(/'/g, "\\'");

    return `
      <tr data-json="${JSON.stringify(row).replace(/"/g, '&quot;')}">
        <td data-col="select">
          <input type="checkbox" class="check-row-cruzado" value="${rowId}">
        </td>
        <td data-col="index_code">${row.index_code || '-'}</td>
        <td data-col="id_member">${row.id_member || '-'}</td>
        <td data-col="nombres" class="text-start fw-semibold">${row.nombres || '-'}</td>
        <td data-col="estado">${row.estado || '-'}</td>
        <td data-col="compania">${row.compania || '-'}</td>
        <td data-col="status_venta">${renderStatusBadge(row.status_venta)}</td>
        <td data-col="status_miembro">${renderStatusBadge(row.status_miembro)}</td>

        <!-- Columnas secundarias -->
        <td data-col="numero_venta" class="d-none">${row.numero_venta || '-'}</td>
        <td data-col="numero_confirmado_1" class="d-none">${row.numero_confirmado_1 || '-'}</td>
        <td data-col="afiliados" class="d-none">${row.afiliados || '-'}</td>
        <td data-col="dob" class="d-none">${row.dob || '-'}</td>
        <td data-col="ultimo_hs" class="d-none">${row.ultimo_hs || '-'}</td>
        <td data-col="plan" class="d-none">${row.plan || '-'}</td>
        <td data-col="agente" class="d-none">${row.agente || '-'}</td>
        
        <!-- COLUMNA ACCIONES -->
        <td data-col="acciones" class="text-center align-middle">
          <button type="button" class="btn btn-sm btn-outline-info py-0 px-2 shadow-sm" onclick="verDetalleCruzado('${safeId}', '${safeIndex}', '${safeMember}')" title="Ver Detalle">
            <i class="bi bi-info-circle"></i>
          </button>
        </td>
      </tr>
    `;
}

// 5. RENDERIZADO DE TABLA Y CONTADOR CON PAGINACIÓN
function renderizarTablaConPaginacion() {
    const tbody = document.getElementById('tbody-cruzado');
    const badge = document.getElementById('badge-coincidencias-count');
    const infoPaginacion = document.getElementById('info-paginacion');
    const ulPaginacion = document.getElementById('ul-paginacion');
    const checkAll = document.getElementById('check-all-cruzado');

    if (checkAll) checkAll.checked = false;
    if (!tbody) return;

    const dataset = datosFiltradosCruzados.length > 0 || (document.getElementById('quick-filter-input')?.value || document.getElementById('quick-filter-status')?.value)
        ? datosFiltradosCruzados 
        : datosCruzadosGlobales;

    const totalRegistros = dataset.length;

    if (badge) badge.innerText = `${totalRegistros} coincidencias`;

    if (totalRegistros === 0) {
        tbody.innerHTML = '<tr><td colspan="16" class="text-center text-muted py-4">No se encontraron coincidencias.</td></tr>';
        if (infoPaginacion) infoPaginacion.innerText = 'Mostrando 0 de 0 registros';
        if (ulPaginacion) ulPaginacion.innerHTML = '';
        if (typeof renderizarTarjetasCruzadas === 'function') renderizarTarjetasCruzadas();
        return;
    }

    const totalPaginas = Math.ceil(totalRegistros / registrosPorPagina);
    if (paginaActual > totalPaginas) paginaActual = totalPaginas;

    const inicio = (paginaActual - 1) * registrosPorPagina;
    const fin = Math.min(inicio + registrosPorPagina, totalRegistros);
    const paginaDatos = dataset.slice(inicio, fin);

    tbody.innerHTML = paginaDatos.map(item => renderizarFilaCruzada(item)).join('');

    if (infoPaginacion) {
        infoPaginacion.innerText = `Mostrando ${inicio + 1} a ${fin} de ${totalRegistros} registros`;
    }

    if (ulPaginacion) {
        let pagHTML = '';

        pagHTML += `
            <li class="page-item ${paginaActual === 1 ? 'disabled' : ''}">
                <button class="page-link" onclick="cambiarPaginaCruzada(${paginaActual - 1})">Anterior</button>
            </li>
        `;

        const maxBotones = 5;
        let pagInicio = Math.max(1, paginaActual - Math.floor(maxBotones / 2));
        let pagFin = Math.min(totalPaginas, pagInicio + maxBotones - 1);

        if (pagFin - pagInicio < maxBotones - 1) {
            pagInicio = Math.max(1, pagFin - maxBotones + 1);
        }

        for (let p = pagInicio; p <= pagFin; p++) {
            pagHTML += `
                <li class="page-item ${p === paginaActual ? 'active' : ''}">
                    <button class="page-link" onclick="cambiarPaginaCruzada(${p})">${p}</button>
                </li>
            `;
        }

        pagHTML += `
            <li class="page-item ${paginaActual === totalPaginas ? 'disabled' : ''}">
                <button class="page-link" onclick="cambiarPaginaCruzada(${paginaActual + 1})">Siguiente</button>
            </li>
        `;

        ulPaginacion.innerHTML = pagHTML;
    }

    aplicarVisibilidadColumnasCruzado();

    if (typeof vistaCruzada !== 'undefined' && vistaCruzada === 'cards' && typeof renderizarTarjetasCruzadas === 'function') {
        renderizarTarjetasCruzadas();
    }
}

// 6. SELECCIÓN DE CHECKBOXES
function toggleSelectAllCruzado(masterCheckbox) {
    const checkboxes = document.querySelectorAll('.check-row-cruzado');
    checkboxes.forEach(cb => {
        cb.checked = masterCheckbox.checked;
    });
}

function obtenerSeleccionadosCruzados() {
    const checkboxes = document.querySelectorAll('.check-row-cruzado:checked');
    return Array.from(checkboxes).map(cb => cb.value);
}

// 7. VISIBILIDAD DE COLUMNAS
function aplicarVisibilidadColumnasCruzado() {
    const checkboxes = document.querySelectorAll('.col-toggle-cruzado');
    
    if (checkboxes.length > 0) {
        checkboxes.forEach(checkbox => {
            const colKey = checkbox.value;
            if (colKey === 'acciones') return;
            
            const visible = checkbox.checked;
            document.querySelectorAll(`[data-col="${colKey}"]`).forEach(elem => {
                elem.style.display = visible ? '' : 'none';
            });
        });
    }

    document.querySelectorAll('[data-col="acciones"], [data-col="select"]').forEach(elem => {
        elem.style.display = '';
    });
}

function cambiarPaginaCruzada(nuevaPagina) {
    const dataset = datosFiltradosCruzados.length > 0 ? datosFiltradosCruzados : datosCruzadosGlobales;
    const totalPaginas = Math.ceil(dataset.length / registrosPorPagina);
    if (nuevaPagina >= 1 && nuevaPagina <= totalPaginas) {
        paginaActual = nuevaPagina;
        renderizarTablaConPaginacion();
    }
}

function limpiarBusquedaCruzada() {
    const input = document.getElementById('txt-busqueda-cruzada');
    if (input) input.value = '';
    datosCruzadosGlobales = [];
    datosFiltradosCruzados = [];
    paginaActual = 1;
    renderizarTablaConPaginacion();
}

function limpiarBusquedaCruzadaMasiva() {
    const textarea = document.getElementById('txt-busqueda-masiva-cruzada');
    if (textarea) textarea.value = '';
    limpiarBusquedaCruzada();
}

// 8. MODALES Y ACCIONES

function verDetalleCruzado(idRecord, indexCode, idMember) {
    let registro = null;

    if (idRecord && idRecord !== 'undefined' && idRecord !== 'null') {
        registro = datosCruzadosGlobales.find(r => String(r.id) === String(idRecord));
    }
    
    if (!registro) {
        registro = datosCruzadosGlobales.find(
            r => String(r.index_code) === String(indexCode) && String(r.id_member) === String(idMember)
        );
    }

    if (!registro) {
        alert("⚠️ No se encontró la información detallada de este registro.");
        return;
    }

    abrirModalDetalle(registro);
}

function abrirModalDetalle(data) {
    // Llenado Datos de Ventas
    if (document.getElementById('det-v-index')) document.getElementById('det-v-index').innerText = data.index_code || 'N/A';
    if (document.getElementById('det-v-nombres')) document.getElementById('det-v-nombres').innerText = data.nombres || 'N/A';
    if (document.getElementById('det-v-estado')) document.getElementById('det-v-estado').innerText = data.estado || 'N/A';
    if (document.getElementById('det-v-compania')) document.getElementById('det-v-compania').innerText = data.compania || 'N/A';
    if (document.getElementById('det-v-status')) document.getElementById('det-v-status').innerHTML = renderStatusBadge(data.status_venta);
    if (document.getElementById('det-v-num-venta')) document.getElementById('det-v-num-venta').innerText = data.numero_venta || 'N/A';
    if (document.getElementById('det-v-confirmado')) document.getElementById('det-v-confirmado').innerText = data.numero_confirmado_1 || 'N/A';
    if (document.getElementById('det-v-afiliados')) document.getElementById('det-v-afiliados').innerText = data.afiliados || 'N/A';
    if (document.getElementById('det-v-dob')) document.getElementById('det-v-dob').innerText = data.dob || 'N/A';
    if (document.getElementById('det-v-ultimo-hs')) document.getElementById('det-v-ultimo-hs').innerText = data.ultimo_hs || 'N/A';

    // Llenado Datos de Miembros
    if (document.getElementById('det-m-id')) document.getElementById('det-m-id').innerText = data.id_member || 'N/A';
    if (document.getElementById('det-m-nombres')) document.getElementById('det-m-nombres').innerText = data.nombres || 'N/A';
    if (document.getElementById('det-m-estado')) document.getElementById('det-m-estado').innerText = data.estado || 'N/A';
    if (document.getElementById('det-m-compania')) document.getElementById('det-m-compania').innerText = data.compania || 'N/A';
    if (document.getElementById('det-m-status')) document.getElementById('det-m-status').innerHTML = renderStatusBadge(data.status_miembro);
    if (document.getElementById('det-m-plan')) document.getElementById('det-m-plan').innerText = data.plan || 'N/A';
    if (document.getElementById('det-m-agente')) document.getElementById('det-m-agente').innerText = data.agente || 'N/A';

    const modalElem = document.getElementById('modalDetalleRegistro');
    if (modalElem) {
        const modal = bootstrap.Modal.getOrCreateInstance(modalElem);
        modal.show();
    } else {
        alert("⚠️ No se encontró la estructura HTML del modal de detalle.");
    }
}

function editarSeleccionadoCruzado() {
    const seleccionados = obtenerSeleccionadosCruzados();
    
    if (seleccionados.length === 0) {
        alert("⚠️ Por favor selecciona un registro utilizando el checkbox para editar.");
        return;
    }
    
    if (seleccionados.length > 1) {
        alert("⚠️ Por favor selecciona solo UN registro a la vez para editar.");
        return;
    }

    const idSeleccionado = seleccionados[0];
    const item = datosCruzadosGlobales.find(d => 
        String(d.id) === String(idSeleccionado) || `${d.index_code}_${d.id_member}` === String(idSeleccionado)
    );

    if (!item) {
        alert("⚠️ No se encontró la información del registro seleccionado.");
        return;
    }

    if (document.getElementById('edit-id-coincidencia')) document.getElementById('edit-id-coincidencia').value = item.id || '';
    if (document.getElementById('edit-nombres')) document.getElementById('edit-nombres').value = item.nombres || '';
    if (document.getElementById('edit-estado')) document.getElementById('edit-estado').value = item.estado || '';
    if (document.getElementById('edit-compania')) document.getElementById('edit-compania').value = item.compania || '';
    if (document.getElementById('edit-status-venta')) document.getElementById('edit-status-venta').value = item.status_venta || '';
    if (document.getElementById('edit-status-miembro')) document.getElementById('edit-status-miembro').value = item.status_miembro || '';
    if (document.getElementById('edit-numero-venta')) document.getElementById('edit-numero-venta').value = item.numero_venta || '';
    if (document.getElementById('edit-confirmado')) document.getElementById('edit-confirmado').value = item.numero_confirmado_1 || '';
    if (document.getElementById('edit-afiliados')) document.getElementById('edit-afiliados').value = item.afiliados || '';
    if (document.getElementById('edit-dob')) document.getElementById('edit-dob').value = item.dob || '';
    if (document.getElementById('edit-ultimo-hs')) document.getElementById('edit-ultimo-hs').value = item.ultimo_hs || '';
    if (document.getElementById('edit-plan')) document.getElementById('edit-plan').value = item.plan || '';
    if (document.getElementById('edit-agente')) document.getElementById('edit-agente').value = item.agente || '';

    const modalElem = document.getElementById('modalEditarRegistro');
    if (modalElem) {
        const modal = bootstrap.Modal.getOrCreateInstance(modalElem);
        modal.show();
    } else {
        alert("⚠️ No se encontró la estructura HTML del modal de edición.");
    }
}

async function guardarEdicionCruzada() {
    const idRecord = document.getElementById('edit-id-coincidencia').value;
    if (!idRecord) {
        alert("⚠️ El registro no tiene un ID primario válido para actualizar en la base de datos.");
        return;
    }

    const payload = {
        nombres: document.getElementById('edit-nombres')?.value || null,
        estado: document.getElementById('edit-estado')?.value || null,
        compania: document.getElementById('edit-compania')?.value || null,
        status_venta: document.getElementById('edit-status-venta')?.value || null,
        status_miembro: document.getElementById('edit-status-miembro')?.value || null,
        numero_venta: document.getElementById('edit-numero-venta')?.value || null,
        numero_confirmado_1: document.getElementById('edit-confirmado')?.value || null,
        afiliados: document.getElementById('edit-afiliados')?.value || null,
        dob: document.getElementById('edit-dob')?.value || null,
        ultimo_hs: document.getElementById('edit-ultimo-hs')?.value || null,
        plan: document.getElementById('edit-plan')?.value || null,
        agente: document.getElementById('edit-agente')?.value || null
    };

    try {
        const client = typeof supabaseVentas !== 'undefined' ? supabaseVentas : supabaseClient;
        const { error } = await client
            .from('coincidencias_ventas_miembros')
            .update(payload)
            .eq('id', idRecord);

        if (error) throw error;

        if (typeof mostrarToast === 'function') mostrarToast("Registro actualizado con éxito");
        else alert("✅ Registro actualizado con éxito.");

        const modalElem = document.getElementById('modalEditarRegistro');
        if (modalElem) {
            const modalObj = bootstrap.Modal.getInstance(modalElem);
            if (modalObj) modalObj.hide();
        }

        const index = datosCruzadosGlobales.findIndex(d => String(d.id) === String(idRecord));
        if (index !== -1) {
            datosCruzadosGlobales[index] = { ...datosCruzadosGlobales[index], ...payload };
            aplicarFiltrosRapidos();
        }

    } catch (err) {
        alert("Error al actualizar: " + err.message);
    }
}

async function eliminarSeleccionadosCruzados() {
    const seleccionados = obtenerSeleccionadosCruzados();

    if (seleccionados.length === 0) {
        alert("⚠️ Por favor selecciona al menos un registro para eliminar.");
        return;
    }

    if (confirm(`¿Estás seguro de que deseas eliminar los ${seleccionados.length} registros seleccionados?`)) {
        try {
            const client = typeof supabaseVentas !== 'undefined' ? supabaseVentas : supabaseClient;
            const { error } = await client
                .from('coincidencias_ventas_miembros')
                .delete()
                .in('id', seleccionados);

            if (error) throw error;

            if (typeof mostrarToast === 'function') mostrarToast(`${seleccionados.length} registros eliminados`);
            else alert("✅ Registros eliminados con éxito.");

            datosCruzadosGlobales = datosCruzadosGlobales.filter(item => !seleccionados.includes(String(item.id)));
            aplicarFiltrosRapidos();

        } catch (err) {
            alert("Error al eliminar los registros: " + err.message);
        }
    }
}

// 9. EXPORTACIÓN A EXCEL (.xlsx) Y CSV (.csv)
function exportarTablaCruzada(tipo = 'excel') {
    const dataset = datosFiltradosCruzados.length > 0 ? datosFiltradosCruzados : datosCruzadosGlobales;

    if (!dataset || dataset.length === 0) {
        alert("⚠️ No hay datos para exportar.");
        return;
    }

    // 1. Filtrar si hay elementos seleccionados o exportar todos
    const seleccionados = obtenerSeleccionadosCruzados();
    let datosAExportar = [];

    if (seleccionados.length > 0) {
        datosAExportar = dataset.filter(r => {
            const rowId = r.id ? String(r.id) : `${r.index_code}_${r.id_member}`;
            return seleccionados.includes(rowId);
        });
    } else {
        datosAExportar = dataset;
    }

    // 2. Mapear datos a un formato limpio con encabezados claros
    const datosMapeados = datosAExportar.map(r => ({
        "ID": r.id || '',
        "INDEX CODE": r.index_code || '',
        "ID MEMBER": r.id_member || '',
        "NOMBRES": r.nombres || '',
        "ESTADO": r.estado || '',
        "COMPAÑÍA": r.compania || '',
        "STATUS VENTA": r.status_venta || '',
        "STATUS MIEMBRO": r.status_miembro || '',
        "Nº VENTA": r.numero_venta || '',
        "CONFIRMADO 1": r.numero_confirmado_1 || '',
        "AFILIADOS": r.afiliados || '',
        "DOB": r.dob || '',
        "ÚLTIMO HS": r.ultimo_hs || '',
        "PLAN": r.plan || '',
        "AGENTE": r.agente || ''
    }));

    const fechaStr = new Date().toISOString().slice(0, 10);
    const sufijo = seleccionados.length > 0 ? `_seleccionados_${seleccionados.length}` : '_todos';

    // 3. EXPORTAR A EXCEL REAL (.xlsx)
    if (tipo === 'excel') {
        if (typeof XLSX === 'undefined') {
            alert("⚠️ La librería XLSX no está cargada. Por favor agrega el script CDN de SheetJS en tu HTML.");
            return;
        }

        const worksheet = XLSX.utils.json_to_sheet(datosMapeados);
        const workbook = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(workbook, worksheet, "Coincidencias");

        const maxCols = Object.keys(datosMapeados[0] || {}).map(key => ({
            wch: Math.max(key.length + 3, 15)
        }));
        worksheet['!cols'] = maxCols;

        XLSX.writeFile(workbook, `coincidencias_cruzadas${sufijo}_${fechaStr}.xlsx`);
    } 
    // 4. EXPORTAR A CSV (.csv)
    else {
        const headers = Object.keys(datosMapeados[0] || []);
        const rows = datosMapeados.map(obj => 
            headers.map(header => `"${String(obj[header] || '').replace(/"/g, '""')}"`).join(",")
        );

        const csvContent = "data:text/csv;charset=utf-8,\uFEFF" 
            + [headers.join(","), ...rows].join("\n");

        const encodedUri = encodeURI(csvContent);
        const link = document.createElement("a");
        link.setAttribute("href", encodedUri);
        link.setAttribute("download", `coincidencias_cruzadas${sufijo}_${fechaStr}.csv`);
        
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }
}

// Alias por compatibilidad
function exportarResultadosCruzadosCSV() {
    exportarTablaCruzada('csv');
}