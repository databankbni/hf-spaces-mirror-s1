// URL de exportación CSV directa desde Google Sheets
const SHEET_URL = "https://docs.google.com/spreadsheets/d/1UXtiEPUHof4mxBRf4ztuW_o9hzvo4_1mWKZJHyDi8KI/export?format=csv&gid=1422203808";

// Estado global de la aplicación
let datasetGlobal = [];
let datasetFiltrado = [];
let tipoBusqueda = 'index';
let paginaActual = 1;
const REGISTROS_POR_PAGINA = 25;

// Inicialización
document.addEventListener("DOMContentLoaded", () => {
  inicializarEventos();
  cargarDatosGoogleSheet();
});

function inicializarEventos() {
  // Disparar input de archivo al hacer clic en Cargar CSV
  document.getElementById("btnCargarManual").addEventListener("click", () => {
    document.getElementById("fileInput").click();
  });

  // Procesar archivo CSV local seleccionado
  document.getElementById("fileInput").addEventListener("change", cargarArchivoManual);

  // Sync / Recargar datos desde Google Sheets
  document.getElementById("btnSync").addEventListener("click", cargarDatosGoogleSheet);

  // Botón buscar e Input Enter
  document.getElementById("btnBuscar").addEventListener("click", ejecutarBusqueda);
  document.getElementById("searchInput").addEventListener("keyup", (e) => {
    if (e.key === "Enter") ejecutarBusqueda();
  });

  // Eventos para cambiar de pestaña (INDEX, Número, Nombre)
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      e.target.classList.add("active");
      tipoBusqueda = e.target.getAttribute("data-type");
      ejecutarBusqueda();
    });
  });

  // Botones de Paginación
  document.getElementById("btnPrev").addEventListener("click", () => cambiarPagina(-1));
  document.getElementById("btnNext").addEventListener("click", () => cambiarPagina(1));
}

// Carga automática desde Google Sheets
function cargarDatosGoogleSheet() {
  const metricEstado = document.getElementById("metricEstado");
  metricEstado.textContent = "Cargando Sheets...";
  metricEstado.className = "value status-connecting";

  Papa.parse(SHEET_URL, {
    download: true,
    header: true,
    skipEmptyLines: true,
    complete: function(results) {
      procesarDataYRenderizar(results.data, "En línea (Google Sheets)");
    },
    error: function(err) {
      metricEstado.textContent = "Error de Carga";
      metricEstado.className = "value status-error";
      console.error("Error al obtener datos:", err);
    }
  });
}

// Cargue Manual de Archivo CSV Local
function cargarArchivoManual(event) {
  const file = event.target.files[0];
  if (!file) return;

  const metricEstado = document.getElementById("metricEstado");
  metricEstado.textContent = "Procesando...";
  metricEstado.className = "value status-connecting";

  Papa.parse(file, {
    header: true,
    skipEmptyLines: true,
    complete: function(results) {
      procesarDataYRenderizar(results.data, "Archivo Local Cargado");
    },
    error: function(err) {
      metricEstado.textContent = "Error en Archivo";
      metricEstado.className = "value status-error";
      console.error("Error al leer CSV:", err);
    }
  });
}

// Procesa y limpia las filas descargadas o cargadas manualmente
function procesarDataYRenderizar(dataRaw, textoEstado) {
  datasetGlobal = dataRaw.map(row => {
    let cleanRow = {};
    for (let key in row) {
      cleanRow[key.trim().toUpperCase()] = row[key] ? row[key].trim() : "";
    }
    return cleanRow;
  }).filter(r => r["NOMBRE"] && r["NOMBRE"].toUpperCase() !== "NOMBRE");

  datasetFiltrado = [...datasetGlobal];
  
  // Actualización de Métricas de Encabezado
  document.getElementById("metricTotal").textContent = datasetGlobal.length;
  document.getElementById("metricFiltrados").textContent = datasetFiltrado.length;
  
  const metricEstado = document.getElementById("metricEstado");
  metricEstado.textContent = textoEstado;
  metricEstado.className = "value status-online";

  paginaActual = 1;
  renderizarTabla();
}

// Filtrado de búsquedas en memoria
function ejecutarBusqueda() {
  const val = document.getElementById("searchInput").value.trim().toUpperCase();

  if (!val) {
    datasetFiltrado = [...datasetGlobal];
  } else {
    datasetFiltrado = datasetGlobal.filter(row => {
      if (tipoBusqueda === 'index') {
        return (row["INDEX"] || row["INDEX_CODE"] || "").toUpperCase() === val;
      } else if (tipoBusqueda === 'nombre') {
        return (row["NOMBRE"] || "").toUpperCase().includes(val);
      } else if (tipoBusqueda === 'numero') {
        const numClean = val.replace(/\D/g, "");
        const n1 = (row["NUMERO VENTA"] || row["NUMERO_VENTA"] || "").replace(/\D/g, "");
        const n2 = (row["NUMERO 1"] || row["NUMERO_CONFIRMADO_1"] || "").replace(/\D/g, "");
        const n3 = (row["NUMERO 2"] || row["NUMERO_CONFIRMADO_2"] || "").replace(/\D/g, "");
        return n1.includes(numClean) || n2.includes(numClean) || n3.includes(numClean);
      }
      return false;
    });
  }

  document.getElementById("metricFiltrados").textContent = datasetFiltrado.length;
  paginaActual = 1;
  renderizarTabla();
}

// Renderizado de tabla y paginación
function renderizarTabla() {
  const tbody = document.querySelector("#tablaResultados tbody");
  tbody.innerHTML = "";

  const total = datasetFiltrado.length;
  const totalPaginas = Math.ceil(total / REGISTROS_POR_PAGINA) || 1;

  if (paginaActual > totalPaginas) paginaActual = totalPaginas;

  const inicio = (paginaActual - 1) * REGISTROS_POR_PAGINA;
  const fin = inicio + REGISTROS_POR_PAGINA;
  const paginaData = datasetFiltrado.slice(inicio, fin);

  paginaData.forEach(row => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row["INDEX"] || row["INDEX_CODE"] || ""}</td>
      <td>${row["AFILIADOS"] || ""}</td>
      <td>${row["NUMERO VENTA"] || row["NUMERO_VENTA"] || ""}</td>
      <td>${row["AGENTE"] || ""}</td>
      <td>${row["FECHA LLAMADA"] || row["FECHA_LLAMADA"] || ""}</td>
      <td>${row["NOMBRE"] || ""}</td>
      <td>${row["FECHA NACIMIENTO"] || row["DOB"] || ""}</td>
      <td>${row["NUMERO 1"] || row["NUMERO_CONFIRMADO_1"] || ""}</td>
      <td>${row["NUMERO 2"] || row["NUMERO_CONFIRMADO_2"] || ""}</td>
      <td>${row["ESTADO"] || ""}</td>
      <td>${row["STATUS"] || ""}</td>
      <td>${row["CIA"] || ""}</td>
    `;
    tbody.appendChild(tr);
  });

  document.getElementById("labelPaginacion").textContent = `Página ${paginaActual} de ${totalPaginas} (${total} registros)`;
}

// Lógica de cambio de página
function cambiarPagina(delta) {
  const totalPaginas = Math.ceil(datasetFiltrado.length / REGISTROS_POR_PAGINA) || 1;
  if (paginaActual + delta >= 1 && paginaActual + delta <= totalPaginas) {
    paginaActual += delta;
    renderizarTabla();
  }
}