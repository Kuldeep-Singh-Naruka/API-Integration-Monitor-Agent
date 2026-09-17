from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import Optional


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables / .env file.
    All secrets and configuration live here — never hardcoded elsewhere.
    """

    DATABASE_URL: str
    APP_NAME: str = "API Integration Monitor"
    DEBUG: bool = False
    TAVILY_API_KEY: str
    GROQ_API_KEY: str
    SCHEDULER_SECRET: str

    LANGSMITH_TRACING: bool = False
    LANGSMITH_API_KEY: Optional[str] = None
    LANGSMITH_PROJECT: str = "api-integration-monitor-agent"
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")


# Single shared instance — import this everywhere
settings = Settings()
