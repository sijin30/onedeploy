from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    WATCHDOG_INTERVAL_SECONDS: float = 10
    WATCHDOG_FAILED_CHECKS: int = 3
    WATCHDOG_MAX_RESTART_ATTEMPTS: int = 3
    WATCHDOG_MEMORY_PERCENT_THRESHOLD: float = 85

    model_config = SettingsConfigDict(
        env_file=".env"
    )


settings = Settings()