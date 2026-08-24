from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.auth import hash_password, require_role
from app.config import Settings, get_settings
from app.job_manager import create_job, run_job
from app.neo4j_client import neo4j_session
from app.schemas import (
    BeriNilaiBatchRequest,
    BeriNilaiRequest,
    BuatDosenRequest,
    BuatMahasiswaRequest,
    BuatSoalRequest,
    ConfirmSoalDraftRequest,
    DosenDashboardOut,
    GenerateSoalRequest,
    JawabanOut,
    JobAccepted,
    ModulMahasiswaOut,
    SetAktifRequest,
    SetModulMahasiswaRequest,
    SoalOut,
    SuggestKonsepRequest,
    SuggestKonsepResponse,
    UpdateSoalRequest,
    UserCreatedResponse,
    UserOut,
)
from app.services import enrollment_repo, jawaban_repo, kg_queries, soal_pipeline, user_repo
from app.services.soal_generator import generate_soal_draft

router = APIRouter(prefix="/dosen", tags=["dosen"], dependencies=[Depends(require_role("dosen"))])


# --- Manajemen mahasiswa & dosen ---

@router.post("/mahasiswa", response_model=UserCreatedResponse, status_code=201)
def buat_mahasiswa(body: BuatMahasiswaRequest):
    password_awal = user_repo.generate_temp_password()
    with neo4j_session() as session:
        if user_repo.get_user_by_email(session, body.email) is not None:
            raise HTTPException(status_code=409, detail="Email sudah terdaftar")
        user = user_repo.create_user(
            session, nama=body.nama, email=body.email, password_hash=hash_password(password_awal),
            role=user_repo.ROLE_MAHASISWA, nim=body.nim,
        )
    return UserCreatedResponse(id=user["id"], nama=user["nama"], email=user["email"], role=user["role"], password_awal=password_awal)


@router.get("/mahasiswa", response_model=list[UserOut])
def list_mahasiswa():
    with neo4j_session() as session:
        return user_repo.list_users(session, user_repo.ROLE_MAHASISWA)


@router.put("/mahasiswa/{user_id}", response_model=dict)
def set_aktif_mahasiswa(user_id: str, body: SetAktifRequest):
    with neo4j_session() as session:
        user_repo.set_aktif(session, user_id, body.aktif)
    return {"detail": "Status akun diperbarui"}


def _pastikan_mahasiswa(session, user_id: str) -> dict:
    target = user_repo.get_user_by_id(session, user_id)
    if target is None or target["role"] != user_repo.ROLE_MAHASISWA:
        raise HTTPException(status_code=404, detail="Mahasiswa tidak ditemukan")
    return target


@router.get("/mahasiswa/{user_id}/modul", response_model=ModulMahasiswaOut)
def get_modul_mahasiswa(user_id: str):
    with neo4j_session() as session:
        _pastikan_mahasiswa(session, user_id)
        return ModulMahasiswaOut(modul_ids=enrollment_repo.list_modul_ids_mahasiswa(session, user_id))


@router.put("/mahasiswa/{user_id}/modul", response_model=dict)
def set_modul_mahasiswa(user_id: str, body: SetModulMahasiswaRequest):
    with neo4j_session() as session:
        _pastikan_mahasiswa(session, user_id)
        enrollment_repo.set_modul_mahasiswa(session, user_id, body.modul_ids)
    return {"detail": "Modul mahasiswa diperbarui"}


@router.post("/dosen", response_model=UserCreatedResponse, status_code=201)
def buat_dosen(body: BuatDosenRequest):
    password_awal = user_repo.generate_temp_password()
    with neo4j_session() as session:
        if user_repo.get_user_by_email(session, body.email) is not None:
            raise HTTPException(status_code=409, detail="Email sudah terdaftar")
        user = user_repo.create_user(
            session, nama=body.nama, email=body.email, password_hash=hash_password(password_awal),
            role=user_repo.ROLE_DOSEN,
        )
    return UserCreatedResponse(id=user["id"], nama=user["nama"], email=user["email"], role=user["role"], password_awal=password_awal)


# --- Soal ---

@router.post("/soal/suggest-konsep", response_model=SuggestKonsepResponse)
def suggest_konsep(body: SuggestKonsepRequest, settings: Settings = Depends(get_settings)):
    with neo4j_session() as session:
        kandidat = soal_pipeline.konsep_kandidat(session, body.bab_id)
    saran = soal_pipeline.sarankan_konsep_llm(settings, body.teks_soal, kandidat)
    return SuggestKonsepResponse(konsep_saran=saran)


@router.post("/soal", response_model=SoalOut, status_code=201)
def buat_soal(body: BuatSoalRequest, user: dict = Depends(require_role("dosen"))):
    with neo4j_session() as session:
        soal = soal_pipeline.buat_soal(
            session, bab_id=body.bab_id, teks_soal=body.teks_soal, tipe=body.tipe,
            konsep_list=body.konsep, dibuat_oleh=user["id"],
            jawaban_referensi=body.jawaban_referensi, tingkat_kesulitan=body.tingkat_kesulitan,
        )
    return soal


@router.post("/soal/generate", response_model=JobAccepted, status_code=202)
def generate_soal(
    body: GenerateSoalRequest, background_tasks: BackgroundTasks, settings: Settings = Depends(get_settings),
):
    """Mulai generate draf soal (via LLM) di background -- BELUM ditulis ke Knowledge Graph. Hasilnya
    ada di `job.result.items` (poll lewat `GET /jobs/{job_id}`) buat direview/diedit dosen, baru
    disimpan lewat `POST /soal/generate/confirm`."""

    job = create_job("soal_generation")

    def _task():
        run_job(
            job.id,
            lambda log_fn: generate_soal_draft(
                body.bab_id, body.jumlah, body.tipe, body.tingkat_kesulitan, settings, log_fn,
            ),
        )

    background_tasks.add_task(_task)
    return JobAccepted(job_id=job.id, status=job.status)


@router.post("/soal/generate/confirm", response_model=list[SoalOut], status_code=201)
def confirm_generated_soal(body: ConfirmSoalDraftRequest, user: dict = Depends(require_role("dosen"))):
    """Simpan draf soal (yang sudah ditinjau/diedit dosen di frontend) ke Knowledge Graph, lewat
    `soal_pipeline.buat_soal()` yang sama dengan endpoint insert manual."""

    with neo4j_session() as session:
        return [
            soal_pipeline.buat_soal(
                session, bab_id=body.bab_id, teks_soal=item.teks_soal, tipe=item.tipe,
                konsep_list=item.konsep, dibuat_oleh=user["id"],
                jawaban_referensi=item.jawaban_referensi, tingkat_kesulitan=item.tingkat_kesulitan,
            )
            for item in body.items
        ]


@router.get("/soal", response_model=list[SoalOut])
def get_soal_bab(bab_id: str):
    with neo4j_session() as session:
        return soal_pipeline.list_soal(session, bab_id)


@router.put("/soal/{soal_id}", response_model=SoalOut)
def update_soal(soal_id: str, body: UpdateSoalRequest):
    with neo4j_session() as session:
        soal = soal_pipeline.update_soal(
            session, soal_id=soal_id, teks_soal=body.teks_soal, tipe=body.tipe,
            konsep_list=body.konsep, jawaban_referensi=body.jawaban_referensi,
            tingkat_kesulitan=body.tingkat_kesulitan,
        )
    if soal is None:
        raise HTTPException(status_code=404, detail="Soal tidak ditemukan")
    return soal


@router.delete("/soal/{soal_id}")
def hapus_soal(soal_id: str):
    with neo4j_session() as session:
        soal_pipeline.hapus_soal(session, soal_id)
    return {"detail": "Soal dihapus"}


# --- Penilaian ---

@router.get("/penilaian", response_model=list[JawabanOut])
def get_penilaian(bab_id: Optional[str] = None, status: Optional[str] = None):
    with neo4j_session() as session:
        return jawaban_repo.list_jawaban(session, bab_id=bab_id, status=status)


@router.put("/penilaian/{jawaban_id}", response_model=dict)
def beri_nilai(jawaban_id: str, body: BeriNilaiRequest):
    with neo4j_session() as session:
        hasil = jawaban_repo.beri_nilai(session, jawaban_id, body.nilai)
    if hasil is None:
        raise HTTPException(status_code=404, detail="Jawaban tidak ditemukan")
    return {"detail": "Nilai tersimpan", **hasil}


@router.post("/penilaian/batch", response_model=dict)
def beri_nilai_batch(body: BeriNilaiBatchRequest):
    if not body.nilai:
        raise HTTPException(status_code=400, detail="Daftar nilai kosong")
    with neo4j_session() as session:
        hasil = jawaban_repo.beri_nilai_batch(session, [item.model_dump() for item in body.nilai])
    return {"detail": f"{len(hasil)} dari {len(body.nilai)} nilai tersimpan", "jawaban": hasil}


# --- Dashboard ---

@router.get("/dashboard", response_model=DosenDashboardOut)
def dashboard():
    with neo4j_session() as session:
        return kg_queries.dosen_dashboard_counts(session)
