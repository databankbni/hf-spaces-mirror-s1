// js/database_tab.js

let paginaActual = 1;
let registrosPorPagina = 15;
let totalRegistros = 0;

document.addEventListener("DOMContentLoaded", () => {
  cargarBaseDatosPaginated();
});

/**
 * Consulta por Rango a Supabase (mantiene tus 15 columnas y conteo exacto)
 */
async function cargarBaseDatosPaginated() {
  mostrarSpinner(true);

  // Calculamos el rango exacto para la consulta en Supabase
  const desde = (paginaActual - 1) * registrosPorPagina;
  const hasta = desde + registrosPorPagina - 1;

  try {
    const { data, count, error } = await supabaseClient
      .from('registros_ventas')
      .select('*', { count: 'exact' })
      .range(desde, hasta);

    if (error) throw error;

    totalRegistros = count || 0;
    const totalPaginas = Math.ceil(totalRegistros / registrosPorPagina) || 1;
    
    // Actualizar Badge del total global
    const badge = document.getElementById("totalRegistrosBadge");
    if (badge) badge.textContent = `${totalRegistros.toLocaleString('es-ES')} Registros`;

    // Renderizar los datos de las 15 columnas
    renderizarTabla(data || []);

    // Actualizar los controles visuales del HTML
    actualizarControlesPaginacion(desde + 1, Math.min(hasta + 1, totalRegistros), totalPaginas);

  } catch (err) {
    console.error("Error al obtener la base de datos:", err);
  } finally {
    mostrarSpinner(false);
  }
}

/**
 * Renderizado de filas respetando la estructura de la tabla
 */
function renderizarTabla(datos) {
  const tbody = document.querySelector("#tablaBaseDatos tbody");
  if (!tbody) return;

  tbody.innerHTML = "";

  if (datos.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="15" class="text-center py-4 text-muted fw-bold">
          No hay datos disponibles en la base de datos.
        </td>
      </tr>`;
    return;
  }

  datos.forEach(row => {
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
      <td><span class="badge bg-${(row.status||'').toUpperCase()==='ACTIVA'?'success':'secondary'}">${row.status || '-'}</span></td>
      <td>${row.cia || '-'}</td>
      <td>${row.ultimo_hs || '-'}</td>
      <td>${row.agente || '-'}</td>
      <td>${row.fecha_llamada || '-'}</td>
    `;
    tbody.appendChild(tr);
  });
}

/**
 * Actualiza los elementos del DOM de la barra de paginación
 */
function actualizarControlesPaginacion(desde, hasta, totalPaginas) {
  // 1. Texto de información (Mostrando X-Y de Z)
  const infoPaginacion = document.getElementById("infoPaginacion");
  if (infoPaginacion) {
    infoPaginacion.textContent = totalRegistros === 0 
      ? "Mostrando 0 de 0" 
      : `Mostrando ${desde}-${hasta} de ${totalRegistros.toLocaleString('es-ES')}`;
  }

  // 2. Input numérico de página y etiqueta de total
  const inputPagina = document.getElementById("input-pagina-db");
  if (inputPagina) {
    inputPagina.value = paginaActual;
    inputPagina.max = totalPaginas;
  }

  const lblTotalPaginas = document.getElementById("lbl-total-paginas-db");
  if (lblTotalPaginas) {
    lblTotalPaginas.textContent = `de ${totalPaginas.toLocaleString('es-ES')}`;
  }

  // 3. Estado Habilitado/Deshabilitado de botones Anterior y Siguiente
  const btnPrev = document.getElementById("btn-prev-db");
  if (btnPrev) {
    btnPrev.disabled = (paginaActual <= 1);
  }

  const btnNext = document.getElementById("btn-next-db");
  if (btnNext) {
    btnNext.disabled = (paginaActual >= totalPaginas);
  }
}

// =========================================================================
// FUNCIONES REQUERIDAS POR EVENTOS HTML (onclick, onchange, onkeydown)
// =========================================================================

// 1. Cambiar la cantidad de registros por página (10, 15, 50, 100)
function cambiarLimiteDB(nuevoLimite) {
  registrosPorPagina = parseInt(nuevoLimite, 10) || 15;
  paginaActual = 1;
  cargarBaseDatosPaginated();
}

// 2. Navegar con los botones Anterior (-1) o Siguiente (+1)
function cambiarPaginaDB(delta) {
  const totalPaginas = Math.ceil(totalRegistros / registrosPorPagina) || 1;
  const nuevaPagina = paginaActual + delta;

  if (nuevaPagina >= 1 && nuevaPagina <= totalPaginas) {
    paginaActual = nuevaPagina;
    cargarBaseDatosPaginated();
  }
}

// 3. Saltar directamente a un número de página específico
function irAPaginaDirecta(numPagina) {
  const totalPaginas = Math.ceil(totalRegistros / registrosPorPagina) || 1;
  let pagina = parseInt(numPagina, 10);

  if (isNaN(pagina) || pagina < 1) {
    pagina = 1;
  } else if (pagina > totalPaginas) {
    pagina = totalPaginas;
  }

  paginaActual = pagina;
  cargarBaseDatosPaginated();
}

function mostrarSpinner(visible) {
  const spinner = document.getElementById("spinnerCarga");
  if (spinner) spinner.style.display = visible ? "block" : "none";
}