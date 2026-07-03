"""Score postings for relevance with the Claude API.

Design decisions:
- `anthropic` is imported lazily so unit tests for the parser don't need
  the SDK or an API key.
- parse_score_response() is a pure function, tested in isolation. It
  tolerates the two common failure modes of "JSON-only" prompts: markdown
  fences and stray prose around the object.
- Malformed output triggers a retry with an explicit corrective nudge;
  after MAX_ATTEMPTS the posting gets a score of 0 with an error rationale
  rather than crashing the run (it will still appear in logs).
- A posting that fails to score is NOT marked as seen, so the next run
  retries it automatically.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

from pydantic import ValidationError

from .models import JobPosting, Score
from .prompts import SCORING_SYSTEM_PROMPT

log = logging.getLogger(__name__)

# Update this string when Anthropic ships newer models; see README.
DEFAULT_MODEL = os.environ.get("JOBSCOUT_MODEL", "claude-sonnet-4-6")
MAX_ATTEMPTS = 3
RETRY_BASE_DELAY = 2.0  # seconds; doubles per attempt for 429/5xx backoff

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)


class ScoringError(Exception):
    """Raised when a posting cannot be scored after all retries."""


def parse_score_response(text: str) -> Score:
    """Extract and validate the JSON score object from a model response.

    Raises ValueError / ValidationError on malformed input so the caller
    can decide whether to retry.
    """
    cleaned = text.strip()
    # Strip markdown fences if the model added them despite instructions.
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.S).strip()
    if not cleaned.startswith("{"):
        match = _JSON_OBJECT_RE.search(cleaned)
        if not match:
            raise ValueError(f"No JSON object found in response: {text[:200]!r}")
        cleaned = match.group(0)
    data = json.loads(cleaned)
    return Score.model_validate(data)


def _build_user_message(posting: JobPosting) -> str:
    locs = "; ".join(l.display() for l in posting.locations) or "not listed"
    return (
        f"Company: {posting.company}\n"
        f"Title: {posting.title}\n"
        f"Locations: {locs}\n\n"
        f"Description:\n{posting.description or '(no description provided)'}"
    )


def score_posting(posting: JobPosting, client=None, model: str = DEFAULT_MODEL) -> Score:
    """Score one posting, retrying on malformed output and transient API errors."""
    import anthropic  # lazy: keeps parser tests dependency-free

    if client is None:
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    messages = [{"role": "user", "content": _build_user_message(posting)}]
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=400,
                system=SCORING_SYSTEM_PROMPT,
                messages=messages,
            )
            text = "".join(
                block.text for block in response.content if block.type == "text"
            )
            return parse_score_response(text)
        except (json.JSONDecodeError, ValueError, ValidationError) as exc:
            # Malformed output: append a corrective turn and retry.
            last_error = exc
            log.warning(
                "Malformed score for %s (attempt %d/%d): %s",
                posting.uid, attempt, MAX_ATTEMPTS, exc,
            )
            messages = messages + [
                {"role": "assistant", "content": text if "text" in dir() else ""},
                {
                    "role": "user",
                    "content": (
                        "Your previous reply was not a single valid JSON object "
                        "matching the required schema. Respond again with ONLY "
                        "the JSON object."
                    ),
                },
            ]
        except anthropic.APIStatusError as exc:
            # Rate limits / server errors: exponential backoff then retry.
            last_error = exc
            if exc.status_code in (429, 500, 502, 503, 529):
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                log.warning(
                    "API %s for %s; sleeping %.1fs (attempt %d/%d)",
                    exc.status_code, posting.uid, delay, attempt, MAX_ATTEMPTS,
                )
                time.sleep(delay)
            else:
                raise ScoringError(f"Non-retryable API error: {exc}") from exc

    raise ScoringError(
        f"Failed to score {posting.uid} after {MAX_ATTEMPTS} attempts: {last_error}"
    )
