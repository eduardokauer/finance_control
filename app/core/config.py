from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "finance-control-backend"
    environment: str = "dev"
    api_token: str = "changeme"
    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/finance_control"

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')


settings = Settings()
