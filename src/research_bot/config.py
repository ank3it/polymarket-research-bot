"""Configuration loaded from environment / .env.

All money values are Gordon micro-units: 1_000_000 units = $1.00 USD.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- Gordon ----
    gordon_platform_url: str = "https://api.withgordon.ai"
    gordon_mcp_url: str = "https://api.withgordon.ai/mcp"
    gordon_agent_api_key: str = Field(default="", description="gak_pub_...")
    gordon_agent_api_secret: str = Field(default="", description="gak_sec_...")

    # ---- Polymarket (public read) ----
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"
    polymarket_clob_url: str = "https://clob.polymarket.com"

    # ---- Storage ----
    database_path: str = "research_bot.db"

    # ---- Catalog operations (confirm slugs via `research-bot services`) ----
    # Slugs from the enabled Gordon catalog. Confirm exact operation_ids with
    # `research-bot services "<query>"` (gordon_find_service) before a full run.
    triage_search_op: str = "exa.search.web"      # search · Exa (verified)
    # Tavily exists in the catalog but is not probe-passed yet, so Gordon blocks it
    # (SERVICE_NOT_PROBE_PASSED). Default deep research to Exa until a deeper
    # provider is verified.
    deep_research_op: str = "exa.search.web"
    # NOTE: the enabled catalog currently has NO general chat-completions service,
    # so decompose/estimate degrade to a placeholder probability. Point this at a
    # real inference op once one is enabled (or wire a direct LLM).
    inference_op: str = "blockrun.chat.completions"
    # Model passed to the inference op (depends on the catalog operation's schema)
    inference_model: str = "claude-3-5-sonnet-latest"

    # ---- Budget / routing (micro-units) ----
    triage_max_units: int = 10_000        # $0.01
    deep_max_units: int = 10_000          # $0.01 (keep ≤ daily budget or calls are skipped)
    inference_max_units: int = 50_000     # $0.05
    daily_budget_units: int = 5_000_000   # $5.00
    estimator_samples: int = 5

    # ---- Scan filters ----
    min_liquidity: float = 5_000.0
    max_days_to_resolution: int = 120
    min_days_to_resolution: int = 2

    # ---- Signal thresholds ----
    edge_threshold: float = 0.07
    confidence_threshold: float = 0.6

    @property
    def gordon_auth_header(self) -> str:
        """Bearer {key}:{secret} per Gordon docs."""
        return f"Bearer {self.gordon_agent_api_key}:{self.gordon_agent_api_secret}"

    @property
    def gordon_configured(self) -> bool:
        return bool(self.gordon_agent_api_key and self.gordon_agent_api_secret)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def units_to_usd(units: int) -> float:
    return units / 1_000_000


def usd_to_units(usd: float) -> int:
    return int(round(usd * 1_000_000))
