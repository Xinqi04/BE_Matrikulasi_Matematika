"""Query read-only ke Neo4j untuk endpoint GET (lihat isi KG)."""

from __future__ import annotations

from neo4j import Session


def dosen_dashboard_counts(session: Session) -> dict:
    def _tx(tx):
        result = tx.run(
            """
            OPTIONAL MATCH (mhs:User {role: 'mahasiswa', aktif: true})
            WITH count(DISTINCT mhs) AS jumlah_mahasiswa_aktif
            OPTIONAL MATCH (m:Modul)
            WITH jumlah_mahasiswa_aktif, count(DISTINCT m) AS jumlah_modul
            OPTIONAL MATCH (s:Soal)
            WITH jumlah_mahasiswa_aktif, jumlah_modul, count(DISTINCT s) AS jumlah_soal
            OPTIONAL MATCH ()-[r:MENJAWAB {status: 'menunggu_penilaian'}]->()
            RETURN jumlah_mahasiswa_aktif, jumlah_modul, jumlah_soal,
                   count(r) AS jumlah_jawaban_menunggu_penilaian
            """
        )
        return dict(result.single())

    return session.execute_read(_tx)


def list_konsep(session: Session) -> list[dict]:
    def _tx(tx):
        result = tx.run(
            """
            MATCH (k:Konsep)
            OPTIONAL MATCH (m:Materi)-[:MEMBAHAS_KONSEP]->(k)
            RETURN k.nama AS nama, count(DISTINCT m) AS jumlah_video
            ORDER BY k.nama
            """
        )
        return [{"nama": r["nama"], "jumlah_video": r["jumlah_video"]} for r in result]

    return session.execute_read(_tx)


_MODUL_TREE_TAIL = """
    OPTIONAL MATCH (m)-[:HAS_BAB]->(bab:Bab)
    OPTIONAL MATCH (bab)-[:HAS_SUBBAB]->(sub:SubBab)
    OPTIONAL MATCH (bab)-[:HAS_KONSEP]->(k1:Konsep)
    OPTIONAL MATCH (sub)-[:HAS_KONSEP]->(k2:Konsep)
    RETURN
        m.id AS modul_id, m.nama_domain AS nama_domain,
        bab.id AS bab_id, bab.nomor AS bab_nomor, bab.nama AS bab_nama,
        sub.id AS sub_id, sub.nomor AS sub_nomor, sub.nama AS sub_nama,
        count(DISTINCT k1) AS jumlah_konsep_bab, count(DISTINCT k2) AS jumlah_konsep_sub,
        collect(DISTINCT k1.nama) AS konsep_bab, collect(DISTINCT k2.nama) AS konsep_sub
    ORDER BY modul_id, toInteger(bab.nomor), toInteger(split(sub.nomor, '.')[1])
"""


def _map_modul_rows(result) -> list[dict]:
    modul_map: dict[str, dict] = {}
    bab_map: dict[str, dict] = {}

    for r in result:
        modul_id = r["modul_id"]
        if modul_id is None:
            continue
        modul = modul_map.setdefault(
            modul_id, {"id": modul_id, "nama_domain": r["nama_domain"], "bab": []}
        )

        bab_id = r["bab_id"]
        if bab_id is None:
            continue
        bab = bab_map.get(bab_id)
        if bab is None:
            bab = {
                "id": bab_id, "nomor": r["bab_nomor"], "nama": r["bab_nama"],
                "jumlah_konsep": r["jumlah_konsep_bab"], "konsep": sorted(r["konsep_bab"]), "subbab": [],
            }
            bab_map[bab_id] = bab
            modul["bab"].append(bab)

        if r["sub_id"] is not None and not any(s["id"] == r["sub_id"] for s in bab["subbab"]):
            bab["subbab"].append({
                "id": r["sub_id"], "nomor": r["sub_nomor"], "nama": r["sub_nama"],
                "jumlah_konsep": r["jumlah_konsep_sub"], "konsep": sorted(r["konsep_sub"]),
            })

    return list(modul_map.values())


def list_modul(session: Session) -> list[dict]:
    def _tx(tx):
        result = tx.run("MATCH (m:Modul)" + _MODUL_TREE_TAIL)
        return _map_modul_rows(result)

    return session.execute_read(_tx)


def list_modul_untuk_mahasiswa(session: Session, mahasiswa_id: str) -> list[dict]:
    def _tx(tx):
        result = tx.run(
            "MATCH (u:User {id: $mahasiswa_id})-[:MENGAMBIL]->(m:Modul)" + _MODUL_TREE_TAIL,
            mahasiswa_id=mahasiswa_id,
        )
        return _map_modul_rows(result)

    return session.execute_read(_tx)


def list_video(session: Session) -> list[dict]:
    def _tx(tx):
        result = tx.run(
            """
            MATCH (m:Materi)
            OPTIONAL MATCH (m)-[:MEMBAHAS_KONSEP]->(k:Konsep)
            RETURN m.id AS video_id, m.judul AS judul, m.kontributor AS channel,
                   m.sumber AS link, m.status_validasi AS status_validasi,
                   collect(k.nama) AS konsep
            ORDER BY m.judul
            """
        )
        return [dict(r) for r in result]

    return session.execute_read(_tx)
