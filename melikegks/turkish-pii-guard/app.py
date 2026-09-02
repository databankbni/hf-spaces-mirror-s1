"""Türkçe PII Guard — Hugging Face Space demosu.

Model uçtan uca çalışır: metni alır, maskelenmiş metni döndürür.
Şema dışı etiket üretebildiği için çıktı bir whitelist katmanından geçirilir
ve kullanıcıya ayrıca gösterilir — ham model davranışı gizlenmez.
"""

import os
import re
import time

import gradio as gr
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_ADI = "saturday-labs/turkish-pii-guard-0.8b"

# Konteynerde stdout tamponlanır; loglar anında görünsün diye kapatıyoruz.
os.environ.setdefault("PYTHONUNBUFFERED", "1")

GECERLI_ETIKETLER = {
    "[AD]", "[TCKN]", "[DOGUM_TARIHI]", "[DOGUM_YERI]", "[ANNE_ADI]",
    "[ANNE_KIZLIK]", "[BABA_ADI]", "[PASAPORT_NO]", "[EHLIYET_NO]", "[SGK_NO]",
    "[IMZA]", "[IBAN]", "[HESAP_NO]", "[KART]", "[KART_SKT]", "[CVV]",
    "[MAAS]", "[VERGI_NO]", "[MUSTERI_NO]", "[KREDI_NOTU]", "[POLICE_NO]",
    "[SOZLESME_NO]", "[KRIPTO_CUZDAN]", "[TEL]", "[EMAIL]", "[ADRES]",
    "[KONUM]", "[SAGLIK]", "[DIN]", "[ETNIK_KOKEN]", "[SENDIKA]",
    "[BIYOMETRIK]", "[CEZA_KAYDI]", "[KAN_GRUBU]", "[ENGEL_DURUMU]",
    "[SIFRE]", "[PIN]", "[KULLANICI_ADI]", "[IP_ADRES]", "[MAC_ADRES]",
    "[IMEI]", "[CIHAZ_ID]", "[PLAKA]", "[SASI_NO]", "[MOTOR_NO]",
    "[RUHSAT_NO]", "[SICIL_NO]", "[ISYERI]", "[AILE]", "[REFERANS]",
}

ETIKET_RE = re.compile(r"\[[A-Z_]+\]")
IM_END = "<|im_end|>"

# Egitimde kullanilan SABIT sistem promptu. Cikarimda birebir ayni verilmeli;
# verilmezse model dagilim disina cikar ve kalite belirgin duser.
SISTEM = ("Sen bir Türkçe PII maskeleme servisisin. Verilen talimata göre metindeki "
          "kişisel verileri köşeli parantezli etiketlerle değiştir. Talimatın "
          "kapsamadığı hiçbir şeye dokunma; kelime ekleme, silme, noktalama ve "
          "satır sonlarını koru.")

TALIMATLAR = {
    "Tam maskeleme":
        "Metindeki tüm kişisel ve hassas bilgileri uygun etiketlerle maskele. "
        "Diğer kısımları değiştirme.",
    "Yalnızca IBAN":
        "Yalnızca IBAN bilgisini maskele. Diğer bilgileri değiştirme.",
    "Yalnızca telefon":
        "Sadece telefon numarasını maskele. Geri kalan her şey aynen kalsın.",
    "Ad soyad açık kalsın":
        "Kişinin adını açık bırak. Diğer kişisel bilgileri maskele.",
    "IBAN açık kalsın":
        "IBAN bilgisini değiştirme. Diğer kişisel ve hassas bilgileri maskele.",
    "Sadece finansal veriler":
        "Bu metinde sadece finansal bilgileri maskele.",
    "Sadece özel nitelikli (KVKK md. 6)":
        "Bu metinde sadece KVKK madde 6 kapsamındaki özel nitelikli kişisel "
        "verileri maskele.",
    "Serbest (aşağıya yaz)": "",
}

# ZeroGPU tespiti ORTAM DEĞİŞKENİNDEN yapılmalı, paketin varlığından değil:
# `spaces` requirements.txt'te olduğu için cpu-basic'te de kuruluyor ve
# "import edilebiliyorsa GPU vardır" varsayımı yanlış sonuç veriyor.
# HF, ZeroGPU donanımında SPACES_ZERO_GPU=true tanımlar.
#
# Ayrıca ZeroGPU'da torch.cuda.is_available() açılışta False döner — GPU
# yalnızca @spaces.GPU ile dekore edilmiş fonksiyon çalışırken bağlanır.
# Bu yüzden cuda kontrolü tek başına da yeterli değil.
ZEROGPU = os.environ.get("SPACES_ZERO_GPU", "").lower() in ("1", "true")

if ZEROGPU:
    import spaces
else:
    spaces = None
    # os.cpu_count() konteynerde HOST çekirdek sayısını verir; Space'e ayrılan
    # 2 vCPU'ya 32 thread açmak çekirdekleri birbirine bekletir ve üretimi
    # yavaşlatır. sched_getaffinity cgroup sınırını görür.
    try:
        cekirdek = len(os.sched_getaffinity(0))
    except AttributeError:
        cekirdek = os.cpu_count() or 2
    torch.set_num_threads(max(1, min(cekirdek, 4)))
    print("CPU thread:", torch.get_num_threads(), flush=True)

GPU_VAR = ZEROGPU or torch.cuda.is_available()

print("Model yükleniyor… ZeroGPU:", ZEROGPU, flush=True)
tokenizer = AutoTokenizer.from_pretrained(MODEL_ADI)
# Unsloth ile kaydedilen modellerde Qwen3VLProcessor donebiliyor.
tokenizer = getattr(tokenizer, "tokenizer", tokenizer)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ADI,
    dtype=torch.bfloat16 if GPU_VAR else torch.float32,
).eval()
if GPU_VAR:
    model = model.to("cuda")
# DURMA TOKENI: ikisi de verilmeli. Instruct modelde eos <|im_end|> (248046),
# -Base'de <|endoftext|> (248044). Yalnizca biri verilirse model durmaz ve
# dogru cevabin pesine icerik uydurur.
IM_END_ID = tokenizer.convert_tokens_to_ids(IM_END)
STOP = [i for i in {tokenizer.eos_token_id, IM_END_ID} if i is not None]
print("Model hazır. Cihaz:", next(model.parameters()).device, flush=True)


def gpu_gerekiyorsa(fn):
    """ZeroGPU'da @spaces.GPU uygular, CPU'da fonksiyonu olduğu gibi bırakır."""
    return spaces.GPU(duration=20)(fn) if ZEROGPU else fn


@gpu_gerekiyorsa
@torch.inference_mode()
def maskele(metin, talimat):
    """Maskelenmiş metni ve geçen süreyi döndürür."""
    # EGITIM FORMATIYLA BIREBIR: sabit SISTEM sistem turunda, talimat ve
    # metin birlikte kullanici turunda. Onceki surumde talimat sistem
    # yuvasindaydi ve sabit prompt hic verilmiyordu -> dagilim disi.
    mesajlar = [
        {"role": "system", "content": SISTEM},
        {"role": "user", "content": f"{talimat}\n\n{metin}"},
    ]
    prompt = tokenizer.apply_chat_template(
        mesajlar, tokenize=False, add_generation_prompt=True,
        enable_thinking=False,
    )
    girdi = tokenizer(prompt, return_tensors="pt",
                      add_special_tokens=False).to(model.device)

    # Çıktı girdiyle yaklaşık aynı uzunlukta: maskeleme metni yeniden yazmaz,
    # yalnızca bazı parçaları etiketle değiştirir. Sabit 320 yerine girdiye
    # bağlı sınır, model <|im_end|> üretmezse boşa dönmeyi engeller.
    # Cikti girdiyle yaklasik ayni uzunlukta. Ust sinir 256 idi ve uzun
    # girdileri kesiyordu; 1024'e cikarildi.
    girdi_uzunlugu = girdi["input_ids"].shape[1]
    sinir = min(1024, max(64, int(girdi_uzunlugu * 1.4) + 48))

    baslangic = time.time()
    cikti = model.generate(
        **girdi,
        max_new_tokens=sinir,
        do_sample=False,               # maskeleme belirlenimci olmalı
        eos_token_id=STOP,
        pad_token_id=tokenizer.pad_token_id,
        use_cache=True,
    )
    sure = time.time() - baslangic

    yeni = cikti[0, girdi_uzunlugu:]
    o = tokenizer.decode(yeni, skip_special_tokens=True).strip()
    if "</think>" in o:                      # Qwen3.5 bos dusunme blogu birakir
        o = o.split("</think>", 1)[1].strip()
    return o, sure


def calistir(metin, secim, serbest_talimat):
    metin = (metin or "").strip()
    if not metin:
        return "", "Metin gir.", ""

    talimat = serbest_talimat.strip() if secim == "Serbest (aşağıya yaz)" \
        else TALIMATLAR[secim]
    if not talimat:
        talimat = TALIMATLAR["Tam maskeleme"]

    cikti, sure = maskele(metin, talimat)

    etiketler = ETIKET_RE.findall(cikti)
    uydurma = sorted({e for e in etiketler if e not in GECERLI_ETIKETLER})

    if not etiketler:
        ozet = "Kişisel veri bulunmadı — metin değiştirilmedi."
    else:
        sayim = {}
        for e in etiketler:
            sayim[e] = sayim.get(e, 0) + 1
        ozet = "Maskelenen: " + ", ".join(
            f"{e}×{n}" if n > 1 else e for e, n in sorted(sayim.items()))
    ozet += f"   ·   {sure:.1f} sn"

    if uydurma:
        uyari = (
            f"⚠️ Şema dışı etiket üretildi: {', '.join(uydurma)}\n\n"
            "Model 50 etiketin dışında bir etiket uydurdu — genellikle "
            "metindeki komşu kelimeden türetir. Kör holdout ölçümünde 1.600 "
            "satırda 9 kez görüldü (%0,56). Üretimde bu satırlar reddedilmeli "
            "veya insan incelemesine gönderilmelidir. Geçersiz etiketi metne "
            "geri çevirmeyin — maskelenmiş gerçek veriyi açığa çıkarır."
        )
    else:
        uyari = "✅ Tüm etiketler şema içinde."

    return cikti, ozet, uyari


ORNEKLER = [
    # Tam maskeleme
    [
        "müşteri Ahmet Yıldız 0542 321 45 67 numarasından aradı, "
        "iade hesabı TR12 0001 2000 0034 5678 9012 34",
        "Tam maskeleme",
        "Metindeki tüm kişisel ve hassas bilgileri maskele.",
    ],
    [
        "tc kimlik numaram otuz dört yirmi üç altmış beş yetmiş sekiz doksan bir, "
        "acil bakar mısınız",
        "Tam maskeleme",
        "Metindeki tüm kişisel ve hassas bilgileri maskele.",
    ],
    [
        "aracımın plakası 34 ABC 123, şasi numarası NM0KXXTTFKJ123456 "
        "kasko yenilenecek",
        "Tam maskeleme",
        "Plaka ve araç kimlik bilgileri dahil tüm kişisel verileri maskele.",
    ],

    # Birbirine benzeyen sayısal değerler
    [
        "kart numaram 5401 2345 6789 1234 işlem yapamıyorum",
        "Sadece finansal veriler",
        "Yalnızca finansal bilgileri maskele.",
    ],
    [
        "ürün seri numarası 5401234567891234 olarak kayıtlı",
        "Tam maskeleme",
        "Kişisel veri varsa maskele; ürün seri numarasını değiştirme.",
    ],
    [
        "işlem kodu 419 ama kartın arkasındaki güvenlik kodu 732",
        "Tam maskeleme",
        "Kişisel ve finansal bilgileri maskele; işlem kodunu değiştirme.",
    ],
    [
        "kargo takip kodu 12345678901 henüz hareket etmemiş",
        "Ad soyad açık kalsın",
        "Ad soyadı açık bırak; diğer kişisel bilgileri maskele.",
    ],
    [
        "maaşım 45.000 TL kredi başvurusu için yeterli mi",
        "Sadece finansal veriler",
        "Yalnızca finansal bilgileri maskele.",
    ],

    # Aynı metne uygulanan farklı politikalar
    [
        "Ali Kaya 0532 111 22 33 numarasından aradı, "
        "ibanı TR33 0006 1005 1978 6457 8413 26",
        "Yalnızca IBAN",
        "Yalnızca IBAN bilgisini maskele.",
    ],
    [
        "Ali Kaya 0532 111 22 33 numarasından aradı, "
        "ibanı TR33 0006 1005 1978 6457 8413 26",
        "IBAN açık kalsın",
        "IBAN bilgisini açık bırak; diğer kişisel bilgileri maskele.",
    ],
    [
        "Ali Kaya 0532 111 22 33 numarasından aradı, "
        "ibanı TR33 0006 1005 1978 6457 8413 26",
        "Yalnızca telefon",
        "Yalnızca telefon numarasını maskele.",
    ],
    [
        "Ali Kaya 0532 111 22 33 numarasından aradı, "
        "ibanı TR33 0006 1005 1978 6457 8413 26",
        "Ad soyad açık kalsın",
        "Ad soyadı açık bırak; diğer kişisel bilgileri maskele.",
    ],

    # Seçici hazır politikalar
    [
        "iban: TR330006100519786457841326, telefon: 05321112233",
        "Yalnızca telefon",
        "Yalnızca telefon numarasını maskele.",
    ],
    [
        "Müşteri Selin Aksoy tc 10000000146 telefon 0507 123 45 67",
        "Ad soyad açık kalsın",
        "Ad soyadı açık bırak; diğer kişisel bilgileri maskele.",
    ],
    [
        "başvuru sahibi Zeynep Arslan, mail zeynep.arslan@firma.com.tr, "
        "adres Cumhuriyet Mah. Lale Sok. No:14 Kadıköy İstanbul",
        "Ad soyad açık kalsın",
        "Ad soyadı açık bırak; e-posta ve adres bilgilerini maskele.",
    ],
    [
        "personel kaydımda kan grubum A Rh negatif ve inanç bilgim Alevi yazıyor",
        "Sadece özel nitelikli (KVKK md. 6)",
        "Yalnızca özel nitelikli kişisel verileri maskele.",
    ],

    # Serbest talimatlar
    [
        "Elif Demir telefon 0532 456 78 90 e-posta elif.demir@example.com "
        "müşteri 847291",
        "Serbest (aşağıya yaz)",
        "Telefon ve e-posta adresini maskele; ad soyad ile müşteri numarasına dokunma.",
    ],
    [
        "Dr. Can Eren kan grubum 0 Rh pozitif, telefonum 0506 222 31 40.",
        "Serbest (aşağıya yaz)",
        "Yalnızca sağlık bilgisini maskele; ad soyad ve telefon açık kalsın.",
    ],
    [
        "Ödeme için IBAN TR33 0006 1005 1978 6457 8413 26, "
        "kart 5401 2345 6789 1234 ve telefon 0532 111 22 33.",
        "Serbest (aşağıya yaz)",
        "IBAN ve kart numarasını maskele; telefon numarasına dokunma.",
    ],
    [
        "Sunucu erişimi: kullanıcı adı mdemir, IP 88.240.12.34, "
        "MAC 00:1A:2B:3C:4D:5E.",
        "Serbest (aşağıya yaz)",
        "Yalnızca IP ve MAC adresini maskele; kullanıcı adı açık kalsın.",
    ],
    [
        "Başvuru sahibi Derya Şen, TCKN 10000000146, "
        "adresi Moda Cad. No:8 Kadıköy, maaşı 52.000 TL.",
        "Serbest (aşağıya yaz)",
        "Kimlik ve adres bilgilerini maskele; maaşı açık bırak.",
    ],
]
ACIKLAMA = """
# Türkçe PII Guard

Türkçe metindeki kişisel verileri tespit edip maskeleyen 0.8B model.
50 etiket tanır ve **kapsam talimatını okur** — aynı metin farklı politika
altında farklı maskelenir.

Model [saturday-labs/turkish-pii-guard-0.8b](https://huggingface.co/saturday-labs/turkish-pii-guard-0.8b)

"""

with gr.Blocks(title="Türkçe PII Guard") as demo:
    gr.Markdown(ACIKLAMA)

    with gr.Row():
        with gr.Column():
            metin = gr.Textbox(
                label="Metin", lines=5,
                placeholder="müşteri Ahmet Yıldız 0542 321 45 67 numarasından aradı…",
            )
            secim = gr.Radio(
                choices=list(TALIMATLAR), value="Tam maskeleme",
                label="Maskeleme politikası",
            )
            serbest = gr.Textbox(
                label="Serbest talimat", lines=2,
                placeholder="Örn: Maaşı gizle, ad soyad ve telefona dokunma.",
            )
            calistir_btn = gr.Button("Maskele", variant="primary")

        with gr.Column():
            cikti = gr.Textbox(label="Maskelenmiş metin", lines=5,
                               show_copy_button=True)
            ozet = gr.Textbox(label="Özet", lines=2)
            uyari = gr.Textbox(label="Şema kontrolü", lines=4)

    gr.Examples(examples=ORNEKLER, inputs=[metin, secim, serbest])

    calistir_btn.click(calistir, [metin, secim, serbest], [cikti, ozet, uyari])
    metin.submit(calistir, [metin, secim, serbest], [cikti, ozet, uyari])

demo.queue().launch()
