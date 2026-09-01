# Backend MathDasar

Backend aplikasi matrikulasi matematika berbasis FastAPI. Backend menggunakan PostgreSQL untuk
akun, autentikasi, enrollment, dan data transaksional; Neo4j digunakan untuk struktur modul,
Bab, konsep, materi, dan knowledge graph.

Backend, PostgreSQL, dan Neo4j dijalankan bersama menggunakan Docker Compose. Frontend tidak
dijalankan melalui Docker.

## Teknologi

- Python 3.12
- FastAPI dan Uvicorn
- PostgreSQL 16
- Neo4j 5.26 Community
- Google Gemini API
- YouTube Data API v3
- Docker Desktop dan Docker Compose

## Prasyarat

Instal aplikasi berikut:

1. Docker Desktop versi terbaru dengan Docker Compose v2.
2. Git, jika project diambil dari repository.
3. Koneksi internet untuk mengunduh image Docker dan memakai layanan Gemini/YouTube.

Python lokal tidak wajib karena aplikasi Python berjalan di dalam container.

Pastikan Docker Desktop sudah aktif:

```powershell
docker --version
docker compose version
```

## Struktur penting

```text
backend/
├── app/                    # Source code FastAPI
├── database/               # Skema dan init database
├── scripts/                # Seed dan utilitas migrasi
├── uploads/                # Upload lokal jika berjalan tanpa Docker
├── kg_snapshot.json        # Snapshot awal struktur knowledge graph
├── .env.example            # Contoh konfigurasi aplikasi
├── .env.docker.example     # Contoh konfigurasi database Docker
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Konfigurasi environment

Jalankan dari folder `backend`:

```powershell
Copy-Item .env.example .env
Copy-Item .env.docker.example .env.docker
```

Jika kedua file sudah tersedia, jangan disalin ulang karena dapat menimpa konfigurasi.

### File `.env`

Isi minimal variabel berikut:

```dotenv
GEMINI_API_KEY=api-key-gemini
YOUTUBE_API_KEY=api-key-youtube
JWT_SECRET_KEY=string-acak-yang-panjang-dan-rahasia
```

Variabel lain sudah memiliki contoh/default di `.env.example`.

- `GEMINI_API_KEY` digunakan untuk ekstraksi PDF, klasifikasi materi, dan pembuatan soal.
- `YOUTUBE_API_KEY` digunakan untuk mengambil informasi video YouTube.
- `JWT_SECRET_KEY` digunakan untuk menandatangani token login.

Backend mensyaratkan ketiga variabel ada saat startup. Untuk development tanpa memakai fitur
Gemini atau YouTube, isi API key dengan placeholder non-kosong; fitur terkait tetap tidak akan
berfungsi sampai key yang valid digunakan.

### File `.env.docker`

Ganti password contoh dengan password sendiri:

```dotenv
POSTGRES_DB=matrikulasi
POSTGRES_USER=matrikulasi
POSTGRES_PASSWORD=password-postgres-yang-kuat
POSTGRES_PORT=5433

NEO4J_PASSWORD=password-neo4j-yang-kuat
NEO4J_HTTP_PORT=7474
NEO4J_BOLT_PORT=7687
NEO4J_DATABASE=neo4j
```

Jangan commit `.env` atau `.env.docker` ke repository.

## Menjalankan backend

Buka PowerShell di folder backend:

```powershell
cd "D:\KULIAH\TUGAS AKHIR\web\web matrikulasi\backend"
docker compose --env-file .env.docker up -d --build
```

Perintah tersebut menjalankan:

- `postgres` pada port host `5433`
- `neo4j` pada port `7474` dan `7687`
- `neo4j-init` untuk membuat constraint
- `backend` pada port `8000`

Backend tidak perlu dijalankan lagi menggunakan `uvicorn` secara manual selama container backend
aktif.

## Memeriksa status

```powershell
docker compose --env-file .env.docker ps
```

Semua service utama seharusnya berstatus `healthy`.

Periksa endpoint health:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Respons yang diharapkan:

```json
{"status":"ok"}
```

Alamat layanan:

- API: http://localhost:8000
- Swagger/OpenAPI: http://localhost:8000/docs
- Neo4j Browser: http://localhost:7474
- PostgreSQL dari host: `localhost:5433`

## Mengimpor knowledge graph saat setup pertama kali

Setelah semua container berstatus sehat, masukkan data awal knowledge graph dari
`kg_snapshot.json`. Pastikan file tersebut berada langsung di folder `backend`:

```text
backend/
├── kg_snapshot.json
├── docker-compose.yml
└── scripts/
```

Jalankan perintah berikut dari folder `backend`:

```powershell
docker compose --env-file .env.docker cp .\kg_snapshot.json backend:/tmp/kg_snapshot.json
docker compose --env-file .env.docker exec backend python scripts/import_kg_snapshot.py `
  --uri bolt://neo4j:7687 `
  --database neo4j `
  --input /tmp/kg_snapshot.json
```

Jika berhasil, terminal menampilkan jumlah node dan relasi yang diimpor, misalnya:

```text
Node: 120, relasi: 245 berhasil diimpor.
```

Impor ini cukup dilakukan sekali setelah volume Neo4j pertama kali dibuat. Script menggunakan
`MERGE`, sehingga aman dijalankan ulang jika proses sebelumnya terputus atau hasil impor perlu
dipastikan kembali.

Snapshot hanya berisi struktur knowledge graph seperti modul, bab, subbab, konsep, dan materi.
Snapshot tidak berisi akun, password, enrollment, jawaban, atau nilai. Buat akun dummy secara
terpisah menggunakan langkah pada bagian berikutnya.

## Membuat akun dummy

Setelah semua container sehat:

```powershell
docker compose --env-file .env.docker exec backend python scripts/seed_postgres_dummy.py
```

Script bersifat idempotent: akun yang sudah ada akan dilewati.

| Role | NIM/ID | Password |
|---|---|---|
| Admin | `ADM001` | `admin123` |
| Dosen | `DSN001` | `dosen123` |
| Mahasiswa | `MHS001` | `mahasiswa123` |

Kredensial tersebut hanya untuk development/demo. Ganti password untuk penggunaan nyata.

## Enrollment mahasiswa

Mahasiswa baru belum otomatis memiliki modul. Login sebagai admin melalui frontend, buka menu
Mahasiswa, klik **Atur Modul**, pilih modul, lalu simpan enrollment.

## Log dan restart

Melihat log backend:

```powershell
docker compose --env-file .env.docker logs -f backend
```

Restart backend:

```powershell
docker compose --env-file .env.docker restart backend
```

Setelah source backend diubah, image harus dibangun ulang:

```powershell
docker compose --env-file .env.docker up -d --build backend
```

## Menghentikan aplikasi

Menghentikan container tanpa menghapus data:

```powershell
docker compose --env-file .env.docker down
```

Jangan tambahkan `-v` kecuali memang ingin menghapus seluruh volume PostgreSQL, Neo4j, dan upload.

## Menjalankan backend tanpa Docker (opsional)

Cara ini tetap membutuhkan PostgreSQL dan Neo4j yang aktif serta konfigurasi host/port yang sesuai.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Untuk workflow project ini, cara Docker lebih disarankan.

## Troubleshooting

### Port 5433 sudah digunakan

Cari container yang memakai port tersebut:

```powershell
docker ps --format "table {{.Names}}\t{{.Ports}}"
```

Hentikan stack lama tanpa menghapus volumenya, atau ubah `POSTGRES_PORT` di `.env.docker`.

### Backend tidak dapat dihubungi

```powershell
docker compose --env-file .env.docker ps
docker compose --env-file .env.docker logs --tail 100 backend
Invoke-RestMethod http://localhost:8000/health
```

### Perubahan kode backend belum muncul

Backend tidak memakai bind mount source. Build ulang container:

```powershell
docker compose --env-file .env.docker up -d --build backend
```

### Database ingin direset total

Perintah berikut menghapus seluruh data dan tidak dapat dipulihkan kecuali ada backup:

```powershell
docker compose --env-file .env.docker down -v
docker compose --env-file .env.docker up -d --build
```

Gunakan hanya jika benar-benar ingin memulai database kosong.
