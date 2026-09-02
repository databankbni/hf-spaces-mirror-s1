import { NextResponse } from "next/server";

const defaultModels = [
  "openai/gpt-oss-20b:fastest",
  "Qwen/Qwen3-32B:fastest",
  "deepseek-ai/DeepSeek-V3-0324:fastest",
  "meta-llama/Llama-3.3-70B-Instruct:fastest"
];

// Dos consumidores muy distintos comparten este endpoint:
//   "plan" -> la revision adversarial del plan; el cliente PARSEA la respuesta
//             linea por linea (parseAiCards) y necesita el formato literal.
//   "chat" -> el panel flotante; responde en prosa la pregunta que se hizo.
// Sin esta separacion el prompt de formato se aplicaba tambien al chat y el
// modelo devolvia la lista de despachos preguntaras lo que preguntaras.
type AiMode = "plan" | "chat";

export async function POST(request: Request) {
  const body = await request.json();
  const question = String(body.question ?? "");
  const context = String(body.context ?? "");
  const mode: AiMode = body.mode === "chat" ? "chat" : "plan";

  if (!process.env.HF_TOKEN) {
    return NextResponse.json({
      answer:
        "HF_TOKEN no esta configurado. Agrega un token de Hugging Face con permiso para Inference Providers."
    });
  }

  const models = getModelChain();
  const errors: string[] = [];

  for (const model of models) {
    try {
      const response = await fetch("https://router.huggingface.co/v1/chat/completions", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${process.env.HF_TOKEN}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          model,
          stream: false,
          temperature: 0.2,
          // Holgado: los modelos de razonamiento gastan tokens en <think> antes de
          // la respuesta; con poco presupuesto se truncaban a mitad del razonamiento.
          max_tokens: 1600,
          messages: [
            {
              role: "system",
              content: buildSystemPrompt(mode)
            },
            {
              role: "user",
              content: `Contexto operativo:\n${context}\n\nPregunta:\n${question}`
            }
          ]
        })
      });

      const data = await response.json().catch(() => null);
      const answer = cleanAnswer(data?.choices?.[0]?.message?.content);

      if (response.ok && answer) {
        return NextResponse.json({ answer });
      }

      errors.push(`${model}: ${readError(data, response.status)}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Error desconocido";
      errors.push(`${model}: ${message}`);
    }
  }

  return NextResponse.json(
    {
      answer: `No se pudo completar la inferencia con los modelos configurados.\n\nIntentos:\n${errors.join("\n")}`
    },
    { status: 502 }
  );
}

// Reglas de negocio: valen para los dos modos. Lo que cambia entre ellos es
// solo la FORMA de la respuesta, nunca el dominio.
const REGLAS_OPERATIVAS = [
  "Eres un planificador logistico de materia prima para la refineria DANEC SANGOLQUI.",
  "Responde siempre en espanol.",
  "Reglas de priorizacion del plan diario:",
  "1) El cuello de botella es la CAPACIDAD DE RECEPCION de la refineria: estaciones CONFIGURABLES (lista 'stations'); cada estacion tiene un nombre, un cupo de tanqueros/dia (tankers) y los productos que puede recibir (productos). Un producto solo se recibe en la estacion a la que esta asignado. El plan debe LLENAR esos cupos entre semana para evitar horas extra el fin de semana.",
  "2) Prioriza la materia prima de mayor acidez (top 25%) desde EXTRACTORAS y PUERTO: esos entran primero. Los cupos restantes de cada estacion se llenan por la ruta mas barata (minimo costo).",
  "3) No exceder el almacenamiento libre de la refineria por producto (refineryFreeCapacity). Los productos que no esten asignados a ninguna estacion no pueden recibirse y quedan fuera del plan.",
  "4) Usa SOLO las rutas habilitadas que vienen en routes (cada ruta es un par origen->destino activo); no sugieras movimientos por rutas que no esten en esa lista.",
  "Equilibra llenar la recepcion (productividad semanal), acidez (calidad) y costo, sin exceder el almacenamiento de la refineria.",
  "No muestres razonamiento interno, borradores, etiquetas <think> ni cadenas de pensamiento.",
  "No uses Markdown, asteriscos, negritas, tablas ni encabezados decorativos."
];

function buildSystemPrompt(mode: AiMode) {
  if (mode === "chat") {
    return [
      ...REGLAS_OPERATIVAS,
      // Lo critico de este modo: el contexto trae distributionPlan y el modelo
      // tiende a recitarlo. Aqui es material de consulta, no la respuesta.
      "Estas conversando con el jefe de operaciones sobre la jornada de hoy.",
      "RESPONDE EXACTAMENTE LA PREGUNTA QUE TE HACEN, nada mas. No hay un formato fijo de salida.",
      "El contexto incluye 'distributionPlan', el plan que ya calculo el optimizador. Es informacion de apoyo: usalo solo si la pregunta lo requiere.",
      "PROHIBIDO listar el plan de distribucion, enumerar despachos o escribir lineas que empiecen con 'Prioridad' salvo que te lo pidan explicitamente. Ese listado ya se muestra en otra pantalla y repetirlo aqui no aporta nada.",
      "Escribe en prosa breve: de 2 a 6 frases, o hasta 4 vinetas cortas con guion si la pregunta pide una enumeracion.",
      "Cita numeros concretos del contexto (toneladas, acidez, cupos, costos, porcentajes de ocupacion) en vez de generalidades.",
      "Si el contexto no alcanza para responder, dilo en una frase y señala que dato falta. No inventes cifras."
    ].join(" ");
  }

  return [
    ...REGLAS_OPERATIVAS,
    // El cliente contrasta la respuesta contra distributionPlan fila por fila
    // (coincide / difiere / omite / añade), asi que el modelo tiene que
    // posicionarse frente a ese plan, no ignorarlo.
    "El contexto incluye 'distributionPlan': el plan que ya calculo un optimizador determinista. NO lo copies ni lo des por bueno: revisalo con criterio propio.",
    "Coincide con el en los despachos que consideres correctos (mismo origen, producto y toneladas), apartate donde creas que se equivoca, omite los que no incluirias y agrega los que falten.",
    "El optimizador ya respeta todas las restricciones duras, asi que si te apartas de el explica en el Motivo que ganas a cambio.",
    "Entrega solo conclusiones accionables para operacion.",
    // El cliente parsea estas lineas para armar tarjetas (parseAiCards en
    // src/app/page.tsx). El formato tiene que ser literal: cada bullet en UNA
    // sola linea y empezando por "Prioridad <nivel>:".
    "FORMATO OBLIGATORIO. Cada sugerencia va en UNA sola linea, sin saltos internos, con esta forma exacta:",
    "Prioridad <critica|alta|media|baja>: ORIGEN -> DESTINO, PRODUCTO, N t, Motivo: <razon>, Riesgo: <riesgo>",
    "Ejemplo: Prioridad alta: QUEVEDO -> DANEC SANGOLQUI, ACEITE ROJO DE PALMA HIBRIDA, 480 t, Motivo: acidez 4.9 en el top 25%, Riesgo: tanque al 92% de ocupacion",
    "Empieza SIEMPRE con la palabra 'Prioridad'; no uses otra puntuacion ni antepongas numeros o guiones.",
    "Usa maximo 6 lineas de ese tipo.",
    "Cierra con una unica linea que empiece exactamente con 'Accion inmediata:' seguida de la accion.",
    "No agregues introduccion, resumen ni texto fuera de esas lineas."
  ].join(" ");
}

function getModelChain() {
  const configured = [process.env.HF_MODEL, ...(process.env.HF_FALLBACK_MODELS ?? "").split(",")]
    .map((model) => model?.trim())
    .filter((model): model is string => Boolean(model));

  return Array.from(new Set([...configured, ...defaultModels]));
}

function cleanAnswer(value: unknown) {
  if (typeof value !== "string") return "";

  let text = value;

  // Modelos de razonamiento: la respuesta va DESPUES del ultimo cierre de
  // <think>/<thinking>. Si existe, quedarse solo con lo posterior.
  const closeMatch = text.match(/<\/think>|<\/thinking>/gi);
  if (closeMatch) {
    const lastClose = Math.max(text.lastIndexOf("</think>"), text.lastIndexOf("</thinking>"));
    const tag = text.lastIndexOf("</thinking>") === lastClose ? "</thinking>" : "</think>";
    text = text.slice(lastClose + tag.length);
  }

  return text
    .replace(/<think>[\s\S]*?<\/think>/gi, "")
    .replace(/<thinking>[\s\S]*?<\/thinking>/gi, "")
    // <think> sin cierre = respuesta truncada a mitad del razonamiento: descartar.
    .replace(/<think(?:ing)?>[\s\S]*$/i, "")
    .replace(/<\/?think(?:ing)?>/gi, "")
    .replace(/^\s*(analysis|reasoning|thought)\s*:\s*/gim, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/__(.*?)__/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/[ \t]+$/gm, "")
    .trim();
}

function readError(data: unknown, status: number) {
  if (isRecord(data)) {
    const error = data.error;
    if (isRecord(error) && typeof error.message === "string") return error.message;
    if (typeof error === "string") return error;
    if (typeof data.message === "string") return data.message;
  }
  return `HTTP ${status}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
