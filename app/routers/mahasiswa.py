from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_role
from app.neo4j_client import neo4j_session
from app.schemas import (
    DiagnosaOut,
    MahasiswaDashboardOut,
    MulaiUjianModulRequest,
    ProgressBabOut,
    SoalMahasiswaOut,
    SubmitJawabanRequest,
    SubmitUjianModulRequest,
)
from app.services import diagnosis, enrollment_repo, jawaban_repo, kg_queries, soal_pipeline, ujian_modul_repo

router = APIRouter(prefix="/mahasiswa", tags=["mahasiswa"], dependencies=[Depends(require_role("mahasiswa"))])


@router.get("/dashboard", response_model=MahasiswaDashboardOut)
def dashboard(user: dict = Depends(require_role("mahasiswa"))):
    with neo4j_session() as session:
        modul_ids = enrollment_repo.list_modul_ids_mahasiswa(user["id"])
        modul_list = kg_queries.list_modul_untuk_mahasiswa(session, modul_ids)

        progress = []
        for modul in modul_list:
            pretest_selesai = ujian_modul_repo.pretest_sudah_dikirim_untuk_modul(
                session, user["id"], modul["id"]
            )
            for bab in modul["bab"]:
                status, nilai_bab = diagnosis.status_bab(session, user["id"], bab["id"])
                locked = (not pretest_selesai) or diagnosis.bab_terkunci(
                    session, user["id"], bab["id"]
                )
                progress.append(ProgressBabOut(
                    bab_id=bab["id"], bab_nama=bab["nama"], nomor=bab["nomor"],
                    nilai_bab=nilai_bab, status=status, locked=locked,
                ))
        ujian_modul = ujian_modul_repo.status_ujian(session, user["id"])

    return MahasiswaDashboardOut(modul=modul_list, progress=progress, ujian_modul=ujian_modul)


_PESAN_TERKUNCI = "Bab ini masih terkunci. Selesaikan Bab sebelumnya dengan nilai lulus (>= 70) terlebih dahulu."
_PESAN_BELUM_TERDAFTAR = "Anda tidak terdaftar pada modul yang memuat Bab ini."


@router.get("/bab/{bab_id}/soal", response_model=list[SoalMahasiswaOut])
def get_soal_bab(bab_id: str, user: dict = Depends(require_role("mahasiswa"))):
    with neo4j_session() as session:
        if not enrollment_repo.mahasiswa_terdaftar_bab(session, user["id"], bab_id):
            raise HTTPException(status_code=403, detail=_PESAN_BELUM_TERDAFTAR)
        if not ujian_modul_repo.pretest_sudah_dikirim_untuk_bab(session, user["id"], bab_id):
            raise HTTPException(status_code=403, detail="Selesaikan pretest modul terlebih dahulu.")
        if diagnosis.status_bab(session, user["id"], bab_id)[0] == "menunggu_penilaian":
            raise HTTPException(status_code=409, detail="Jawaban bab ini sedang menunggu penilaian dosen.")
        if diagnosis.bab_terkunci(session, user["id"], bab_id):
            raise HTTPException(status_code=403, detail=_PESAN_TERKUNCI)
        soal_list = soal_pipeline.list_soal(session, bab_id)
        jawaban_list = jawaban_repo.list_jawaban(session, bab_id=bab_id, mahasiswa_id=user["id"])

        diagnosa = diagnosis.diagnosa_bab(session, user["id"], bab_id)

    # Percobaan ulang (remedial/pengayaan) cuma perlu soal yang menguji konsep yang masih lemah --
    # bukan seluruh soal Bab lagi. Kalau gara-gara filter ini soal-nya jadi kosong (mis. konsep_fokus
    # gak match ke soal manapun), fallback ke daftar penuh biar mahasiswa gak buntu.
    if diagnosa["status"] in ("remedial", "pengayaan") and diagnosa["konsep_fokus"]:
        konsep_fokus = set(diagnosa["konsep_fokus"])
        difilter = [s for s in soal_list if konsep_fokus & set(s["konsep"])]
        if difilter:
            soal_list = difilter

    soal_id_terjawab = {j["soal_id"] for j in jawaban_list}
    return [
        SoalMahasiswaOut(
            id=s["id"], bab_id=s["bab_id"], teks_soal=s["teks_soal"], tipe=s["tipe"],
            konsep=s["konsep"], sudah_dijawab=s["id"] in soal_id_terjawab,
        )
        for s in soal_list
    ]


@router.post("/bab/{bab_id}/jawaban")
def submit_jawaban(bab_id: str, body: SubmitJawabanRequest, user: dict = Depends(require_role("mahasiswa"))):
    with neo4j_session() as session:
        if not enrollment_repo.mahasiswa_terdaftar_bab(session, user["id"], bab_id):
            raise HTTPException(status_code=403, detail=_PESAN_BELUM_TERDAFTAR)
        if not ujian_modul_repo.pretest_sudah_dikirim_untuk_bab(session, user["id"], bab_id):
            raise HTTPException(status_code=403, detail="Selesaikan pretest modul terlebih dahulu.")
        if diagnosis.status_bab(session, user["id"], bab_id)[0] == "menunggu_penilaian":
            raise HTTPException(status_code=409, detail="Jawaban bab ini sedang menunggu penilaian dosen.")
        if diagnosis.bab_terkunci(session, user["id"], bab_id):
            raise HTTPException(status_code=403, detail=_PESAN_TERKUNCI)
        hasil = jawaban_repo.submit_jawaban(
            session, mahasiswa_id=user["id"], bab_id=bab_id,
            daftar_jawaban=[item.model_dump() for item in body.jawaban],
        )
    return {"detail": f"{len(hasil)} jawaban tersimpan, menunggu penilaian dosen.", "jawaban": hasil}


@router.get("/bab/{bab_id}/hasil", response_model=DiagnosaOut)
def hasil_bab(bab_id: str, user: dict = Depends(require_role("mahasiswa"))):
    with neo4j_session() as session:
        return diagnosis.diagnosa_bab(session, user["id"], bab_id)


@router.post("/modul/{modul_id}/ujian/mulai")
def mulai_ujian_modul(modul_id: str, body: MulaiUjianModulRequest, user: dict = Depends(require_role("mahasiswa"))):
    if body.jenis not in ("pretest", "posttest"):
        raise HTTPException(status_code=400, detail="Jenis ujian harus pretest atau posttest")
    modul_ids = enrollment_repo.list_modul_ids_mahasiswa(user["id"])
    if modul_id not in modul_ids:
        raise HTTPException(status_code=403, detail="Anda tidak terdaftar pada modul ini")
    with neo4j_session() as session:
        if ujian_modul_repo.jumlah_soal_ujian_modul(session, modul_id) == 0:
            raise HTTPException(
                status_code=409,
                detail=f"Belum ada soal untuk {body.jenis} modul ini. Silakan hubungi dosen.",
            )
        if body.jenis == "posttest":
            modul_list = kg_queries.list_modul_untuk_mahasiswa(session, modul_ids)
            target = next((m for m in modul_list if m["id"] == modul_id), None)
            if target is None:
                raise HTTPException(status_code=403, detail="Anda tidak terdaftar pada modul ini")
            if any(diagnosis.status_bab(session, user["id"], bab["id"])[0] not in ("lanjut", "pengayaan") for bab in target["bab"]):
                raise HTTPException(status_code=403, detail="Selesaikan seluruh bab sebelum memulai posttest")
        hasil = ujian_modul_repo.mulai_ujian(session, user["id"], modul_id, body.jenis)
    if hasil is None:
        raise HTTPException(status_code=404, detail="Modul tidak ditemukan")
    if hasil["status"] in ("menunggu_penilaian", "dinilai"):
        raise HTTPException(status_code=409, detail=f"{body.jenis.capitalize()} sudah pernah dikirim")
    if not hasil["soal"]:
        raise HTTPException(status_code=409, detail=f"Belum ada soal untuk {body.jenis} modul ini. Silakan hubungi dosen.")
    return hasil


@router.post("/modul/{modul_id}/ujian/jawaban")
def submit_ujian_modul(modul_id: str, body: SubmitUjianModulRequest, user: dict = Depends(require_role("mahasiswa"))):
    with neo4j_session() as session:
        berhasil = ujian_modul_repo.submit_ujian(
            session, user["id"], modul_id, body.attempt_id,
            [item.model_dump() for item in body.jawaban],
        )
    if not berhasil:
        raise HTTPException(status_code=409, detail="Ujian sudah dikirim atau sesi tidak ditemukan")
    return {"detail": "Jawaban berhasil dikirim dan menunggu penilaian dosen."}
