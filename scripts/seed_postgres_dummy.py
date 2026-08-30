"""Buat akun dummy PostgreSQL secara idempotent untuk development."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import hash_password
from app.services import postgres_user_repo

USERS = (
    ("Admin Matrikulasi", "ADM001", "admin", "admin123"),
    ("Dosen Penilai", "DSN001", "dosen", "dosen123"),
    ("Mahasiswa Dummy", "MHS001", "mahasiswa", "mahasiswa123"),
)

for nama, nim, role, password in USERS:
    if postgres_user_repo.get_by_nim(nim):
        print(f"Lewati {nim}: sudah ada")
        continue
    postgres_user_repo.create_user(nama, nim, hash_password(password), role)
    print(f"Dibuat {role}: {nim} / {password}")
