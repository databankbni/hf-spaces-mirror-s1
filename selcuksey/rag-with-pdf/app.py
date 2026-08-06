import os
import time
import gradio as gr
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from huggingface_hub import HfApi, hf_hub_download
from groq import Groq

# ── Ayarlar ──────────────────────────────────────────────────────────────
HF_TOKEN   = os.getenv("HF_TOKEN")
HF_DATASET = "selcuksey/my-rag-pdfs"

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

# ── Promptlar ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Sen Alzheimer hastalığı konusunda yardımcı olan, sıcak ve anlayışlı bir asistansın. Sana verilen belge içeriğine dayanarak soruları yanıtlıyorsun.
KURALLAR:
- Sadece Türkçe alfabe ve Türkçe kelimeler kullan, "regular", "konvansiyonel", "semptomatik" gibi yabancı kelimeler kesinlikle kullanma
- Kesinlikle Türkçe dışında hiçbir alfabe veya karakter kullanma
- "nörodejeneratif" kelimesini kullanma, yerine "beyin hücrelerinin yavaş yavaş hasar gördüğü" de
- "lisan" yerine "konuşma", "varsanı" yerine "olmayan şeyleri görmek veya duymak", "agresyon" yerine "saldırganlık", "entferlemek" yerine "kaldırmak" de
- "delüzyon" kelimesini kullanma, yerine "gerçek olmayan inançlar" veya "olmayan şeyleri gerçekmiş gibi görmek" de
- "semptomatik" yerine "belirtileri hafifletmeye yönelik" de
- "konvansiyonel" yerine "standart" de
- Teknik terimleri kullanma; "bilişsel" yerine "düşünme", "oryantasyon" yerine "yer-zaman karışıklığı" de
- Kaynak İngilizce olsa bile cevabı her zaman Türkçe yaz
- Her zaman en fazla 3-4 cümle yaz
- Kullanıcı "annem", "babam", "yakınım" gibi ifadeler kullandığında cevabında "annen", "baban", "yakınınız" diye hitap et, asla "annem" veya "babam" deme
- Sanki hastanın yakınına anlatır gibi empatik ve sade bir dil kullan
- Bilgi belgede yoksa sadece "Bu bilgi dokümanda yer almıyor." de
ÖRNEKLER:
Soru: Alzheimer nedir?
Cevap: Alzheimer, zamanla beyin hücrelerinin hasar görmesiyle ortaya çıkan ve en çok belleği etkileyen bir hastalıktır. Başlangıçta küçük unutkanlıklar gibi görünse de ilerledikçe kişi günlük hayatını tek başına sürdüremez hale gelebilir. Hastalık yavaş ilerlediği için erken fark edilmesi büyük önem taşır. Aileler için de oldukça zorlu bir süreç olduğundan destek almak çok değerlidir.
Soru: Alzheimer'ın ilk belirtileri nelerdir?
Cevap: En sık görülen ilk belirti, yakın zamanda yaşanan olayları unutmaktır; örneğin az önce söylenen bir şeyi tekrar sormak gibi. Bunun yanı sıra tanıdık yerlerde kaybolmak, söylemek istediği kelimeyi bir türlü bulamamak da erken dönem işaretleri arasındadır. Kişi faturalarını ödemeyi ya da randevularını takip etmeyi giderek zorlaştığını fark edebilir. Bu belirtiler görüldüğünde bir uzmana başvurmak erken teşhis açısından çok önemlidir.
"""

CLASSIFIER_PROMPT = """Kullanıcının mesajını aşağıdaki kategorilerden birine yerleştir ve sadece kategori adını yaz:
BİLGİ - Genel bilgi sorusu (hastalık nedir, nasıl ilerler, belirtiler neler gibi)
SINIR_DISI - Tanı, ilaç, tedavi, ameliyat kararı gerektiren soru
ACIL - Acil tıbbi yardım gerektiren durum
KONU_DISI - Alzheimer ile ilgisi olmayan veya kişisel soru
YONLENDIRME - Hangi doktora gideyim sorusu
Sadece kategori adını yaz, başka hiçbir şey yazma.
Örnekler:
"Alzheimer nedir?" → BİLGİ
"Hangi ilacı almalıyım?" → SINIR_DISI
"Yakınım saldırgan davranıyor, ne yapmalıyım?" → BİLGİ
"Alzheimer'da tansiyon ilacı kullanılır mı?" → BİLGİ
"Annemin durumu çok kötü, ne yapmalıyım?" → BİLGİ
"Yakınım saldırgan davranıyor, ne yapabilirim?" → BİLGİ
"Annem bayıldı ne yapayım?" → ACIL
"Hangi doktora gitmeliyim?" → YONLENDIRME
"Senin olayın ne?" → KONU_DISI
"Bugün hava nasıl?" → KONU_DISI
"Yakınımı kaybetmekteyim ve çok üzgünüm" → KONU_DISI"""

SINIR_DISI_CEVAP = """⚠️ Bu konuda size kesin bir bilgi vermem doğru olmaz, çünkü ilaç ve tedavi kararları kişiden kişiye farklılık gösterir ve uzmanlık gerektirir. Lütfen mutlaka bir doktora danışın. Alzheimer hastalığı hakkında genel bilgi sorularında size yardımcı olmaktan memnuniyet duyarım."""

ACIL_CEVAP = """🚨 Bu bir acil durum gibi görünüyor. Lütfen hemen 112'yi arayın ya da en yakın acil servise gidin. Size en hızlı yardımı onlar sağlayabilir."""

KONU_DISI_CEVAP = """Bu konuda yardımcı olamam, ben sadece Alzheimer hastalığı hakkında bilgi verebiliyorum. Alzheimer ile ilgili bir sorunuz varsa memnuniyetle yardımcı olurum."""

YONLENDIRME_CEVAPLARI = {
    "alzheimer": "Nöroloji",
    "unutkanlık": "Nöroloji veya Geriatri",
    "davranış": "Psikiyatri veya Nöroloji",
    "depresyon": "Psikiyatri",
    "default": "Nöroloji"
}

# ── Niyet sınıflandırma ───────────────────────────────────────────────────
def classify_intent(query):
    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": CLASSIFIER_PROMPT},
            {"role": "user", "content": query}
        ],
        temperature=0,
        max_tokens=10
    )
    return res.choices[0].message.content.strip()

# ── HF Dataset'ten PDF listesini çek ─────────────────────────────────────
def list_hf_pdfs():
    api = HfApi()
    files = api.list_repo_files(HF_DATASET, repo_type="dataset", token=HF_TOKEN)
    return [f for f in files if f.endswith(".pdf")]

# ── PDF içeriğini indir ve parse et ──────────────────────────────────────
def load_pdf_from_hf(filename: str) -> list:
    path = hf_hub_download(
        repo_id=HF_DATASET,
        filename=filename,
        repo_type="dataset",
        token=HF_TOKEN
    )
    return PyPDFLoader(path).load()

# ── Index oluştur ─────────────────────────────────────────────────────────
def build_index():
    pdf_names = list_hf_pdfs()
    if not pdf_names:
        return None, "❌ Dataset'te PDF bulunamadı."

    splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=80)
    all_docs = []

    for name in pdf_names:
        try:
            pages = load_pdf_from_hf(name)
            for page in pages:
                page.metadata["source"] = name
            chunks = splitter.split_documents(pages)
            all_docs.extend(chunks)
        except Exception as e:
            print(f"Hata ({name}): {e}")

    if not all_docs:
        return None, "❌ Hiçbir PDF okunamadı."

    vs = FAISS.from_documents(all_docs, embeddings)
    return vs, f"✅ {len(pdf_names)} PDF, {len(all_docs)} chunk ile index hazır."

# ── Uygulama başlarken index oluştur ─────────────────────────────────────
print("Index oluşturuluyor...")
vectorstore, build_status = build_index()
print(build_status)

# ── Soru-cevap (geçmiş destekli) ─────────────────────────────────────────
def chat(query, history=None):
    if vectorstore is None:
        return build_status
    if not query.strip():
        return "Lütfen bir soru girin."

    if history is None:
        history = []

    intent = classify_intent(query)
    print(f"Niyet: {intent}")

    if intent == "ACIL":
        return ACIL_CEVAP

    if intent == "KONU_DISI":
        return KONU_DISI_CEVAP

    if intent == "SINIR_DISI":
        return SINIR_DISI_CEVAP

    if intent == "YONLENDIRME":
        query_lower = query.lower()
        for anahtar, bolum in YONLENDIRME_CEVAPLARI.items():
            if anahtar in query_lower:
                return f"Belirttiğiniz duruma göre {bolum} bölümüne başvurmanızı öneririm. Doktor ismi veremem ama bu bölümdeki bir uzman size en iyi yardımı sağlayacaktır."
        return f"Belirttiğiniz duruma göre {YONLENDIRME_CEVAPLARI['default']} bölümüne başvurmanızı öneririm."

    # BİLGİ soruları
    start = time.time()
    docs = vectorstore.similarity_search(query, k=8)
    context = "\n\n".join([d.page_content for d in docs])
    sources = list(set([
        os.path.basename(d.metadata.get("source", ""))
        for d in docs if d.metadata.get("source")
    ]))

    # Sohbet geçmişini mesajlara ekle (son 6 mesaj)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history[-6:]:
        if isinstance(h, dict):
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        elif isinstance(h, (list, tuple)) and len(h) == 2:
            messages.append({"role": "user", "content": h[0]})
            messages.append({"role": "assistant", "content": h[1]})

    messages.append({"role": "user", "content": f"BİLGİ:\n{context}\n\nSORU: {query}"})

    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.3,
        max_tokens=2000
    )
    elapsed = round(time.time() - start, 2)
    response = res.choices[0].message.content

    source_text = "\n\n📚 Kaynak: " + ", ".join(sources) if sources else ""

    return f"{response}{source_text}\n⏱️ Yanıt süresi: {elapsed} sn"

# ── Arayüz ───────────────────────────────────────────────────────────────
with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown("## 📚 Alzheimer Asistanı")
    gr.Markdown(f"**Durum:** {build_status}")

    query = gr.Textbox(label="Soru", placeholder="Alzheimer hakkında ne öğrenmek istiyorsunuz?")
    history_input = gr.JSON(value=[], visible=False)  # gizli history girişi
    ask_btn = gr.Button("Sor", variant="primary")
    output = gr.Textbox(label="Cevap", lines=8)

    ask_btn.click(chat, [query, history_input], output)
    query.submit(chat, [query, history_input], output)

demo.launch()