# hf-spaces-archive — mirror s1 (2026.09)

Repo ini **jalur transit menuju arsip permanen**, bukan tempat penyimpanan
utama. Isinya cermin berkas dari Hugging Face Space publik, apa adanya,
dikelompokkan `<owner>/<nama>/`.

* Shard: `s1`
* Periode: `2026.09`
* Space: 542
* Byte: 1820318767 (1.70 GiB)

Arsip permanennya ada di Software Heritage. Kalau repo ini suatu saat
dihapus, salinan SWH tetap ada dan tetap bisa diambil.

Ambil satu Space (ganti `<dir>` dengan SWHID direktori Space itu dari
`manifest/swhtree/<periode>.spaces.jsonl`):

    curl -A 'hf-spaces-archive-bot/1.0' -X POST \
      'https://archive.softwareheritage.org/api/1/vault/flat/swh:1:dir:<dir>/'
    # tunggu status "done", lalu:
    curl -A 'hf-spaces-archive-bot/1.0' -L -o space.tar.gz \
      'https://archive.softwareheritage.org/api/1/vault/flat/swh:1:dir:<dir>/raw/'

Atau buka di peramban: `https://archive.softwareheritage.org/swh:1:dir:<dir>/`

Catatan: berkas yang tampak sebagai kredensial sudah disaring sebelum masuk
(26 pola + 47 deny-glob). Hak cipta tiap Space tetap milik pembuatnya;
mirror ini untuk pelestarian.
