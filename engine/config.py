"""
Configuration loader for Pixel HR Office.

Priority (highest → lowest):
  1. Environment variables
  2. config.local.toml  (git-ignored, for personal overrides)
  3. config.toml        (checked in, project defaults)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib          # stdlib, Python ≥ 3.11
except ImportError:
    try:
        import tomli as tomllib   # type: ignore[no-reuse-def]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

_PROJECT_ROOT = Path(__file__).parent.parent


def _load_toml(path: Path) -> dict:
    if tomllib is None or not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _merge(result[k], v)
        else:
            result[k] = v
    return result


def _raw() -> dict:
    base    = _load_toml(_PROJECT_ROOT / "config.toml")
    local   = _load_toml(_PROJECT_ROOT / "config.local.toml")
    return _merge(base, local)


@dataclass
class ApiConfig:
    anthropic_api_key: str = ""
    daily_budget_usd:  float = 1.0


@dataclass
class AppConfig:
    default_context: str   = "HR_Office"
    demo_interval:   float = 5.0
    log_max_lines:   int   = 500


@dataclass
class NightWatchConfig:
    run_at:           str = ""
    interval_seconds: int = 3600


@dataclass
class DbConfig:
    sqlite_path: str = "pixel_hr.db"
    chroma_path: str = "./chroma_db"


@dataclass
class LimitsConfig:
    max_tokens_default: int = 1024
    max_tokens_short:   int = 160
    max_tokens_medium:  int = 256
    max_tokens_long:    int = 350


@dataclass
class Config:
    api:         ApiConfig        = field(default_factory=ApiConfig)
    app:         AppConfig        = field(default_factory=AppConfig)
    night_watch: NightWatchConfig = field(default_factory=NightWatchConfig)
    db:          DbConfig         = field(default_factory=DbConfig)
    limits:      LimitsConfig     = field(default_factory=LimitsConfig)


def load() -> Config:
    raw = _raw()

    api_raw = raw.get("api", {})
    app_raw = raw.get("app", {})
    nw_raw  = raw.get("night_watch", {})
    db_raw  = raw.get("db", {})
    lim_raw = raw.get("limits", {})

    # Env vars override file values
    api_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or api_raw.get("anthropic_api_key", "")
    )
    budget = float(
        os.environ.get("DAILY_BUDGET_USD")
        or api_raw.get("daily_budget_usd", 1.0)
    )

    return Config(
        api=ApiConfig(
            anthropic_api_key=api_key,
            daily_budget_usd=budget,
        ),
        app=AppConfig(
            default_context=os.environ.get("DEFAULT_CONTEXT") or app_raw.get("default_context", "HR_Office"),
            demo_interval=float(app_raw.get("demo_interval", 5.0)),
            log_max_lines=int(app_raw.get("log_max_lines", 500)),
        ),
        night_watch=NightWatchConfig(
            run_at=os.environ.get("NIGHT_WATCH_TIME") or nw_raw.get("run_at", ""),
            interval_seconds=int(nw_raw.get("interval_seconds", 3600)),
        ),
        db=DbConfig(
            sqlite_path=os.environ.get("SQLITE_PATH") or db_raw.get("sqlite_path", "pixel_hr.db"),
            chroma_path=os.environ.get("CHROMA_PATH") or db_raw.get("chroma_path", "./chroma_db"),
        ),
        limits=LimitsConfig(
            max_tokens_default=int(lim_raw.get("max_tokens_default", 1024)),
            max_tokens_short=int(lim_raw.get("max_tokens_short", 160)),
            max_tokens_medium=int(lim_raw.get("max_tokens_medium", 256)),
            max_tokens_long=int(lim_raw.get("max_tokens_long", 350)),
        ),
    )


# Module-level singleton — import and use `cfg` directly
cfg: Config = load()
