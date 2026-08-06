// js/upload_tab.js

let datosProcesados = [];
let nombreArchivoGlobal = "";

// Convierte un número de serie de Excel (ej: 44517) a formato DD/MM/YYYY
function convertirFechaExcel(valor) {
  if (!valor) return "";

  if (typeof valor === 'string' && (valor.includes('/') || valor.includes('-'))) {
    return valor.trim();
  }

  const num = Number(valor);
  if (isNaN(num) || num <= 0) return String(valor).trim();

  const fecha = new Date(Math.round((num - 25569) * 86400 * 1000));
  
  const dia = String(fecha.getUTCDate()).padStart(2, '0');
  const mes = String(fecha.getUTCMonth() + 1).padStart(2, '0');
  const anio = fecha.getUTCFullYear();

  return `${dia}/${mes}/${anio}`;
}

document.addEventListener("DOMContentLoaded", () => {
  const inputFileInput = document.getElementById("excelFile");
  const btnProcesar = document.getElementById("btnProcesar");
  const estadoLectura = document.getElementById("estadoLectura");

  inputFileInput.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;

    nombreArchivoGlobal = file.name;
    btnProcesar.disabled = true;
    if (estadoLectura) estadoLectura.style.display = "block";
    ocultarAlerta();

    setTimeout(() => {
      const reader = new FileReader();

      reader.onload = (evt) => {
        try {
          const data = new Uint8Array(evt.target.result);
          const workbook = XLSX.read(data, { type: 'array' });
          const sheetName = workbook.SheetNames[0];
          const sheet = workbook.Sheets[sheetName];

          const jsonRaw = XLSX.utils.sheet_to_json(sheet, { defval: "" });

          datosProcesados = jsonRaw.map(row => {
            let cleanRow = {};
            for (let key in row) {
              cleanRow[key.trim().toUpperCase()] = String(row[key]).trim();
            }
          
            return {
              index_code: cleanRow["INDEX"] || cleanRow["INDEX_CODE"] || "",
              afiliados: cleanRow["AFILIADOS"] || "",
              numero_venta: cleanRow["NUMERO DE VENTA"] || cleanRow["N° VENTA"] || cleanRow["NUMERO VENTA"] || "",
              agente: cleanRow["AGENTE"] || "",
              
              fecha_llamada: convertirFechaExcel(cleanRow["FECHA LLAMADA"] || cleanRow["FECHA_LLAMADA"]),
              nombre: cleanRow["NOMBRE"] || "",
              dob: convertirFechaExcel(cleanRow["DOB"] || cleanRow["FECHA NACIMIENTO"]),
              
              confirmado_1: cleanRow["NUMERO CONFIRMADO 1"] || cleanRow["CONFIRMADO 1"] || cleanRow["NUMERO 1"] || "",
              confirmado_2: cleanRow["NUMERO CONFIRMADO 2"] || cleanRow["CONFIRMADO 2"] || cleanRow["NUMERO 2"] || "",
              estado: cleanRow["ESTADO"] || "",
              
              // 📌 CAMBIADO: Ahora se mapea a 'index_member' y busca variaciones de "INDEX MEMBER" o "PARENTESCO"
              index_member: cleanRow["INDEX MEMBER"] || cleanRow["INDEX_MEMBER"] || cleanRow["INDEX-MEMBER"] || cleanRow["AF."] || cleanRow["AF"] || cleanRow["PARENTESCO"] || "",
              
              status: cleanRow["STATUS"] || "",
              cia: cleanRow["CIA"] || "",
              ultimo_hs: cleanRow["ULTIMO HS"] || cleanRow["ULTIMO_HS"] || "",

              // 📌 Mapeo exacto respetando la columna del Excel:
              archivo_origen: nombreArchivoGlobal || "CARGA MANUAL",
              archivo_id: cleanRow["ARCHIVO"] || cleanRow["LIBRO"] || cleanRow["ARCHIVO ORIGEN"] || ""
            };
          }).filter(item => item.nombre !== "" || item.index_code !== "");

          if (estadoLectura) estadoLectura.style.display = "none";

          if (datosProcesados.length > 0) {
            btnProcesar.disabled = false;
            mostrarAlerta(`✅ Archivo preparado con éxito: <strong>${datosProcesados.length}</strong> registros listos para subir.`, 'info');
          } else {
            btnProcesar.disabled = true;
            mostrarAlerta('⚠️ El archivo no contiene registros válidos.', 'warning');
          }

        } catch (err) {
          console.error("Error al analizar Excel:", err);
          if (estadoLectura) estadoLectura.style.display = "none";
          mostrarAlerta(`❌ Error al leer el archivo: ${err.message}`, 'danger');
        }
      };

      reader.readAsArrayBuffer(file);
    }, 100);
  });

  btnProcesar.addEventListener("click", subirDatosASupabase);
});

async function subirDatosASupabase() {
  const btnProcesar = document.getElementById("btnProcesar");
  const estadoCarga = document.getElementById("estadoCarga");
  const estadoLectura = document.getElementById("estadoLectura");
  const barraProgreso = document.getElementById("barraProgreso");
  const lblProgreso = document.getElementById("lblProgreso");

  if (estadoLectura) estadoLectura.style.display = "none";

  btnProcesar.disabled = true;
  if (estadoCarga) estadoCarga.style.display = "block";

  try {
    // Registrar el archivo subido en el historial (opcional)
    try {
      await supabaseClient
        .from('archivos')
        .insert([{ nombre_archivo: nombreArchivoGlobal, total_registros: datosProcesados.length }]);
    } catch (errHist) {
      console.warn("Aviso al guardar en la tabla 'archivos':", errHist);
    }

    const BATCH_SIZE = 500;
    const totalRegistros = datosProcesados.length;
    let procesados = 0;

    for (let i = 0; i < totalRegistros; i += BATCH_SIZE) {
      const batch = datosProcesados.slice(i, i + BATCH_SIZE);
      
      const { error: errBatch } = await supabaseClient
        .from('registros_ventas')
        .insert(batch);

      if (errBatch) throw errBatch;

      procesados += batch.length;
      const porcentaje = Math.round((procesados / totalRegistros) * 100);
      
      if (barraProgreso) {
        barraProgreso.style.width = `${porcentaje}%`;
        barraProgreso.textContent = `${porcentaje}%`;
      }
      if (lblProgreso) {
        lblProgreso.textContent = `Subiendo ${procesados} de ${totalRegistros} registros a Supabase...`;
      }
    }

    mostrarAlerta(`🎉 ¡DATA MASTER guardada exitosamente! Se subieron ${totalRegistros} registros.`, 'success');
    document.getElementById("excelFile").value = "";

  } catch (err) {
    console.error("Error al subir archivo:", err);
    mostrarAlerta(`❌ Error al guardar datos: ${err.message}`, 'danger');
  } finally {
    btnProcesar.disabled = false;
    if (estadoCarga) estadoCarga.style.display = "none";
  }
}

function mostrarAlerta(mensaje, tipo) {
  const alert = document.getElementById("alertResultado");
  if (alert) {
    alert.className = `alert alert-${tipo} mt-3`;
    alert.innerHTML = mensaje;
    alert.style.display = "block";
  }
}

function ocultarAlerta() {
  const alert = document.getElementById("alertResultado");
  if (alert) alert.style.display = "none";
}