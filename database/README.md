# Skema dual database

## Keputusan ownership

PostgreSQL menyimpan data yang membutuhkan transaksi, constraint, audit, dan agregasi stabil:

- `users`: akun admin/dosen/mahasiswa dan autentikasi hanya dengan `nim` + password (tanpa email).
- `enrollments`: mahasiswa mengambil modul.
- `questions`: teks soal, kunci, tipe, pembuat, dan flag soal ujian.
- `assessment_attempts`, `attempt_questions`, `answers`: proses ujian, jawaban, nilai, dan antrean penilaian.
- `graph_outbox`: event yang belum/sudah diproyeksikan ke Neo4j.

Neo4j menyimpan data yang nilai utamanya berasal dari traversal dan konektivitas:

- `Modul`, `Bab`, `SubBab`, `Konsep`, `Materi` (nama dipertahankan agar cocok dengan Cypher saat ini).
- Relasi kurikulum: `HAS_BAB`, `HAS_SUBBAB`, `HAS_KONSEP`.
- Relasi semantik: `PRASYARAT`, `RELATED_TO`, `MEMBAHAS_KONSEP`.
- `SoalRef` hanya berisi `id` PostgreSQL dan terhubung dengan `MENGUJI`; teks soal tidak diduplikasi.

Model graph yang dituju:

```text
(Modul)-[:HAS_BAB]->(Bab)-[:HAS_SUBBAB]->(SubBab)
       (Bab|SubBab)-[:HAS_KONSEP]->(Konsep)
                    (Konsep)-[:PRASYARAT]->(Konsep)
                     (Materi)-[:MEMBAHAS_KONSEP]->(Konsep)
                     (SoalRef)-[:MENGUJI]->(Konsep)
```

`module_id` dan `chapter_id` pada PostgreSQL sengaja berupa external ID tanpa foreign key lintas
database. Validasi keberadaan dilakukan service sebelum transaksi ditulis. PostgreSQL tidak boleh
menyalin seluruh node kurikulum karena itu akan menciptakan dua source of truth.

## Role dan batas kewenangan

| Role | Kewenangan |
|---|---|
| `admin` | Kelola semua akun, enrollment, modul/Bab/SubBab/konsep, materi, dan bank soal. |
| `dosen` | Melihat antrean jawaban dan memberikan/mengubah nilai. Tidak mengelola akun, modul, atau soal. |
| `mahasiswa` | Melihat modul yang diambil, mengerjakan ujian, melihat hasil dan rekomendasi. |

Kolom `nim` dipakai sebagai ID login unik untuk ketiga role sesuai kebutuhan aplikasi. Untuk admin
dan dosen, nilainya dapat berupa nomor pegawai/kode akun walaupun nama kolomnya tetap `nim`.

## Konsistensi antar-database

Jangan memakai dual-write langsung dalam satu request. Simpan perubahan soal dan satu record
`graph_outbox` dalam transaksi PostgreSQL yang sama. Worker kemudian melakukan `MERGE SoalRef`
dan relasi `MENGUJI` di Neo4j, lalu mengisi `processed_at`. Operasi worker harus idempotent. Pembacaan
yang menggabungkan nilai dan konsep dilakukan application layer: ambil agregat nilai dari PostgreSQL,
lalu ambil konsep/rekomendasi dari Neo4j menggunakan daftar ID.

## Menjalankan skema

```powershell
cd backend
Copy-Item .env.docker.example .env.docker
# edit password di .env.docker
docker compose --env-file .env.docker up -d --build
docker compose --env-file .env.docker ps
```

PostgreSQL tersedia di `localhost:5433`, Neo4j Browser di `http://localhost:7474`, dan Bolt di
`bolt://localhost:7687`. Untuk image Community, nama database Neo4j yang dipakai adalah `neo4j`.

Init SQL hanya otomatis berjalan ketika volume PostgreSQL masih kosong. Untuk mengubah skema setelah
mulai dipakai, tambahkan migration tool (disarankan Alembic), jangan mengedit init file dan berharap
container menjalankannya ulang. Init Neo4j aman dijalankan kembali karena memakai `IF NOT EXISTS`.

## Dampak ke kode saat migrasi berikutnya

Backend saat ini masih membaca `User`, `Soal`, `UjianModul`, `JawabanUjian`, `MENGAMBIL`, dan
`MENJAWAB` dari Neo4j. Repository tersebut perlu dipindahkan ke PostgreSQL. Query kurikulum tetap
memakai label Neo4j yang sama. Node `Soal` lama kemudian diganti proyeksi ringan `SoalRef` khusus
untuk relasi konsep. Compose ini menyiapkan database target, bukan otomatis memindahkan data existing.

## Memigrasikan knowledge graph lama

Pastikan Neo4j lama dan Neo4j Docker dapat diakses pada port berbeda. Contoh: lama di `7687`, Docker
baru dijalankan dengan `NEO4J_BOLT_PORT=7688`. Script migrasi hanya menyalin `Modul`, `Bab`, `SubBab`,
`Konsep`, `Materi` beserta relasi KG; akun, enrollment, soal, jawaban, dan ujian lama sengaja tidak ikut.

```powershell
$env:SOURCE_NEO4J_PASSWORD = "password-neo4j-lama"
$env:TARGET_NEO4J_PASSWORD = "password-neo4j-docker"
python scripts/migrate_kg_to_docker.py `
  --source-uri bolt://localhost:7687 `
  --source-database matrikulasi `
  --target-uri bolt://localhost:7688 `
  --target-database neo4j
```

Script bersifat idempotent (`MERGE`), sehingga aman dijalankan ulang. Setelah jumlah node/relasi
terverifikasi, ubah backend nanti ke `NEO4J_URI=bolt://localhost:7688` dan `NEO4J_DATABASE=neo4j`.

### Migrasi lewat file untuk laptop berbeda

Di komputer yang masih memiliki Neo4j lama, ekspor snapshot:

```powershell
python scripts/export_kg_snapshot.py --output kg_snapshot.json
```

Script ekspor otomatis membaca `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, dan `NEO4J_DATABASE`
dari `backend/.env`. Argumen CLI hanya dipakai untuk override URI, user, atau nama database.

Salin `kg_snapshot.json` ke laptop baru. Setelah Neo4j Docker aktif, impor snapshot:

```powershell
python scripts/import_kg_snapshot.py --database neo4j --input kg_snapshot.json
```

Script impor otomatis membaca `NEO4J_PASSWORD` dan `NEO4J_BOLT_PORT` dari `.env.docker` di folder
`backend`.

File snapshot tidak berisi akun, password, enrollment, soal, ujian, jawaban, atau nilai. Karena impor
memakai `MERGE`, file yang sama aman diimpor ulang.
