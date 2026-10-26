from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    MAX_BOT_TOKEN: str = ""
    MAX_API_BASE: str = "https://platform-api2.max.ru"
    MAX_BOT_MODE: str = "polling"
    MAX_WEBHOOK_URL: str = ""
    MAX_WEBHOOK_SECRET: str = ""
    MAX_BOT_USERNAME: str = "t158_hakaton_max_bot"
    MAX_CA_BUNDLE: str = ""
    MAX_TLS_INSECURE: bool = False

    DATABASE_URL: str = "sqlite:///./data/classgo.db"
    # Файлы от пользователей (билеты): на том же томе, что и база.
    FILES_DIR: str = "./data/files"
    MINIAPP_BASE_URL: str = "http://localhost:8080"
    PUBLIC_BASE_URL: str = "http://localhost:8080"
    MAX_VALIDATE_INIT_DATA: bool = False
    INIT_DATA_MAX_AGE_SECONDS: int = 86400
    # Токен служебных ручек (/api/v1/admin/*). Пусто — в строгом режиме они закрыты.
    ADMIN_TOKEN: str = ""
    # Секрет коротких ссылок на скачивание документов; пусто — выводится из токена бота.
    DOWNLOAD_SECRET: str = ""
    AUTO_SEED: bool = True
    POLL_TIMEOUT: int = 30
    REMINDER_INTERVAL_SECONDS: int = 300
    LOG_LEVEL: str = "INFO"

    @property
    def bot_enabled(self) -> bool:
        return bool(self.MAX_BOT_TOKEN) and self.MAX_BOT_MODE in ("polling", "webhook")


@lru_cache
def get_settings() -> Settings:
    return Settings()
