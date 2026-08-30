from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field

from app.auth import hash_password, require_role
from app.neo4j_client import neo4j_session
from app.schemas import ModulMahasiswaOut, SetAktifRequest, SetModulMahasiswaRequest, UserCreatedResponse, UserOut
from app.services import enrollment_repo, kg_queries, postgres_user_repo

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_role("admin"))])


class CreateUserRequest(BaseModel):
    nama: str = Field(min_length=2, max_length=160)
    nim: str = Field(min_length=2, max_length=64)
    role: Literal["admin", "dosen", "mahasiswa"]
    password: str | None = Field(default=None, min_length=6)


class UpdateUserRequest(BaseModel):
    nama: str = Field(min_length=2, max_length=160)
    nim: str = Field(min_length=2, max_length=64)
    aktif: bool
    password_baru: str | None = Field(default=None, min_length=6)


@router.get("/users", response_model=list[UserOut])
def users(role: Literal["admin", "dosen", "mahasiswa"] | None = Query(default=None)):
    return postgres_user_repo.list_users(role)


@router.post("/users", response_model=UserCreatedResponse, status_code=201)
def create_user(body: CreateUserRequest):
    password = body.password or postgres_user_repo.generate_temp_password()
    try:
        user = postgres_user_repo.create_user(body.nama, body.nim, hash_password(password), body.role)
    except UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="NIM sudah terdaftar") from exc
    return {**user, "id": str(user["id"]), "password_awal": password}


@router.put("/users/{user_id}/active", response_model=UserOut)
def update_active(user_id: str, body: SetAktifRequest):
    user = postgres_user_repo.set_active(user_id, body.aktif)
    if not user:
        raise HTTPException(status_code=404, detail="Akun tidak ditemukan")
    return user


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: str, body: UpdateUserRequest):
    password_hash = hash_password(body.password_baru) if body.password_baru else None
    try:
        user = postgres_user_repo.update_user(
            user_id, body.nama, body.nim, body.aktif, password_hash,
        )
    except UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="NIM / ID sudah digunakan akun lain") from exc
    if not user:
        raise HTTPException(status_code=404, detail="Akun tidak ditemukan")
    return user


def _get_mahasiswa(user_id: str) -> dict:
    user = postgres_user_repo.get_by_id(user_id)
    if not user or user["role"] != "mahasiswa":
        raise HTTPException(status_code=404, detail="Mahasiswa tidak ditemukan")
    return user


@router.get("/users/{user_id}/modules", response_model=ModulMahasiswaOut)
def get_user_modules(user_id: str):
    _get_mahasiswa(user_id)
    return ModulMahasiswaOut(modul_ids=enrollment_repo.list_modul_ids_mahasiswa(user_id))


@router.put("/users/{user_id}/modules")
def set_user_modules(user_id: str, body: SetModulMahasiswaRequest):
    _get_mahasiswa(user_id)
    with neo4j_session() as session:
        valid_ids = {modul["id"] for modul in kg_queries.list_modul(session)}
    invalid = sorted(set(body.modul_ids) - valid_ids)
    if invalid:
        raise HTTPException(status_code=400, detail=f"Modul tidak ditemukan: {', '.join(invalid)}")
    enrollment_repo.set_modul_mahasiswa(user_id, body.modul_ids)
    return {"detail": "Enrollment mahasiswa diperbarui"}


@router.get("/dashboard")
def dashboard():
    users = postgres_user_repo.list_users()
    return {
        "jumlah_admin": sum(u["role"] == "admin" for u in users),
        "jumlah_dosen": sum(u["role"] == "dosen" for u in users),
        "jumlah_mahasiswa": sum(u["role"] == "mahasiswa" for u in users),
        "jumlah_aktif": sum(u["aktif"] for u in users),
    }
