"""
Application configuration loaded from environment variables / .env file.
All settings have sensible defaults so the app runs locally without a .env.
"""
from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── MongoDB ──────────────────────────────────────────────────────────────
    mongodb_url: str = Field(
        default="mongodb://localhost:27017",
        description="Full MongoDB connection URI",
    )
    mongodb_db_name: str = Field(default="trading_agent")

    # ── App ──────────────────────────────────────────────────────────────────
    app_env: str = Field(default="development")
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    log_level: str = Field(default="INFO")

    # ── Scheduler ────────────────────────────────────────────────────────────
    ingestion_interval_minutes: int = Field(default=5)

    # ── Tickers to watch ─────────────────────────────────────────────────────
    default_tickers: str = Field(default="PLTR,AAPL,TSLA,NVDA,MSFT")

    @property
    def ticker_list(self) -> List[str]:
        return [t.strip().upper() for t in self.default_tickers.split(",") if t.strip()]

    # ── Feature flags ─────────────────────────────────────────────────────────
    enable_ml_model: bool = Field(default=False)
    enable_backtesting: bool = Field(default=False)

    # ── Scoring weights (must sum to 1.0) ─────────────────────────────────────
    weight_technical: float = Field(default=0.4)
    weight_sentiment: float = Field(default=0.3)
    weight_volatility: float = Field(default=0.3)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton Settings instance."""
    return Settings()
