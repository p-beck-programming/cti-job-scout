"""Load the tracked-company list and runtime settings."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .models import Company

DEFAULT_COMPANIES_PATH = Path("config/companies.yaml")


class Settings(BaseModel):
    score_threshold: int = Field(default=60, ge=0, le=100)
    dashboard_url: str = ""
    dry_run: bool = False  # True: run everything except sending the email

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            score_threshold=int(os.environ.get("SCORE_THRESHOLD", "60")),
            dashboard_url=os.environ.get("DASHBOARD_URL", ""),
            dry_run=os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes"),
        )


def load_companies(path: Path = DEFAULT_COMPANIES_PATH) -> list[Company]:
    data = yaml.safe_load(Path(path).read_text())
    companies = [Company.model_validate(entry) for entry in data.get("companies", [])]
    if not companies:
        raise ValueError(f"No companies defined in {path}")
    return companies
