# Menjalankan backend dengan Docker

Docker hanya dipakai untuk backend, PostgreSQL, dan Neo4j. Jalankan perintah berikut dari folder
`backend`:

```powershell
Copy-Item .env.docker.example .env.docker # cukup sekali jika file belum ada
# Isi password di .env.docker dan API key/JWT secret di .env
docker compose --env-file .env.docker up -d --build
```

Layanan backend:

- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- PostgreSQL host: localhost:5433
- Neo4j Browser: http://localhost:7474

Status dan log:

```powershell
docker compose --env-file .env.docker ps
docker compose --env-file .env.docker logs -f backend
```

Buat akun dummy development:

```powershell
docker compose --env-file .env.docker exec backend python scripts/seed_postgres_dummy.py
```

Menghentikan backend tanpa menghapus data:

```powershell
docker compose --env-file .env.docker down
```

Jangan tambahkan `-v` kecuali memang ingin menghapus volume database dan upload.

## Menjalankan frontend

Frontend tidak memakai Docker. Jalankan dari folder `frontend` pada terminal terpisah:

```powershell
npm install
npm run dev
```

Frontend tersedia di http://localhost:5173 dan otomatis menggunakan backend di
`http://localhost:8000`.
