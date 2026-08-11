"""
Application configuration loaded from environment variables / .env file.
All settings have sensible defaults so the app runs locally without a .env.
"""
from functools import lru_cache
from typing import List

from pydantic import Field, model_validator
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
    # Comma-separated allowed CORS origins. Use "*" for dev, explicit domains for prod.
    cors_origins: str = Field(default="*")

    # ── Scheduler ────────────────────────────────────────────────────────────
    ingestion_interval_minutes: int = Field(default=5)

    # ── Tickers to watch ─────────────────────────────────────────────────────
    default_tickers: str = Field(default="PLTR,AAPL,TSLA,NVDA,MSFT")

    @property
    def ticker_list(self) -> List[str]:
        return [t.strip().upper() for t in self.default_tickers.split(",") if t.strip()]

    # ── Auth / JWT ────────────────────────────────────────────────────────────
    jwt_secret_key: str = Field(
        default="change-me-in-production",
        description="Secret key for signing JWTs — set a strong random value in production",
    )
    jwt_algorithm: str = Field(default="HS256")
    jwt_expire_hours: int = Field(default=24)

    # ── External API keys (all optional — services degrade gracefully if absent) ─
    finnhub_api_key: str = Field(default="", description="Finnhub.io API key for real news sentiment")
    fred_api_key: str = Field(default="", description="FRED API key for macro data")
    anthropic_api_key: str = Field(default="", description="Anthropic API key for AI analyst (Claude)")

    # ── IBKR / Automated Trading ──────────────────────────────────────────────
    # IB Gateway or TWS must be running on the configured host:port with API enabled.
    # Port 7497 = paper trading (default), 7496 = live trading.
    # CIRO NOTE: API-based automated trading is only permitted for US-listed securities.
    ibkr_host: str = Field(default="127.0.0.1")
    ibkr_port: int = Field(default=7497)          # 7497=paper, 7496=live
    ibkr_client_id: int = Field(default=1)
    ibkr_account_id: str = Field(default="")     # optional; leave empty for default account
    auto_trade_enabled: bool = Field(default=False, description="Global kill-switch for automated trading")
    auto_trade_live_allowed: bool = Field(default=False, description="Allow live (non-paper) trading")

    # ── Feature flags ─────────────────────────────────────────────────────────
    enable_ml_model: bool = Field(default=False)
    enable_backtesting: bool = Field(default=False)
    enable_ai_analyst: bool = Field(default=False, description="Use Claude AI analyst instead of rule-based signal")
    # Claude model for AI analyst. Opus 4.6 scores 23pts higher on Anthropic's
    # Real-World Finance benchmark; Sonnet 4.6 is ~5x cheaper per token.
    analyst_model: str = Field(default="claude-opus-4-6", description="Claude model for AI analyst")
    # Extended thinking lets Claude reason through conflicting signals before answering.
    # Adds ~3-8s per analysis but produces better calibrated signals.
    analyst_extended_thinking: bool = Field(default=True, description="Enable Claude extended thinking for AI analyst")
    # Analysis caching — Claude is only re-called when one of these triggers fires:
    #   1. Last analysis is older than analyst_cache_minutes
    #   2. Price has moved >= analyst_price_change_pct since last analysis
    #   3. Composite score has shifted >= analyst_score_change_threshold
    #   4. VIX is >= analyst_vix_spike_threshold (fear spike → re-evaluate everything)
    analyst_cache_minutes: int = Field(default=60, description="Minutes before Claude re-analyzes a ticker unconditionally")
    analyst_price_change_pct: float = Field(default=0.03, description="Price move threshold (fraction) that triggers re-analysis")
    analyst_score_change_threshold: float = Field(default=0.12, description="Composite score shift that triggers re-analysis")
    analyst_vix_spike_threshold: float = Field(default=30.0, description="VIX level that forces re-analysis of all tickers")

    # ── Scoring weights (6 base weights must sum to 1.0) ──────────────────────
    weight_technical:    float = Field(default=0.25)
    weight_fundamental:  float = Field(default=0.15)
    weight_sentiment:    float = Field(default=0.20)
    weight_macro:        float = Field(default=0.15)
    weight_volatility:   float = Field(default=0.10)
    weight_catalyst:     float = Field(default=0.15)
    # Alternative data weight: additive modifier applied on top of the 6-weight
    # base score, so it does NOT participate in the sum-to-1.0 constraint.
    # score = base_score + weight_alt * (alt_score - 0.5)
    # A value of 0.10 means alt data can shift the composite by ±0.05.
    weight_alternative_data: float = Field(default=0.10)

    @model_validator(mode="after")
    def validate_weights_sum(self) -> "Settings":
        total = (
            self.weight_technical
            + self.weight_fundamental
            + self.weight_sentiment
            + self.weight_macro
            + self.weight_volatility
            + self.weight_catalyst
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Scoring weights must sum to 1.0, got {total:.6f}. "
                "Check weight_technical, weight_fundamental, weight_sentiment, "
                "weight_macro, weight_volatility, weight_catalyst in .env"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton Settings instance."""
    return Settings()
