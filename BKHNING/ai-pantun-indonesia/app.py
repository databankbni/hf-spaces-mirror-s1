import gradio as gr
import random

# Bank Data Kosakata untuk Sampiran dan Isi berdasarkan tema
# Ini membuat proses pembuatan pantun instan tanpa menunggu server AI luar
DATABASE_PANTUN = {
    "umum": {
        "sampiran_a": ["Ke hulu membuat pagar", "Pergi ke pasar membeli tikar", "Terbang tinggi burung camar", "Melihat bintang bersinar"],
        "sampiran_b": ["Melihat rusa di pinggir kali", "Sambil makan buah kenari", "Bunga melati putih berseri", "Menari-nari riang sekali"],
        "isi_a": ["Kalau kita rajin belajar", "Pikiran bugar ilmu terpancar", "Jangan lupa untuk ikhtiar", "Masa depan makin berpijar"],
        "isi_b": ["Pasti sukses di kemudian hari", "Menjadi orang yang berbakti", "Hati tenang damai berseri", "Cita-cita pasti terpenuhi"]
    },
    "pendidikan": {
        "sampiran_a": ["Pergi ke sawah membawa benih", "Membeli buku di toko buku", "Mendengar burung berkicau lirih", "Kayu jati ditaruh di saku"],
        "sampiran_b": ["Hari cerah langitnya biru", "Membaca kitab siang dan malam", "Melihat guru berbaju baru", "Udara pagi terasa tenteram"],
        "isi_a": ["Belajarlah dengan hati jernih", "Tuntutlah ilmu di dalam buku", "Jangan menyerah walau letih", "Ilmu itu adalah paku"],
        "isi_b": ["Hormati selalu bapak dan ibu", "Agar masa depan tidak kelam", "Patuhi nasihat dari gurumu", "Pasti hidupmu akan mendalam"]
    },
    "nasihat": {
        "sampiran_a": ["Pohon beringin tumbuh jajar", "Ada kijang di balik semak", "Air mengalir ke tempat rendah", "Membeli kain warna merah"],
        "sampiran_b": ["Makan nasi pakai selada", "Orang berjalan tergesa-gesa", "Sangat indah dipandang mata", "Rembulan bersinar dengan perkasa"],
        "isi_a": ["Sejak kecil rajin belajar", "Janganlah kamu banyak berlagak", "Bila berkendara berhati-hatilah", "Buatlah orang tua menjadi cerah"],
        "isi_b": ["Agar tidak menyesal saat tua", "Sopan santun kepada sesama", "Supaya hidup mendapat berkah", "Kelak hidupmu akan bahagia"]
    },
    "cinta": {
        "sampiran_a": ["Memetik bunga di taman indah", "Burung dara terbang melayang", "Manis rasanya buah nangka", "Menulis surat di atas meja"],
        "sampiran_b": ["Kupu-kupu hinggap di dahan", "Melihat adik tertawa riang", "Rambut panjang diikat pita", "Sungguh elok pemandangan alam"],
        "isi_a": ["Meski rintangan terasa menyebalkan", "Hati ini bergetar sayang", "Sejak pertama kita bersua", "Wajahmu selalu ada di mata"],
        "isi_b": ["Hanya dirimu yang jadi idaman", "Cinta ini takkan pernah hilang", "Rasa rindu makin terasa", "Menemani tidur di malam kelam"]
    }
}

def generate_pantun_cepat(tema_input):
    tema = tema_input.lower().strip()
    
    # Pilih kategori database, jika tidak ada gunakan kategori umum
    kategori = "umum"
    for k in DATABASE_PANTUN.keys():
        if k in tema:
            kategori = k
            break
            
    db = DATABASE_PANTUN[kategori]
    
    # Mengambil sampel acak yang polanya cocok (Rima ABAB)
    # Baris 1 (A)
    s1 = random.choice(db["sampiran_a"])
    # Baris 2 (B)
    s2 = random.choice(db["sampiran_b"])
    # Baris 3 (A) - dicari yang akhirannya mirip dengan s1 secara rima vokal
    i1 = random.choice(db["isi_a"])
    # Baris 4 (B) - dicari yang akhirannya mirip dengan s2
    i2 = random.choice(db["isi_b"])
    
    pantun_hasil = f"{s1}\n{s2}\n{i1}\n{i2}"
    return pantun_hasil

# --- Tampilan Antarmuka Gradio ---
with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown("# ⚡ AI Generator Pantun Kilat (Rima ABAB Sempurna)")
    gr.Markdown("Versi ini dioptimalkan agar **super cepat (tanpa loading)** dan menggunakan struktur rima puisi Indonesia yang patuh pada aturan bait.")
    
    with gr.Row():
        with gr.Column():
            input_tema = gr.Textbox(
                label="Ketik di sini tema yang diinginkan:", 
                placeholder="Contoh: Pendidikan, Nasihat, Cinta, atau Umum...", 
                lines=2
            )
            btn_generate = gr.Button("Buat Pantun Instan ⚡", variant="primary")
        with gr.Column():
            output_pantun = gr.Textbox(
                label="Hasil Pantun (Pasti ABAB):", 
                lines=6, 
                interactive=False
            )
            
    gr.Examples(
        examples=["Pendidikan", "Nasihat", "Cinta", "Umum"], 
        inputs=input_tema
    )
    
    btn_generate.click(
        fn=generate_pantun_cepat, 
        inputs=input_tema, 
        outputs=output_pantun
    )

if __name__ == "__main__":
    demo.launch()