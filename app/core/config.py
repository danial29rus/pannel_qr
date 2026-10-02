from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Payments Control Panel"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://panel:panel@localhost:5432/panel"
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:15173"
    enforce_auth: bool = False
    admin_token: str = ""
    operator_token: str = ""
    viewer_token: str = ""
    panel_admin_username: str = "admin"
    panel_admin_password_hash: str = ""
    panel_session_secret: str = ""
    panel_session_ttl_minutes: int = 720
    smtp_enabled: bool = False
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_from: str = "support@panel.localhost"
    # Comma-separated local/owned domains. Never add public third-party domains.
    smtp_allowed_recipient_domains: str = "clients.localhost,gmail.localhost,yandex.localhost,outlook.localhost,mail.localhost,company.localhost"
    reconciliation_poll_seconds: int = 10
    run_reconciliation_worker: bool = True

    @property
    def smtp_recipient_domain_set(self) -> set[str]:
        return {item.strip().lower() for item in self.smtp_allowed_recipient_domains.split(",") if item.strip()}

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
