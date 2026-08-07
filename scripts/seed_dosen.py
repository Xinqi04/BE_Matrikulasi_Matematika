"""Bootstrap akun dosen pertama (sekali jalan). Jalankan dari folder `backend/`:

    python scripts/seed_dosen.py --nama "Nama Dosen" --email dosen@kampus.ac.id

Dosen berikutnya bisa dibuat lewat endpoint POST /dosen/dosen setelah login pakai akun ini.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import hash_password  # noqa: E402
from app.neo4j_client import neo4j_session  # noqa: E402
from app.services import user_repo  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Buat akun dosen pertama (bootstrap).")
    parser.add_argument("--nama", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", help="Kalau tidak diisi, password acak akan digenerate.")
    args = parser.parse_args()

    password = args.password or user_repo.generate_temp_password()

    with neo4j_session() as session:
        if user_repo.get_user_by_email(session, args.email) is not None:
            print(f"Email {args.email} sudah terdaftar -- dibatalkan.")
            return
        user = user_repo.create_user(
            session, nama=args.nama, email=args.email, password_hash=hash_password(password),
            role=user_repo.ROLE_DOSEN,
        )

    print(f"Akun dosen dibuat: {user['nama']} <{user['email']}>")
    print(f"Password: {password}")
    print("Simpan/salurkan password ini secara aman -- tidak akan ditampilkan lagi.")


if __name__ == "__main__":
    main()
