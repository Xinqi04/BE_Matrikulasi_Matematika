from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_role
from app.neo4j_client import neo4j_session
from app.schemas import (
    DiagnosaOut,
    MahasiswaDashboardOut,
    ProgressBabOut,
    SoalMahasiswaOut,
    SubmitJawabanRequest,
)
from app.services import diagnosis, enrollment_repo, jawaban_repo, kg_queries, soal_pipeline

router = APIRouter(prefix="/mahasiswa", tags=["mahasiswa"], dependencies=[Depends(require_role("mahasiswa"))])


@router.get("/dashboard", response_model=MahasiswaDashboardOut)
def dashboard(user: dict = Depends(require_role("mahasiswa"))):
    with neo4j_session() as session:
        modul_list = kg_queries.list_modul_untuk_mahasiswa(session, user["id"])

        progress = []
        for modul in modul_list:
            for bab in modul["bab"]:
                status, nilai_bab = diagnosis.status_bab(session, user["id"], bab["id"])
                locked = diagnosis.bab_terkunci(session, user["id"], bab["id"])
                progress.append(ProgressBabOut(
                    bab_id=bab["id"], bab_nama=bab["nama"], nomor=bab["nomor"],
                    nilai_bab=nilai_bab, status=status, locked=locked,
                ))

    return MahasiswaDashboardOut(modul=modul_list, progress=progress)


_PESAN_TERKUNCI = "Bab ini masih terkunci. Selesaikan Bab sebelumnya dengan nilai lulus (>= 70) terlebih dahulu."
_PESAN_BELUM_TERDAFTAR = "Anda tidak terdaftar pada modul yang memuat Bab ini."


@router.get("/bab/{bab_id}/soal", response_model=list[SoalMahasiswaOut])
def get_soal_bab(bab_id: str, user: dict = Depends(require_role("mahasiswa"))):
    with neo4j_session() as session:
        if not enrollment_repo.mahasiswa_terdaftar_bab(session, user["id"], bab_id):
            raise HTTPException(status_code=403, detail=_PESAN_BELUM_TERDAFTAR)
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
