from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", ".env.docker"), env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str
    gemini_model: str = "gemini-3.1-flash-lite-preview"

    # Engine rekonstruksi-KG (parsing struktur PDF + ekstraksi konsep) -- lihat
    # app/services/rekonstruksi_kg/.
    gemini_structure_model: str = "gemini-3.5-flash-lite"
    gemini_extraction_model: str = "gemini-3.1-flash-lite"
    llm_request_delay_seconds: int = 5
    llm_max_retries: int = 3
    max_unit_tokens: int = 30000

    youtube_api_key: str

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str
    neo4j_database: str = "matrikulasi"

    postgres_db: str = "matrikulasi"
    postgres_user: str = "matrikulasi"
    postgres_password: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    default_modul_id: str = "modul_matrikulasi_matematika_dasar"
    default_nama_domain: str = "Matematika Dasar"

    upload_dir: str = "uploads"
    cors_origins: list[str] = ["*"]
    max_pdf_upload_mb: int = Field(default=20, ge=1, le=200)

    jwt_secret_key: str
    jwt_expire_minutes: int = 60 * 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
