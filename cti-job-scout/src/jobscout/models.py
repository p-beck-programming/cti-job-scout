"""Shared data models for the job-scouting pipeline.

Everything that crosses a module boundary is a pydantic model so that
malformed data (from an ATS API or from the scoring model) fails loudly at the
boundary instead of deep inside the digest builder.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Company(BaseModel):
    """One entry from config/companies.yaml."""

    name: str
    ats: Literal["greenhouse", "lever", "ashby"]
    # Greenhouse board token, Lever company slug, or Ashby job-board name,
    # e.g. "anthropic". Ashby names can contain dots ("flashpoint.io").
    token: str


class Location(BaseModel):
    """Normalized location, parsed from the ATS's free-text location field.

    `raw` is always preserved so nothing is lost if parsing guesses wrong.
    """

    raw: str = ""
    city: Optional[str] = None
    state: Optional[str] = None  # Two-letter US state code, e.g. "TN".
    metro: Optional[str] = None  # Human-friendly metro label, e.g. "Nashville Metro".
    country: Optional[str] = None
    is_remote: bool = False

    def display(self) -> str:
        if self.is_remote and not self.city:
            return "Remote" + (f" ({self.country})" if self.country else "")
        parts = [p for p in (self.city, self.state) if p]
        label = ", ".join(parts) if parts else (self.raw or "Location not listed")
        if self.is_remote:
            label += " · Remote-eligible"
        return label


class JobPosting(BaseModel):
    """A single open posting as fetched from an ATS."""

    # Stable unique ID across runs: "{ats}:{token}:{ats_job_id}".
    uid: str
    company: str
    ats: Literal["greenhouse", "lever", "ashby"]
    title: str
    url: str
    description: str = ""
    locations: list[Location] = Field(default_factory=list)
    posted_at: Optional[datetime] = None

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str) -> str:
        return v.strip()


class Score(BaseModel):
    """The scoring model's structured verdict on one posting. Mirrors the JSON schema
    demanded by the scoring prompt in prompts.py — keep the two in sync."""

    score: int = Field(ge=0, le=100)
    rationale: str = Field(min_length=1, max_length=500)
    matched_keywords: list[str] = Field(default_factory=list)


class Synopsis(BaseModel):
    """The model's aggregated read of what employers want, regenerated weekly.
    Mirrors the JSON schema demanded by SYNOPSIS_SYSTEM_PROMPT in prompts.py —
    keep the two in sync."""

    overview: str = Field(min_length=1)
    top_skills: list[str] = Field(default_factory=list)
    tools_and_technologies: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    experience: list[str] = Field(default_factory=list)
    emerging_trends: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)


class ScoredJob(BaseModel):
    """A posting plus its score; the unit stored in state and rendered
    into both the email digest and the dashboard JSON."""

    posting: JobPosting
    score: Score
    scored_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dashboard_row(self) -> dict:
        """Flatten into the shape docs/index.html expects in jobs.json."""
        locs = self.posting.locations or [Location(raw="", is_remote=False)]
        return {
            "uid": self.posting.uid,
            "company": self.posting.company,
            "title": self.posting.title,
            "url": self.posting.url,
            "score": self.score.score,
            "rationale": self.score.rationale,
            "keywords": self.score.matched_keywords,
            "scored_at": self.scored_at.isoformat(),
            "locations": [
                {
                    "raw": l.raw,
                    "city": l.city,
                    "state": l.state,
                    "metro": l.metro,
                    "country": l.country,
                    "remote": l.is_remote,
                    "display": l.display(),
                }
                for l in locs
            ],
        }
