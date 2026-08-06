// js/files_tab.js

document.addEventListener("DOMContentLoaded", () => {
  cargarListaArchivos();

  document.getElementById("checkSelectAll").addEventListener("change", (e) => {
    const checkboxes = document.querySelectorAll(".check-archivo");
    checkboxes.forEach(cb => cb.checked = e.target.checked);
    actualizarBotonEliminar();
  });

  document.getElementById("btnEliminarSeleccionados").addEventListener("click", eliminarArchivosSeleccionados);
});

async function cargarListaArchivos() {
  const tbody = document.querySelector("#tablaArchivos tbody");
  tbody.innerHTML = `<tr><td colspan="5" class="text-center py-4">Cargando archivos...</td></tr>`;

  try {
    const { data, error } = await supabaseClient
      .from('archivos')
      .select('*')
      .order('fecha_carga', { ascending: false });

    if (error) throw error;

    tbody.innerHTML = "";
    if (!data || data.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="text-center py-4 text-muted">No se han subido archivos aún.</td></tr>`;
      return;
    }

    data.forEach(arc => {
      const fecha = new Date(arc.fecha_carga).toLocaleString();
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><input type="checkbox" class="check-archivo" value="${arc.id}"></td>
        <td class="fw-bold">${arc.nombre_archivo}</td>
        <td><span class="badge bg-primary">${arc.total_registros} registros</span></td>
        <td>${fecha}</td>
        <td>
          <button class="btn btn-outline-danger btn-sm" onclick="eliminarArchivoUnico(${arc.id})">
            <i class="bi bi-trash"></i> Borrar
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });

    document.querySelectorAll(".check-archivo").forEach(cb => {
      cb.addEventListener("change", actualizarBotonEliminar);
    });

  } catch (err) {
    console.error("Error al cargar archivos:", err);
    tbody.innerHTML = `<tr><td colspan="5" class="text-center py-4 text-danger">Error: ${err.message}</td></tr>`;
  }
}

function actualizarBotonEliminar() {
  const seleccionados = document.querySelectorAll(".check-archivo:checked").length;
  const btn = document.getElementById("btnEliminarSeleccionados");
  btn.disabled = seleccionados === 0;
}

async function eliminarArchivoUnico(id) {
  if (!confirm("¿Estás seguro de eliminar este archivo y todos sus registros asociados?")) return;
  await borrarArchivosBaseDatos([id]);
}

async function eliminarArchivosSeleccionados() {
  const checkboxes = document.querySelectorAll(".check-archivo:checked");
  const ids = Array.from(checkboxes).map(cb => cb.value);
  
  if (!confirm(`¿Estás seguro de eliminar los ${ids.length} archivos seleccionados?`)) return;
  await borrarArchivosBaseDatos(ids);
}

async function borrarArchivosBaseDatos(idsArray) {
  try {
    const { error } = await supabaseClient
      .from('archivos')
      .delete()
      .in('id', idsArray);

    if (error) throw error;

    alert("Archivos y registros eliminados con éxito.");
    cargarListaArchivos();
  } catch (err) {
    console.error("Error al eliminar:", err);
    alert("Error al eliminar archivos: " + err.message);
  }
}