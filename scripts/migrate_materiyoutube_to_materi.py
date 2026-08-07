"""Migrasi node `:MateriYoutube` (skema lama, khusus YouTube) jadi `:Materi` generik (skema baru,
bisa nampung sumber materi lain lewat properti `tipe`). Relabel IN PLACE lewat `SET`/`REMOVE`
supaya relationship `HAS_KONSEP` otomatis ikut tanpa perlu re-link manual. Jalankan sekali dari
folder `backend/`:

    python scripts/migrate_materiyoutube_to_materi.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.neo4j_client import neo4j_session  # noqa: E402


def main() -> None:
    with neo4j_session() as session:
        def _tx(tx):
            result = tx.run(
                """
                MATCH (v:MateriYoutube)
                SET v:Materi,
                    v.id = v.video_id, v.kontributor = v.channel, v.sumber = v.link, v.tipe = 'youtube'
                REMOVE v.video_id, v.channel, v.link, v:MateriYoutube
                RETURN count(v) AS jumlah
                """
            )
            return result.single()["jumlah"]

        jumlah = session.execute_write(_tx)
        print(f"{jumlah} node :MateriYoutube direlabel jadi :Materi.")

        def _ganti_constraint(tx):
            tx.run("DROP CONSTRAINT video_id IF EXISTS")
            tx.run("CREATE CONSTRAINT materi_id IF NOT EXISTS FOR (m:Materi) REQUIRE m.id IS UNIQUE")

        session.execute_write(_ganti_constraint)
        print("Constraint video_id dihapus, constraint materi_id dibuat.")


if __name__ == "__main__":
    main()
