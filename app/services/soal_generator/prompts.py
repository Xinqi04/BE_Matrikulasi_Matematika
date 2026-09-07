"""Prompt buat generate draf soal per Bab lewat LLM. Pola closed-vocabulary buat field `konsep`
sama persis dengan `_PROMPT_SARAN_KONSEP` di `soal_pipeline.py` -- LLM cuma boleh milih dari konsep
yang sudah ada di Bab itu, gak boleh bikin nama konsep baru.
"""

from __future__ import annotations

_TEMPLATE = """Kamu adalah asisten yang membantu dosen membuat draf soal ujian untuk satu Bab materi
kuliah. Draf ini akan DITINJAU dan diedit dosen sebelum disimpan -- jadi fokus ke kejelasan &
kebenaran konsep, bukan sekadar kuantitas.

Bab: {nomor}. {nama}
Ringkasan materi Bab ini:
\"\"\"
{ringkasan}
\"\"\"

Berikut daftar KONSEP yang ada di Bab ini (format "nama -- deskripsi"). Field "konsep" pada tiap
soal HARUS diisi dengan menyalin PERSIS nama dari daftar ini -- jangan diparafrase, dan DILARANG
membuat nama konsep baru di luar daftar:
{daftar_konsep}

Tugas: buat TEPAT {jumlah} soal untuk Bab ini.
- {instruksi_tipe}
- {instruksi_kesulitan}
- Setiap soal boleh menguji SATU atau LEBIH konsep sekaligus. Kalau menggabungkan lebih dari satu
  konsep, pastikan konsep-konsep itu benar-benar berhubungan secara isi (misal salah satu jadi
  prasyarat/bagian dari yang lain) -- JANGAN menggabungkan konsep yang tidak nyambung cuma demi
  variasi. Variasikan kombinasi antar soal (ada yang 1 konsep, ada yang beberapa) sepanjang tetap
  masuk akal.
- Setiap soal harus jelas, tidak ambigu, dan bisa dijawab murni dari materi Bab ini.
- Dalam teks_soal dan jawaban_referensi, tulis ekspresi matematika sebagai LaTeX
  di antara tanda dolar untuk inline atau dolar ganda untuk blok. Gunakan notasi
  LaTeX untuk pecahan, akar, pangkat, dan simbol; escape backslash sesuai JSON.
- Soal tipe "esai" wajib punya "jawaban_referensi" berupa ringkasan poin-poin kunci/rubrik singkat
  (bukan jawaban penuh kata demi kata). Soal tipe "isian_singkat" wajib punya "jawaban_referensi"
  berupa jawaban singkat & pasti (satu istilah/nilai/kalimat pendek).

Balas HANYA dengan JSON array valid, tanpa teks lain, tanpa markdown code fence. Format tiap item:
{{
  "teks_soal": "...",
  "tipe": "isian_singkat" atau "esai",
  "tingkat_kesulitan": "mudah" atau "sedang" atau "sulit",
  "konsep": ["nama konsep -- SALIN PERSIS dari daftar", "..."],
  "jawaban_referensi": "..."
}}
"""


def build_prompt(
    nomor: str, nama: str, ringkasan: str, daftar_konsep: list[dict],
    jumlah: int, tipe: str | None, tingkat_kesulitan: str | None,
) -> str:
    if tipe:
        instruksi_tipe = f'Semua soal harus bertipe "{tipe}".'
    else:
        instruksi_tipe = 'Variasikan tipe soal antara "isian_singkat" dan "esai".'

    if tingkat_kesulitan:
        instruksi_kesulitan = f'Semua soal harus bertingkat kesulitan "{tingkat_kesulitan}".'
    else:
        instruksi_kesulitan = 'Variasikan tingkat kesulitan antara "mudah", "sedang", dan "sulit".'

    daftar_konsep_text = "\n".join(
        f"- {k['nama']} -- {k['deskripsi']}" if k.get("deskripsi") else f"- {k['nama']}"
        for k in daftar_konsep
    )

    return _TEMPLATE.format(
        nomor=nomor, nama=nama, ringkasan=ringkasan.strip() or "(tidak ada ringkasan)",
        daftar_konsep=daftar_konsep_text, jumlah=jumlah,
        instruksi_tipe=instruksi_tipe, instruksi_kesulitan=instruksi_kesulitan,
    )
