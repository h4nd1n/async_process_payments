from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(default="postgresql+asyncpg://app:app@localhost:5432/payments")
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost:5672/")
    api_key: str = Field(default="dev-secret-api-key-change-me")

    outbox_poll_interval_sec: float = Field(default=0.75)

    webhook_max_attempts: int = Field(default=3)
    webhook_backoff_base_sec: float = Field(default=1.0)

    consumer_max_process_retries: int = Field(default=3)


def get_settings() -> Settings:
    return Settings()
