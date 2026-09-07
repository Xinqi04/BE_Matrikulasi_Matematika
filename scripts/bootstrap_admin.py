"""Create the first production administrator without demo credentials."""
import argparse
import getpass
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.auth import hash_password
from app.postgres_client import postgres_connection


def bootstrap(nim, name, password):
    if not nim.strip() or not name.strip() or len(password) < 16:
        raise ValueError("NIM/nama wajib diisi; password minimal 16 karakter")
    with postgres_connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(74201952)")
        if conn.execute("SELECT 1 FROM users WHERE role='admin' AND aktif=true").fetchone():
            return False
        conn.execute("INSERT INTO users(nim,nama,password_hash,role) VALUES (%s,%s,%s,'admin')", (nim.strip(), name.strip(), hash_password(password)))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nim", required=True)
    parser.add_argument("--nama", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Password admin (minimal 16 karakter): ")
    if password != getpass.getpass("Ulangi password: "):
        raise SystemExit("Password berbeda")
    print("Admin dibuat" if bootstrap(args.nim, args.nama, password) else "Admin aktif sudah ada; tidak ada perubahan")


if __name__ == "__main__":
    main()
