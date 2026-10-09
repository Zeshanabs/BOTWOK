"""Application settings (pydantic-settings). Every env var in .env.example maps here."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["local", "production", "test"] = "local"
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:3000"
    public_media_base_url: str = ""
    signup_mode: Literal["open", "invite_only"] = "open"

    botwok_master_key: str = "change-me-32-bytes-base64"
    jwt_secret: str = "change-me-jwt-secret"
    access_token_minutes: int = 15
    refresh_token_days: int = 30

    database_url: str = "postgresql+asyncpg://botwok:botwok@localhost:5432/botwok"
    database_url_sync: str = "postgresql://botwok:botwok@localhost:5432/botwok"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "botwok"
    s3_secret_key: str = "botwok-secret"
    s3_region: str = "us-east-1"
    s3_bucket_media: str = "media"
    s3_bucket_documents: str = "documents"
    s3_bucket_reports: str = "reports"
    embedding_dims: int = 1536

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    xai_api_key: str = ""
    google_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    huggingface_api_key: str = ""
    pollinations_api_key: str = ""
    # Comma-separated model specs used when no routed provider has a key (key-less public endpoint). Empty disables.
    free_fallback_models: str = "pollinations/openai"
    ollama_base_url: str = "http://localhost:11434/v1"
    default_cheap_model: str = "anthropic/claude-haiku-4-5-20251001"
    default_balanced_model: str = "anthropic/claude-sonnet-5-5"
    default_powerful_model: str = "anthropic/claude-opus-5-5"
    default_embedding_model: str = "openai/text-embedding-3-small"

    tavily_api_key: str = ""
    brave_api_key: str = ""
    exa_api_key: str = ""
    searxng_base_url: str = "http://localhost:8080"

    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_graph_version: str = "v26.0"
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    x_client_id: str = ""
    x_client_secret: str = ""
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    pinterest_app_id: str = ""
    pinterest_app_secret: str = ""

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "botwok@localhost"

    # budgets & limits
    default_run_budget_usd: float = 1.5
    confirm_above_usd: float = 2.0
    max_parallel_tasks: int = 3

    cors_origins: list[str] = Field(default_factory=list)

    @property
    def is_local(self) -> bool:
        return self.app_env != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
