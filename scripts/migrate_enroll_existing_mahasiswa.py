"""Backward-compat migration buat fitur assign mahasiswa ke Modul: enroll semua mahasiswa yang
SUDAH ADA ke semua Modul yang SUDAH ADA (termasuk mahasiswa `aktif=false` -- itu gate login,
bukan enrollment), supaya progress yang udah ada gak hilang aksesnya begitu dashboard mahasiswa
mulai difilter per assignment. Mahasiswa baru yang dibuat SETELAH migrasi ini mulai dari nol
assignment sampai di-assign manual oleh dosen -- itu memang tujuan fiturnya. Jalankan sekali dari
folder `backend/`:

    python scripts/migrate_enroll_existing_mahasiswa.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.neo4j_client import neo4j_session  # noqa: E402
from app.services import enrollment_repo, kg_queries, user_repo  # noqa: E402


def main() -> None:
    with neo4j_session() as session:
        mahasiswa_list = user_repo.list_users(session, user_repo.ROLE_MAHASISWA)
        modul_ids = [m["id"] for m in kg_queries.list_modul(session)]

        if not modul_ids:
            print("Belum ada Modul sama sekali -- tidak ada yang di-enroll.")
            return

        for mhs in mahasiswa_list:
            enrollment_repo.set_modul_mahasiswa(session, mhs["id"], modul_ids)
            print(f"{mhs['nama']} <{mhs['email']}> -> di-enroll ke {len(modul_ids)} modul.")

        print(f"Selesai: {len(mahasiswa_list)} mahasiswa di-enroll ke semua {len(modul_ids)} modul yang ada.")


if __name__ == "__main__":
    main()
