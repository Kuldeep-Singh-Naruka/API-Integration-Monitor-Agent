from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables / .env file.
    All secrets and configuration live here — never hardcoded elsewhere.
    """

    DATABASE_URL: str
    APP_NAME: str = "API Integration Monitor"
    DEBUG: bool = False

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")


# Single shared instance — import this everywhere
settings = Settings()
