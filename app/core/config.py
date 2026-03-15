from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "finance-control-backend"
    environment: str = "dev"
    api_token: str = "changeme"
    admin_ui_password: str | None = None
    admin_ui_session_secret: str = "change-me-admin-session-secret"
    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/finance_control"
    port: int = 8000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
