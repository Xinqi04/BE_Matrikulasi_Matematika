from fastapi import APIRouter, Depends, HTTPException

from app.auth import create_access_token, get_current_user, hash_password, verify_password
from app.config import Settings, get_settings
from app.schemas import ChangePasswordRequest, LoginRequest, LoginResponse, MeResponse
from app.services import postgres_user_repo

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, settings: Settings = Depends(get_settings)):
    user = postgres_user_repo.get_by_nim(body.nim)

    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="NIM atau password salah")
    if not user.get("aktif", True):
        raise HTTPException(status_code=401, detail="Akun dinonaktifkan")

    token = create_access_token(str(user["id"]), user["role"], settings)
    return LoginResponse(access_token=token, role=user["role"], nama=user["nama"])


@router.get("/me", response_model=MeResponse)
def me(user: dict = Depends(get_current_user)):
    return MeResponse(id=str(user["id"]), nama=user["nama"], role=user["role"], nim=user["nim"])


@router.put("/me/password")
def change_password(body: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    if not verify_password(body.password_lama, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Password lama salah")

    postgres_user_repo.set_password_hash(user["id"], hash_password(body.password_baru))

    return {"detail": "Password berhasil diganti"}
