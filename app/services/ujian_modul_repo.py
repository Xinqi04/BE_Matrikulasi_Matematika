"""Penyimpanan pretest/posttest modul yang terpisah dari ujian per bab."""

from datetime import datetime, timezone
from uuid import uuid4

from neo4j import Session


def status_ujian(session: Session, mahasiswa_id: str) -> list[dict]:
    def _tx(tx):
        rows = tx.run(
            """
            MATCH (u:User {id: $user_id})-[:MENGAMBIL]->(m:Modul)
            OPTIONAL MATCH (u)-[:MEMILIKI_UJIAN]->(a:UjianModul)-[:UNTUK_MODUL]->(m)
            RETURN m.id AS modul_id, a.jenis AS jenis, a.status AS status
            """,
            user_id=mahasiswa_id,
        )
        result = {}
        for row in rows:
            item = result.setdefault(row["modul_id"], {"modul_id": row["modul_id"], "pretest": "belum", "posttest": "belum"})
            if row["jenis"] in ("pretest", "posttest"):
                # Data lama bisa memiliki lebih dari satu attempt. Jangan biarkan
                # attempt "dikerjakan" menimpa attempt yang sudah dikirim/dinilai.
                prioritas = {"belum": 0, "dikerjakan": 1, "menunggu_penilaian": 2, "dinilai": 3}
                jenis = row["jenis"]
                if prioritas.get(row["status"], 0) >= prioritas.get(item[jenis], 0):
                    item[jenis] = row["status"]
        return list(result.values())
    return session.execute_read(_tx)


def pretest_sudah_dikirim_untuk_bab(session: Session, mahasiswa_id: str, bab_id: str) -> bool:
    def _tx(tx):
        return tx.run(
            """
            MATCH (u:User {id:$user_id})-[:MEMILIKI_UJIAN]->(a:UjianModul {jenis:'pretest'})-[:UNTUK_MODUL]->(m:Modul)-[:HAS_BAB]->(:Bab {id:$bab_id})
            WHERE a.status IN ['menunggu_penilaian', 'dinilai']
            RETURN count(a) > 0 AS selesai
            """,
            user_id=mahasiswa_id, bab_id=bab_id,
        ).single()["selesai"]
    return session.execute_read(_tx)


def pretest_sudah_dikirim_untuk_modul(session: Session, mahasiswa_id: str, modul_id: str) -> bool:
    """Sumber status pretest untuk dashboard dan kunci bab."""
    def _tx(tx):
        return tx.run(
            """
            MATCH (u:User {id:$user_id})-[:MEMILIKI_UJIAN]->
                  (a:UjianModul {jenis:'pretest'})-[:UNTUK_MODUL]->(:Modul {id:$modul_id})
            WHERE a.status IN ['menunggu_penilaian', 'dinilai']
            RETURN count(a) > 0 AS selesai
            """,
            user_id=mahasiswa_id, modul_id=modul_id,
        ).single()["selesai"]
    return session.execute_read(_tx)


def mulai_ujian(session: Session, mahasiswa_id: str, modul_id: str, jenis: str) -> dict | None:
    attempt_id = str(uuid4())

    def _tx(tx):
        enrolled = tx.run(
            "MATCH (:User {id:$user_id})-[:MENGAMBIL]->(:Modul {id:$modul_id}) RETURN 1 AS ok",
            user_id=mahasiswa_id, modul_id=modul_id,
        ).single()
        if not enrolled:
            return None

        existing = tx.run(
            """
            MATCH (:User {id:$user_id})-[:MEMILIKI_UJIAN]->(a:UjianModul {jenis:$jenis})-[:UNTUK_MODUL]->(:Modul {id:$modul_id})
            RETURN a.id AS id, a.status AS status
            """,
            user_id=mahasiswa_id, modul_id=modul_id, jenis=jenis,
        ).single()
        if existing:
            attempt = dict(existing)
        else:
            tx.run(
                """
                MATCH (u:User {id:$user_id}), (m:Modul {id:$modul_id})
                CREATE (a:UjianModul {id:$id, jenis:$jenis, status:'dikerjakan', mulai_pada:$waktu})
                CREATE (u)-[:MEMILIKI_UJIAN]->(a)-[:UNTUK_MODUL]->(m)
                """,
                user_id=mahasiswa_id, modul_id=modul_id, id=attempt_id, jenis=jenis,
                waktu=datetime.now(timezone.utc).isoformat(),
            )
            if jenis == "pretest":
                tx.run(
                    """
                    MATCH (a:UjianModul {id:$id})-[:UNTUK_MODUL]->(m:Modul)-[:HAS_BAB]->(:Bab)-[:HAS_SOAL]->(s:Soal)
                    WHERE coalesce(s.untuk_ujian, false) = true
                    MERGE (a)-[:MENGGUNAKAN_SOAL]->(s)
                    """,
                    id=attempt_id,
                )
            else:
                tx.run(
                    """
                    MATCH (u:User {id:$user_id})-[:MEMILIKI_UJIAN]->(pre:UjianModul {jenis:'pretest'})-[:MENGGUNAKAN_SOAL]->(s:Soal)
                    MATCH (u)-[:MEMILIKI_UJIAN]->(post:UjianModul {id:$id})
                    MERGE (post)-[:MENGGUNAKAN_SOAL]->(s)
                    """,
                    user_id=mahasiswa_id, id=attempt_id,
                )
            attempt = {"id": attempt_id, "status": "dikerjakan"}

        questions = tx.run(
            """
            MATCH (a:UjianModul {id:$attempt_id})-[:MENGGUNAKAN_SOAL]->(s:Soal)
            MATCH (b:Bab)-[:HAS_SOAL]->(s)
            OPTIONAL MATCH (s)-[:MENGUJI]->(k:Konsep)
            RETURN s.id AS id, b.id AS bab_id, b.nomor AS bab_nomor,
                   s.teks_soal AS teks_soal, s.tipe AS tipe, s.dibuat_pada AS dibuat_pada,
                   collect(k.nama) AS konsep
            ORDER BY toInteger(bab_nomor), dibuat_pada, id
            """,
            attempt_id=attempt["id"],
        )
        return {"attempt_id": attempt["id"], "status": attempt["status"], "jenis": jenis, "soal": [dict(q) for q in questions]}
    return session.execute_write(_tx)


def submit_ujian(session: Session, mahasiswa_id: str, modul_id: str, attempt_id: str, jawaban: list[dict]) -> bool:
    def _tx(tx):
        attempt = tx.run(
            """
            MATCH (u:User {id:$user_id})-[:MEMILIKI_UJIAN]->(a:UjianModul {id:$attempt_id, status:'dikerjakan'})-[:UNTUK_MODUL]->(:Modul {id:$modul_id})
            RETURN a
            """,
            user_id=mahasiswa_id, attempt_id=attempt_id, modul_id=modul_id,
        ).single()
        if not attempt:
            return False
        for item in jawaban:
            tx.run(
                """
                MATCH (a:UjianModul {id:$attempt_id})-[:UNTUK_MODUL]->(m:Modul {id:$modul_id})
                MATCH (m)-[:HAS_BAB]->(:Bab)-[:HAS_SOAL]->(s:Soal {id:$soal_id})
                WHERE coalesce(s.untuk_ujian, false) = true
                CREATE (j:JawabanUjian {id:$id, teks_jawaban:$teks, status:'menunggu_penilaian', dijawab_pada:$waktu})
                CREATE (a)-[:HAS_JAWABAN]->(j)-[:UNTUK_SOAL]->(s)
                """,
                attempt_id=attempt_id, modul_id=modul_id, soal_id=item["soal_id"], id=str(uuid4()), teks=item["teks_jawaban"],
                waktu=datetime.now(timezone.utc).isoformat(),
            )
        tx.run("MATCH (a:UjianModul {id:$id}) SET a.status='menunggu_penilaian', a.dikirim_pada=$waktu", id=attempt_id, waktu=datetime.now(timezone.utc).isoformat())
        return True
    return session.execute_write(_tx)


def list_jawaban_untuk_dosen(session: Session, status: str | None = None) -> list[dict]:
    def _tx(tx):
        rows = tx.run(
            """
            MATCH (u:User)-[:MEMILIKI_UJIAN]->(a:UjianModul)-[:UNTUK_MODUL]->(m:Modul)
            MATCH (a)-[:HAS_JAWABAN]->(j:JawabanUjian)-[:UNTUK_SOAL]->(s:Soal)
            WHERE $status IS NULL OR j.status = $status
            RETURN j.id AS id, a.id AS attempt_id, a.jenis AS jenis, m.id AS modul_id,
                   m.nama_domain AS modul_nama, u.id AS mahasiswa_id, u.nama AS mahasiswa_nama,
                   s.id AS soal_id, s.teks_soal AS teks_soal, s.tipe AS tipe,
                   s.jawaban_referensi AS jawaban_referensi, j.teks_jawaban AS teks_jawaban,
                   j.nilai AS nilai, j.status AS status
            ORDER BY j.dijawab_pada
            """,
            status=status,
        )
        return [dict(row) for row in rows]
    return session.execute_read(_tx)


def beri_nilai_batch(session: Session, items: list[dict]) -> list[dict]:
    def _tx(tx):
        hasil = []
        for item in items:
            row = tx.run(
                """
                MATCH (a:UjianModul)-[:HAS_JAWABAN]->(j:JawabanUjian {id:$id})
                SET j.nilai=$nilai, j.status='dinilai', j.dinilai_pada=$waktu
                WITH a, j
                OPTIONAL MATCH (a)-[:HAS_JAWABAN]->(pending:JawabanUjian)
                WHERE pending.status <> 'dinilai'
                WITH a, j, count(pending) AS tersisa
                SET a.status = CASE WHEN tersisa = 0 THEN 'dinilai' ELSE a.status END
                RETURN j.id AS id, j.nilai AS nilai, j.status AS status
                """,
                id=item["jawaban_id"], nilai=item["nilai"], waktu=datetime.now(timezone.utc).isoformat(),
            ).single()
            if row:
                hasil.append(dict(row))
        return hasil
    return session.execute_write(_tx)
