from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Look for .env in the infra directory (two levels up from this file)
_env_file = Path(__file__).parent.parent.parent.parent / "infra" / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_env_file), env_file_encoding="utf-8")

    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "marketing"
    POSTGRES_USER: str = "marketing"
    POSTGRES_PASSWORD: str = "marketing"
    DATABASE_URL: str = "postgresql+psycopg://marketing:marketing@localhost:5432/marketing"

    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"

    USE_DRY_RUN_EXECUTION: bool = True

    META_ACCESS_TOKEN: str = ""
    META_APP_SECRET: str = ""
    META_AD_ACCOUNT_ID: str = ""  # format: "act_123456789"
    META_PAGE_ID: str = ""  # Facebook Page ID for ad creative creation


settings = Settings()
