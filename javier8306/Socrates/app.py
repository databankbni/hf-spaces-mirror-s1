import os
import re
import json
import gradio as gr
from supabase import create_client, Client
from sentence_transformers import SentenceTransformer
from openai import OpenAI

# ==========================================
# 1. CREDENTIALS AND CONNECTIONS (CLOUD)
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

if not SUPABASE_URL or not SUPABASE_KEY or not OPENROUTER_API_KEY:
    raise ValueError("❌ Missing credentials. Check Hugging Face Secrets.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
modelo_vectorial = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', device='cpu')

cliente_ia = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

ENRUTADOR_MODELOS = {
    "textos_clasicos_latin_v3": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "textos_clasicos_griego_v3": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "textos_clasicos_chino_v3": "google/gemma-4-26b-a4b-it:free"
}

# ==========================================
# 2. ORACLE LOGIC (GLASS-BOX SWARM)
# ==========================================
def realizar_exegesis_web(consulta, canones_seleccionados, progress=gr.Progress()):
    if not canones_seleccionados:
        return "⚠️ Please select at least one database.", "No databases selected."

    # Pop-up notification for the user
    gr.Info("The swarm is processing your request. This may take a few minutes. Please wait...")
    
    # We use the model assigned to the first selected database for the final output
    modelo_asignado = ENRUTADOR_MODELOS[canones_seleccionados[0]]
    bitacora_agentes = [] 
    
    # ---------------------------------------------------------
    # AGENT 1: ANALYST (Alias Expansion)
    # ---------------------------------------------------------
    progress(0.1, desc="Agent 1: Analyzing and expanding aliases...")
    bitacora_agentes.append("🕵️ **Agent 1 (Analyst):** Initiating dissection and alias expansion...")
    prompt_extraccion = f"""
    Analyze the query. Extract the author or the work and generate a list with ALL possible spelling variants (English, Latin/Greek, full name, surnames).
    If there is no author, return an empty list [].
    Respond ONLY with a valid JSON object.
    Query: "{consulta}"
    Expected format: {{"author_variants": ["Sallust", "Sallustius", "Gaius Sallustius Crispus"], "keywords": "concept 1, concept 2"}}
    """
    
    try:
        respuesta_analista = cliente_ia.chat.completions.create(
            model=modelo_asignado,
            messages=[
                {"role": "system", "content": "You are a JSON structured data analyzer."},
                {"role": "user", "content": prompt_extraccion}
            ],
            temperature=0.1
        )
        texto_json = respuesta_analista.choices[0].message.content
        match_json = re.search(r'\{.*\}', texto_json, re.DOTALL)
        
        if match_json:
            datos = json.loads(match_json.group(0))
            variantes_autor = datos.get("author_variants", [])
            claves_busqueda = datos.get("keywords", consulta).strip()
        else:
            variantes_autor, claves_busqueda = [], consulta
            
        bitacora_agentes.append(f"   ↳ *Aliases detected:* `{variantes_autor if variantes_autor else 'None'}`")
        bitacora_agentes.append(f"   ↳ *Vector keywords:* `{claves_busqueda}`")
            
    except Exception as e:
        variantes_autor, claves_busqueda = [], consulta
        bitacora_agentes.append(f"   ⚠️ *Agent 1 Error:* {e}. Using full text.")

    # ---------------------------------------------------------
    # AGENT 2: ARCHIVIST (Multi-Alias & Multi-DB Python Search)
    # ---------------------------------------------------------
    progress(0.3, desc="Agent 2: Searching databases...")
    bitacora_agentes.append("\n🗄️ **Agent 2 (Archivist):** Searching for alias matches in selected databases...")
    conteo_autor_total = 0
    
    if variantes_autor:
        for canon in canones_seleccionados:
            try:
                filtros_or = ",".join([f"obra.ilike.%{alias}%" for alias in variantes_autor])
                
                res_count = supabase.table(canon)\
                    .select("id", count="exact")\
                    .or_(filtros_or)\
                    .execute()
                
                conteo_actual = res_count.count if res_count.count else 0
                conteo_autor_total += conteo_actual
                
                if conteo_actual > 0:
                    bitacora_agentes.append(f"   ↳ ✅ **Success in [{canon}]:** Located **{conteo_actual}** passages using the alias network.")
            except Exception as e:
                bitacora_agentes.append(f"   ↳ ⚠️ Error counting passages in [{canon}]: {e}")
                
        if conteo_autor_total == 0:
            bitacora_agentes.append(f"   ↳ ⚠️ **Warning:** None of the aliases {variantes_autor} yielded results. The author is not in the selected corpus.")
    else:
        bitacora_agentes.append("   ↳ Global search authorized (no specific author restricted).")

    # ---------------------------------------------------------
    # AGENT 3: MATHEMATICIAN (Vectorization & Similarity)
    # ---------------------------------------------------------
    progress(0.6, desc="Agent 3: Mapping semantic coordinates...")
    bitacora_agentes.append("\n📐 **Agent 3 (Mathematician):** Mapping semantic coordinates...")
    texto_a_vectorizar = f"{claves_busqueda}. {consulta}"
    vector_query = modelo_vectorial.encode(texto_a_vectorizar, convert_to_tensor=False).tolist()
    
    filtro_db = None 
    pasajes_totales = []

    for canon in canones_seleccionados:
        try:
            respuesta_db = supabase.rpc(
                "buscar_pasajes_clasicos",
                {
                    "query_embedding": vector_query,
                    "match_threshold": 0.15, 
                    "match_count": 5,
                    "tabla_destino": canon,
                    "filtro_autor_obra": filtro_db
                }
            ).execute()

            if respuesta_db.data:
                # Add canon identifier to each passage for context
                for passage in respuesta_db.data:
                    passage["canon_origen"] = canon
                pasajes_totales.extend(respuesta_db.data)
                
        except Exception as e:
            bitacora_agentes.append(f"   ↳ ⚠️ Error in vector search for [{canon}]: {e}")

    if pasajes_totales:
        bitacora_agentes.append(f"   ↳ ✅ **Success:** Retrieved a total of **{len(pasajes_totales)}** passages surpassing the semantic similarity threshold (0.15) across selected databases.")
    else:
        bitacora_agentes.append(f"   ↳ ❌ **Semantic failure:** Although there might be passages of the author, none conceptually matched your keyword coordinates.")

    # ---------------------------------------------------------
    # AGENT 4: PHILOLOGIST (Transparent Explainer & Exegete)
    # ---------------------------------------------------------
    progress(0.8, desc="Agent 4: Drafting final exegesis...")
    bitacora_agentes.append("\n✍️ **Agent 4 (Philologist):** Drafting final response based on evidence...")
    
    contexto_documentos = ""
    for i, frag in enumerate(pasajes_totales):
        obra = frag.get("obra", "Unknown")
        texto = frag.get("texto_original", "")
        canon_origen = frag.get("canon_origen", "Unknown Database")
        contexto_documentos += f"\n[Document {i+1} - Work: {obra} | Source: {canon_origen}]\n{texto}\n"

    historial_transparente = "\n".join(bitacora_agentes)

    prompt_sistema = """
    You are the Philological Oracle, the final agent of an AI swarm.
    
    VITAL INSTRUCTIONS:
    1. LANGUAGE: Respond EXCLUSIVELY in the language of the "User Query" (e.g., if the user asks in English, reply in English; if in Spanish, reply in Spanish).
    2. TRANSPARENCY: Read the "Agent History". If no documents were found for the requested author, politely explain the limitation and rely on your general philological knowledge, clearly distinguishing it from retrieved data.
    3. EXEGESIS: If documents were retrieved, analyze them rigorously in relation to the query.
    4. REASONING: Write your final logical process inside <reasoning> and </reasoning> tags.
    """

    prompt_usuario = f"User Query: {consulta}\n\n=== Agent History (For your knowledge) ===\n{historial_transparente}\n\n=== Retrieved Documents ===\n{contexto_documentos if pasajes_totales else 'NONE'}"

    try:
        response = cliente_ia.chat.completions.create(
            model=modelo_asignado,
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario}
            ],
            temperature=0.3
        )

        respuesta_completa = response.choices[0].message.content
        
        match = re.search(r'<reasoning>(.*?)</reasoning>', respuesta_completa, re.DOTALL | re.IGNORECASE)
        if match:
            texto_razonamiento = historial_transparente + "\n\n**💭 Philologist's Final Reflection:**\n" + match.group(1).strip()
            texto_exegesis = respuesta_completa.replace(match.group(0), '').strip()
        else:
            texto_razonamiento = historial_transparente + "\n\n**💭 Philologist's Final Reflection:**\nNo reasoning tags were generated."
            texto_exegesis = respuesta_completa

        progress(1.0, desc="Done!")
        return texto_exegesis, texto_razonamiento

    except Exception as e:
        return f"⚠️ Error in the exegesis phase: {str(e)}", historial_transparente

# ==========================================
# 3. GRAPHICAL INTERFACE
# ==========================================
with gr.Blocks() as demo:
    gr.Markdown("# 🏛️ Socrates - Philological Oracle")
    gr.Markdown("### Agentic RAG System: *Glass-Box Swarm Architecture*")
    gr.Markdown(
        "**About this system:** This is a Retrieval-Augmented Generation (RAG) tool designed to retrieve, "
        "cross-reference, and deeply analyze information exclusively from classical texts in **Latin**, **Ancient Greek**, "
        "and **Classical Chinese**. The swarm utilizes multiple AI agents to ensure rigorous historical and philological accuracy."
    )
    
    with gr.Row():
        with gr.Column(scale=1):
            canon_dropdown = gr.Dropdown(
                choices=["textos_clasicos_latin_v3", "textos_clasicos_griego_v3", "textos_clasicos_chino_v3"],
                value=["textos_clasicos_latin_v3"], # Selects Latin by default
                multiselect=True,
                label="📚 Select Database(s) / Canon"
            )
            consulta_input = gr.Textbox(
                label="✍️ Query",
                placeholder="e.g. The moral decadence in Sallust...",
                lines=4
            )
            boton_consultar = gr.Button("Invoke Oracle", variant="primary")
            gr.Markdown("*Note: The system performs deep architectural searches. Processing may take a few minutes.*")
            
        with gr.Column(scale=2):
            with gr.Accordion("🧠 Reasoning Trace (Swarm Log)", open=True):
                salida_razonamiento = gr.Markdown(label="")
                
            salida_markdown = gr.Markdown(label="Exegesis")

    boton_consultar.click(
        fn=realizar_exegesis_web,
        inputs=[consulta_input, canon_dropdown],
        outputs=[salida_markdown, salida_razonamiento]
    )

if __name__ == "__main__":
    demo.launch(theme=gr.themes.Soft())