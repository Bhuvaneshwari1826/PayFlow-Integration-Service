from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Takaada Integration Service"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/takaada"
    DATABASE_URL_SYNC: str = "postgresql+psycopg2://postgres:postgres@localhost:5433/takaada"

    # External Accounting API
    EXTERNAL_API_BASE_URL: str = "https://mock-accounting-api.takaada.io"
    EXTERNAL_API_KEY: str = "mock-api-key-change-in-prod"
    EXTERNAL_API_TIMEOUT: int = 30

    # Sync scheduler (cron: every N minutes)
    SYNC_INTERVAL_MINUTES: int = 15

    # Pagination
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
