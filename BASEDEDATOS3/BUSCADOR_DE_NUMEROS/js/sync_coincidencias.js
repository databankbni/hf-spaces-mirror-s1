// js/sync_coincidencias.js

function normalizarTexto(str) {
    if (!str) return "";
    return str
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[^a-zA-Z0-9\s]/g, "")
        .trim()
        .toLowerCase()
        .replace(/\s+/g, " ");
}

/// Convierte y valida fechas a formato ISO (YYYY-MM-DD) para PostgreSQL
function formatearFechaISO(fechaStr) {
    if (!fechaStr) return null;
    let str = String(fechaStr).trim();
    if (!str) return null;

    let anio, mes, dia;

    // 1. Si viene en formato DD/MM/YYYY o DD-MM-YYYY
    const dmyMatch = str.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$/);
    if (dmyMatch) {
        dia = parseInt(dmyMatch[1], 10);
        mes = parseInt(dmyMatch[2], 10);
        anio = parseInt(dmyMatch[3], 10);
    } 
    // 2. Si viene en formato YYYY-MM-DD o YYYY/MM/DD
    else {
        const ymdMatch = str.match(/^(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})$/);
        if (ymdMatch) {
            anio = parseInt(ymdMatch[1], 10);
            mes = parseInt(ymdMatch[2], 10);
            dia = parseInt(ymdMatch[3], 10);
        }
    }

    // 3. Validar valores de día (1-31), mes (1-12) y año
    if (anio && mes >= 1 && mes <= 12 && dia >= 1 && dia <= 31) {
        const diaStr = String(dia).padStart(2, '0');
        const mesStr = String(mes).padStart(2, '0');
        return `${anio}-${mesStr}-${diaStr}`;
    }

    // Si el día es 00 (ej. 1900-01-00) u otro valor inválido, retorna null
    return null;
}

// Descarga paginada eficiente por Keyset/Cursor usando .gt() para evitar timeouts en tablas masivas
async function descargarTablaCompleta(clienteSupabase, nombreTabla, columnas, campoClave = 'id') {
    let acumulado = [];
    let ultimoValorClave = null;
    const tamanoPagina = 1000; // ⚠️ Límite máximo estándar permitido por el API de Supabase
    let continuar = true;

    while (continuar) {
        let query = clienteSupabase
            .from(nombreTabla)
            .select(columnas)
            .order(campoClave, { ascending: true })
            .limit(tamanoPagina);

        if (ultimoValorClave !== null) {
            query = query.gt(campoClave, ultimoValorClave);
        }

        const { data, error } = await query;

        if (error) {
            throw new Error(`Error descargando ${nombreTabla}: ${error.message}`);
        }

        if (data && data.length > 0) {
            acumulado = acumulado.concat(data);
            ultimoValorClave = data[data.length - 1][campoClave];

            // Feedback en consola cada 25.000 registros
            if (acumulado.length % 25000 === 0) {
                console.log(`⏳ Avance [${nombreTabla}]: ${acumulado.length.toLocaleString()} registros descargados...`);
            }

            // Si devuelve menos que el límite (1000), significa que alcanzamos la última página
            if (data.length < tamanoPagina) {
                continuar = false;
            }
        } else {
            // Si regresa array vacío, terminamos el bucle
            continuar = false;
        }
    }
    return acumulado;
}

async function ejecutarSincronizacionCruzada() {
    const btnSync = document.getElementById('btn-sync-coincidencias');
    const statusMsg = document.getElementById('msg-sync-status');
    
    if (btnSync) btnSync.disabled = true;
    if (statusMsg) statusMsg.innerHTML = '<span class="text-info"><div class="spinner-border spinner-border-sm me-1"></div> Descargando registros de ambas bases de datos...</span>';

    try {
        console.log("--> Iniciando descarga masiva de Ventas y Miembros...");

        // 1. Descarga masiva por cursor usando la clave primaria/index
        const [dataVentas, dataMiembros] = await Promise.all([
            descargarTablaCompleta(
                supabaseVentas, 
                'registros_ventas', 
                'index_code, nombre, estado, cia, status, numero_venta, confirmado_1, afiliados, dob, ultimo_hs',
                'index_code'
            ),
            descargarTablaCompleta(
                supabaseMiembros, 
                'miembros', 
                'id_member, nombre, estado, compania, status, tipo_plan, agente',
                'id_member'
            )
        ]);

        console.log(`✅ TOTAL Ventas descargadas: ${dataVentas.length.toLocaleString()}`);
        console.log(`✅ TOTAL Miembros descargados: ${dataMiembros.length.toLocaleString()}`);

        if (statusMsg) statusMsg.innerHTML = `<span class="text-info">Indexando y cruzando ${dataVentas.length.toLocaleString()} ventas vs ${dataMiembros.length.toLocaleString()} miembros...</span>`;

        // 2. Mapear Miembros en Memoria usando Nombre Normalizado como Clave
        const mapaMiembros = new Map();

        dataMiembros.forEach(m => {
            const nomNormalizado = normalizarTexto(m.nombre);
            if (!nomNormalizado) return;

            if (!mapaMiembros.has(nomNormalizado)) {
                mapaMiembros.set(nomNormalizado, []);
            }
            mapaMiembros.get(nomNormalizado).push(m);
        });

        // 3. Realizar el Cruce
        const mapaCoincidenciasUnicas = new Map();

        dataVentas.forEach(v => {
            const nomV = normalizarTexto(v.nombre);
            if (!nomV) return;

            const matches = mapaMiembros.get(nomV);

            if (matches && matches.length > 0) {
                matches.forEach(m => {
                    const idx = String(v.index_code || '-');
                    const idM = String(m.id_member || '-');
                    const uniqueKey = `${idx}_${idM}`;

                    if (!mapaCoincidenciasUnicas.has(uniqueKey)) {
                        mapaCoincidenciasUnicas.set(uniqueKey, {
                            index_code: idx,
                            id_member: idM,
                            nombres: (m.nombre || v.nombre || '-').trim(),
                            estado: (m.estado || v.estado || '-').trim(),
                            compania: (m.compania || v.cia || '-').trim(),
                            status_venta: (v.status || '-').trim(),
                            status_miembro: (m.status || '-').trim(),

                            // Columnas de ventas
                            numero_venta: v.numero_venta || null,
                            numero_confirmado_1: v.confirmado_1 || null,
                            afiliados: v.afiliados || null,
                            dob: formatearFechaISO(v.dob), // 🔹 Sanitizado a YYYY-MM-DD
                            ultimo_hs: v.ultimo_hs || null,

                            // Columnas de miembros
                            plan: m.tipo_plan || null,
                            agente: m.agente || null
                        });
                    }
                });
            }
        });

        const coincidenciasFinales = Array.from(mapaCoincidenciasUnicas.values());
        console.log(`🎯 Coincidencias Totales Encontradas: ${coincidenciasFinales.length.toLocaleString()}`);

        if (coincidenciasFinales.length === 0) {
            if (statusMsg) statusMsg.innerHTML = '<span class="text-warning">No se encontraron coincidencias.</span>';
            if (btnSync) btnSync.disabled = false;
            return;
        }

        if (statusMsg) statusMsg.innerHTML = `<span class="text-primary">Guardando ${coincidenciasFinales.length.toLocaleString()} coincidencias en Supabase...</span>`;

        // 4. Guardar por lotes de 1000 en la tabla de coincidencias
        const tamanoLote = 1000;
        for (let i = 0; i < coincidenciasFinales.length; i += tamanoLote) {
            const lote = coincidenciasFinales.slice(i, i + tamanoLote);
            const { error: upsertErr } = await supabaseVentas
                .from('coincidencias_ventas_miembros')
                .upsert(lote, { onConflict: 'index_code, id_member' });

            if (upsertErr) throw upsertErr;

            if (statusMsg) {
                const avance = Math.min(i + tamanoLote, coincidenciasFinales.length);
                statusMsg.innerHTML = `<span class="text-primary">Guardando en Supabase: ${avance.toLocaleString()} / ${coincidenciasFinales.length.toLocaleString()}...</span>`;
            }
        }

        if (statusMsg) statusMsg.innerHTML = `<span class="text-success fw-bold"><i class="bi bi-check-circle me-1"></i> ¡Éxito! Se sincronizaron ${coincidenciasFinales.length.toLocaleString()} coincidencias con todas las columnas completas.</span>`;

    } catch (err) {
        console.error("❌ Error en la Sincronización:", err);
        if (statusMsg) statusMsg.innerHTML = `<span class="text-danger fw-bold">Error: ${err.message}</span>`;
    } finally {
        if (btnSync) btnSync.disabled = false;
    }
}