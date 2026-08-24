from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.job_manager import JobStatus


class JobAccepted(BaseModel):
    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    id: str
    type: str
    status: JobStatus
    log: list[str]
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class YoutubeClassifyRequest(BaseModel):
    link: str
    materi_query: Optional[str] = None


# --- PDF extraction preview/confirm ---

class KonsepDraft(BaseModel):
    nama: str
    deskripsi: str = ""


class PdfPreviewUnit(BaseModel):
    unit_id: str
    level: str
    label: str
    judul: str
    konsep: list[KonsepDraft]


class PdfConfirmUnitInput(BaseModel):
    unit_id: str
    konsep: list[KonsepDraft]


class PdfConfirmRequest(BaseModel):
    job_id: str
    unit: list[PdfConfirmUnitInput]


class PdfConfirmResponse(BaseModel):
    detail: str
    jumlah_konsep_total: int
    unit: list[PdfPreviewUnit]


class HapusModulOut(BaseModel):
    detail: str
    nama_domain: str
    jumlah_bab: int
    jumlah_subbab: int
    jumlah_soal: int
    jumlah_jawaban: int


# --- Youtube classification preview/confirm ---

class YoutubeConfirmRequest(BaseModel):
    job_id: str
    konsep: list[str]


class YoutubeConfirmResponse(BaseModel):
    detail: str
    video_id: str
    judul: str
    channel: Optional[str] = None
    link: str
    konsep_terklasifikasi: list[str]


class KonsepOut(BaseModel):
    nama: str
    jumlah_video: int = 0


class SubBabOut(BaseModel):
    id: str
    nomor: str
    nama: str
    jumlah_konsep: int
    konsep: list[str] = []


class BabOut(BaseModel):
    id: str
    nomor: str
    nama: str
    jumlah_konsep: int
    konsep: list[str] = []
    subbab: list[SubBabOut]


class ModulOut(BaseModel):
    id: str
    nama_domain: str
    bab: list[BabOut]


class VideoOut(BaseModel):
    video_id: str
    judul: str
    channel: Optional[str] = None
    link: str
    status_validasi: Optional[str] = None
    konsep: list[str]


class VideoUpdateRequest(BaseModel):
    judul: Optional[str] = None
    konsep: list[str]


class HapusVideoOut(BaseModel):
    detail: str
    video_id: str
    judul: str


# --- Auth ---

class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    nama: str


class MeResponse(BaseModel):
    id: str
    nama: str
    email: str
    role: str
    nim: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    password_lama: str
    password_baru: str


# --- Manajemen user (dosen) ---

class BuatMahasiswaRequest(BaseModel):
    nama: str
    email: str
    nim: Optional[str] = None


class BuatDosenRequest(BaseModel):
    nama: str
    email: str


class UserCreatedResponse(BaseModel):
    id: str
    nama: str
    email: str
    role: str
    password_awal: str


class UserOut(BaseModel):
    id: str
    nama: str
    email: str
    role: str
    nim: Optional[str] = None
    aktif: bool


class SetAktifRequest(BaseModel):
    aktif: bool


class SetModulMahasiswaRequest(BaseModel):
    modul_ids: list[str]


class ModulMahasiswaOut(BaseModel):
    modul_ids: list[str]


# --- Soal ---

class SuggestKonsepRequest(BaseModel):
    bab_id: str
    teks_soal: str


class SuggestKonsepResponse(BaseModel):
    konsep_saran: list[str]


class BuatSoalRequest(BaseModel):
    bab_id: str
    teks_soal: str
    tipe: str  # "isian_singkat" | "esai"
    konsep: list[str]
    jawaban_referensi: Optional[str] = None
    tingkat_kesulitan: Optional[str] = None


class UpdateSoalRequest(BaseModel):
    teks_soal: str
    tipe: str  # "isian_singkat" | "esai"
    konsep: list[str]
    jawaban_referensi: Optional[str] = None
    tingkat_kesulitan: Optional[str] = None


class SoalOut(BaseModel):
    id: str
    bab_id: str
    teks_soal: str
    tipe: str
    konsep: list[str]
    jawaban_referensi: Optional[str] = None
    tingkat_kesulitan: Optional[str] = None
    dibuat_oleh: Optional[str] = None
    dibuat_pada: Optional[str] = None


class GenerateSoalRequest(BaseModel):
    bab_id: str
    jumlah: int = Field(ge=1, le=20)
    tipe: Optional[str] = None  # None = campuran isian_singkat/esai
    tingkat_kesulitan: Optional[str] = None  # None = campuran mudah/sedang/sulit


class SoalDraftItem(BaseModel):
    teks_soal: str
    tipe: str
    tingkat_kesulitan: str
    konsep: list[str]
    jawaban_referensi: Optional[str] = None


class ConfirmSoalDraftRequest(BaseModel):
    bab_id: str
    items: list[SoalDraftItem]


class SoalMahasiswaOut(BaseModel):
    """Versi soal buat mahasiswa -- TANPA jawaban_referensi."""

    id: str
    bab_id: str
    teks_soal: str
    tipe: str
    konsep: list[str]
    sudah_dijawab: bool


# --- Jawaban / Penilaian ---

class JawabanItem(BaseModel):
    soal_id: str
    teks_jawaban: str


class SubmitJawabanRequest(BaseModel):
    jawaban: list[JawabanItem]


class JawabanOut(BaseModel):
    id: str
    bab_id: str
    mahasiswa_id: str
    mahasiswa_nama: str
    soal_id: str
    teks_soal: str
    tipe: str
    jawaban_referensi: Optional[str] = None
    teks_jawaban: str
    nilai: Optional[float] = None
    status: str
    dijawab_pada: Optional[str] = None
    dinilai_pada: Optional[str] = None


class BeriNilaiRequest(BaseModel):
    nilai: float


class NilaiItem(BaseModel):
    jawaban_id: str
    nilai: float


class BeriNilaiBatchRequest(BaseModel):
    nilai: list[NilaiItem]


# --- Diagnosis ---

class RekomendasiVideoOut(BaseModel):
    video_id: str
    judul: str
    link: str
    channel: Optional[str] = None
    thumbnail: Optional[str] = None
    jaccard: float
    konsep_cocok: list[str]


class DiagnosaOut(BaseModel):
    status: str
    nilai_bab: Optional[float] = None
    nilai_per_konsep: dict[str, float]
    konsep_fokus: list[str]
    rekomendasi_video: list[RekomendasiVideoOut]


# --- Dashboard ---

class DosenDashboardOut(BaseModel):
    jumlah_mahasiswa_aktif: int
    jumlah_modul: int
    jumlah_soal: int
    jumlah_jawaban_menunggu_penilaian: int


class ProgressBabOut(BaseModel):
    bab_id: str
    bab_nama: str
    nomor: str
    nilai_bab: Optional[float] = None
    status: Optional[str] = None
    locked: bool = False


class MahasiswaDashboardOut(BaseModel):
    modul: list[ModulOut]
    progress: list[ProgressBabOut]
