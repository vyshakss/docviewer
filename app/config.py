from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    files_root: Path
    db_path: Path
    cache_dir: Path
    session_ttl_seconds: int = 604800
    pending_login_ttl_seconds: int = 300
    max_upload_bytes: int = 2_147_483_648
    login_lockout_threshold: int = 5
    login_lockout_window_seconds: int = 900
    cookie_secure: bool = True

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
