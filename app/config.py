from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str
    gemini_model: str = "gemini-3.1-flash-lite-preview"

    youtube_api_key: str

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str
    neo4j_database: str = "matrikulasi"

    default_modul_id: str = "modul_matrikulasi_matematika_dasar"
    default_nama_domain: str = "Matematika Dasar"

    max_chars_per_chunk: int = 5100
    maks_konsep_per_chunk: int = 5

    upload_dir: str = "uploads"

    jwt_secret_key: str
    jwt_expire_minutes: int = 60 * 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
