# Backend - Matrikulasi Matematika KG API

FastAPI yang membungkus dua pipeline yang sebelumnya ada di notebook:

- `pipeline_ekstraksi_konsep_kg.ipynb` -> `POST /pdf/extract` (upload PDF modul, ekstraksi konsep baru, simpan ke Neo4j)
- `pipeline_klasifikasi_youtube_kg.ipynb` -> `POST /youtube/classify` (link YouTube, klasifikasi ke Konsep yang sudah ada / closed vocabulary)

Kedua endpoint memanggil LLM (Gemini) berkali-kali dan bisa makan waktu, jadi keduanya jalan sebagai
**background job**: request langsung balas `202` dengan `job_id`, progress & hasil akhir dicek lewat
`GET /jobs/{job_id}`. Job disimpan in-memory (hilang kalau server di-restart) -- cukup untuk
development/demo, belum untuk production multi-instance.

## Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate atau .\.venv\Scripts\Activate.ps1 
pip install -r requirements.txt
copy .env.example .env
```

Isi `.env`: `GEMINI_API_KEY`, `YOUTUBE_API_KEY`, `NEO4J_PASSWORD` (dan sesuaikan `NEO4J_URI`/`NEO4J_DATABASE`
kalau beda dari default), plus `JWT_SECRET_KEY` (isi string acak yang panjang). Neo4j harus sudah jalan
dan punya database yang sesuai.

Buat akun dosen pertama (tidak ada self-register -- lihat bagian Auth di bawah):

```bash
python scripts/seed_dosen.py --nama "Nama Dosen" --email dosen@kampus.ac.id
```

## Menjalankan

```bash
uvicorn app.main:app --reload --port 8000
```

Dokumentasi interaktif: http://localhost:8000/docs (klik "Authorize" dan isi `Bearer <access_token>`
hasil `/auth/login` buat coba endpoint yang butuh login).

## Auth & Peran

Tidak ada self-register. Akun dosen pertama dibuat lewat `scripts/seed_dosen.py`; dosen itu lalu bisa
bikin akun dosen lain (`POST /dosen/dosen`) dan akun mahasiswa (`POST /dosen/mahasiswa`) -- keduanya
mengembalikan password awal sekali di response, harus disampaikan manual ke pemiliknya. Semua endpoint
`/dosen/*` dan `/mahasiswa/*` butuh header `Authorization: Bearer <access_token>` dari `POST /auth/login`,
dan role token harus cocok dengan prefix router-nya.

## Endpoint

| Method | Path                          | Role      | Keterangan |
|--------|-------------------------------|-----------|------------|
| POST   | `/auth/login`                 | publik    | `{email, password}` -> `access_token` |
| GET    | `/auth/me`                    | login     | Info user yang sedang login |
| PUT    | `/auth/me/password`           | login     | Ganti password sendiri |
| POST   | `/dosen/mahasiswa`             | dosen     | Buat akun mahasiswa -> password awal |
| GET    | `/dosen/mahasiswa`             | dosen     | List mahasiswa |
| PUT    | `/dosen/mahasiswa/{id}`        | dosen     | Aktifkan/nonaktifkan akun |
| POST   | `/dosen/dosen`                 | dosen     | Buat akun dosen lain -> password awal |
| POST   | `/dosen/soal/suggest-konsep`   | dosen     | `{bab_id, teks_soal}` -> saran nama konsep (LLM, closed vocabulary Bab itu) |
| POST   | `/dosen/soal`                  | dosen     | Buat `:Soal` (isian_singkat/esai) + konsep yang diuji |
| GET    | `/dosen/soal?bab_id=`          | dosen     | List soal per Bab |
| DELETE | `/dosen/soal/{id}`             | dosen     | Hapus soal |
| GET    | `/dosen/penilaian?bab_id=&status=` | dosen | Antrian jawaban mahasiswa yang perlu/sudah dinilai |
| PUT    | `/dosen/penilaian/{jawaban_id}`| dosen     | Input nilai manual -> `status=dinilai` |
| GET    | `/dosen/dashboard`             | dosen     | Ringkasan jumlah mahasiswa/modul/soal/antrian nilai |
| POST   | `/pdf/extract`                  | dosen     | Upload PDF modul (multipart, field `file`) -> job ekstraksi konsep |
| POST   | `/youtube/classify`             | dosen     | `{link, materi_query?}` -> job klasifikasi ke Konsep existing |
| GET    | `/mahasiswa/dashboard`          | mahasiswa | List Modul + ringkasan nilai/status per Bab |
| GET    | `/mahasiswa/bab/{bab_id}/soal`  | mahasiswa | Soal Bab itu (tanpa kunci jawaban), status sudah dijawab atau belum |
| POST   | `/mahasiswa/bab/{bab_id}/jawaban`| mahasiswa | Submit jawaban batch -> `status=menunggu_penilaian` |
| GET    | `/mahasiswa/bab/{bab_id}/hasil`| mahasiswa | Nilai Bab, nilai per konsep, diagnosis (remedial/pengayaan/lanjut) + rekomendasi video |
| GET    | `/jobs`, `/jobs/{job_id}`      | publik    | Status/hasil background job PDF & YouTube |
| GET    | `/kg/konsep`, `/kg/modul`, `/kg/video` | publik | Baca isi Knowledge Graph |
| GET    | `/health`                     | publik    | Health check |

## Diagnosis & Rekomendasi (per Bab)

Setelah dosen menilai semua jawaban mahasiswa untuk Bab tertentu, `GET /mahasiswa/bab/{bab_id}/hasil`
menghitung `nilai_bab` (rata-rata nilai) dan `nilai_per_konsep`, lalu:

- `nilai_bab < 70` -> **remedial**, fokus ke konsep-konsep yang nilainya < 70.
- `nilai_bab >= 70` tapi ada konsep < 70 -> **pengayaan**, fokus ke konsep-konsep lemah itu.
- `nilai_bab >= 70` dan semua konsep >= 70 -> **lanjut**, fokus ke konsep-konsep Bab berikutnya.

Video rekomendasi dicari lewat **content-based filtering pakai Jaccard similarity**: himpunan nama
konsep fokus dibandingkan dengan himpunan konsep tiap `:MateriYoutube` (hasil pipeline klasifikasi
YouTube), video dengan similarity tertinggi yang direkomendasikan duluan.

## Catatan

- Jalur `/pdf/extract` cuma mendukung PDF dengan halaman **Daftar Isi** yang bisa diparsing (sama
  seperti notebook aslinya). Jalur bookmark PDF dan fallback deteksi struktur via LLM belum
  diimplementasikan -- akan melempar error yang jelas kalau PDF tidak cocok dengan jalur Daftar Isi.
- Semantic chunking pakai `sentence-transformers` (`paraphrase-multilingual-MiniLM-L12-v2`), model
  akan diunduh otomatis dari Hugging Face saat pertama kali dipakai (butuh koneksi internet).
- Konsisten dengan `ontology_schema.json` -> `vocabulary_policy`: hanya jalur PDF yang boleh membuat
  Konsep baru; jalur YouTube dan saran-konsep-soal murni klasifikasi ke Konsep yang sudah ada.
- Soal cuma bisa dilekatkan ke **Bab** (bukan SubBab). Kandidat konsep untuk sebuah Bab dihitung dari
  SubBab-nya kalau Bab itu punya SubBab (lihat `konsep_kandidat()` di `app/services/soal_pipeline.py`),
  karena `HAS_KONSEP` di pipeline PDF cuma nempel di unit leaf.
