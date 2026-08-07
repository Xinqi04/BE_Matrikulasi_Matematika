// Dummy user buat login test lewat FE, TANPA lewat API/hashing -- langsung tulis ke Neo4j.
// Cocok dipakai selama app/auth.py masih dalam mode DEBUG (password_hash = plaintext, lihat
// komentar di hash_password()/verify_password()). Kalau nanti balik pakai bcrypt, akun-akun
// ini harus dibuat ulang lewat API (POST /dosen/mahasiswa atau /dosen/dosen), bukan lewat script ini.
//
// Cara pakai di Neo4j Browser:
//   1. Pastikan konek ke database yang benar (default konfigurasi: "matrikulasi") -> jalankan
//      `:use matrikulasi` dulu kalau browser masih di database "neo4j" default.
//   2. Paste seluruh isi file ini, jalankan (Neo4j Browser otomatis pisah per statement `;`).
//   3. Idempotent -- aman dijalankan ulang, id & dibuat_pada gak berubah kalau user udah ada.

CREATE CONSTRAINT user_id IF NOT EXISTS FOR (u:User) REQUIRE u.id IS UNIQUE;
CREATE CONSTRAINT user_email IF NOT EXISTS FOR (u:User) REQUIRE u.email IS UNIQUE;

// --- Dosen dummy ---
// login: dosen@kampus.ac.id / dosen123
MERGE (d:User {email: "dosen@kampus.ac.id"})
ON CREATE SET
  d.id = randomUUID(),
  d.dibuat_pada = toString(datetime())
SET
  d.nama = "Dr. Budi Santoso",
  d.password_hash = "dosen123",
  d.role = "dosen",
  d.aktif = true
REMOVE d.nim;

// --- Mahasiswa dummy ---
// login: mahasiswa@kampus.ac.id / 123
MERGE (m:User {email: "mahasiswa@kampus.ac.id"})
ON CREATE SET
  m.id = randomUUID(),
  m.dibuat_pada = toString(datetime())
SET
  m.nama = "RAF",
  m.password_hash = "123",
  m.role = "mahasiswa",
  m.nim = "2024001",
  m.aktif = true;
