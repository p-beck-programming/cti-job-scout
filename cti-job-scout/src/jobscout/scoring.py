"""Score postings for relevance with any LLM, via LiteLLM.

Design decisions:
- `litellm` is imported lazily so unit tests for the parser don't need
  the library or an API key.
- LiteLLM speaks to 100+ providers through one OpenAI-style interface, so
  the scoring model is just a string: set JOBSCOUT_MODEL to e.g.
  "anthropic/claude-sonnet-4-6", "openai/gpt-4o", "gemini/gemini-2.0-flash",
  or "ollama/llama3" and export the matching provider API key.
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

# Fallback when JOBSCOUT_MODEL is unset. Any LiteLLM model string works:
# "<provider>/<model>". See README. The env var is read at call time (not
# import time) so it picks up .env loaded by main.run().
DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"
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


def score_posting(
    posting: JobPosting, model: str | None = None, completion_fn=None
) -> Score:
    """Score one posting, retrying on malformed output and transient API errors."""
    import litellm  # lazy: keeps parser tests dependency-free

    # Resolve the model here (not as a default arg) so JOBSCOUT_MODEL from a
    # .env loaded at runtime is honored, not frozen at import time.
    if model is None:
        model = os.environ.get("JOBSCOUT_MODEL", DEFAULT_MODEL)

    if completion_fn is None:
        completion_fn = litellm.completion  # provider keys read from env

    # Transient failures worth backing off on; anything else (auth, bad
    # model string, bad request) fails fast as a ScoringError.
    retryable = (
        litellm.exceptions.RateLimitError,
        litellm.exceptions.InternalServerError,
        litellm.exceptions.ServiceUnavailableError,
        litellm.exceptions.APIConnectionError,
        litellm.exceptions.Timeout,
    )

    messages = [
        {"role": "system", "content": SCORING_SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(posting)},
    ]
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = completion_fn(
                model=model,
                max_tokens=400,
                messages=messages,
            )
            text = response.choices[0].message.content or ""
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
        except retryable as exc:
            # Rate limits / server errors / timeouts: exponential backoff.
            last_error = exc
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            log.warning(
                "Transient API error for %s; sleeping %.1fs (attempt %d/%d): %s",
                posting.uid, delay, attempt, MAX_ATTEMPTS, exc,
            )
            time.sleep(delay)
        except Exception as exc:
            # Auth failures, unknown model strings, malformed requests, etc.
            raise ScoringError(f"Non-retryable API error: {exc}") from exc

    raise ScoringError(
        f"Failed to score {posting.uid} after {MAX_ATTEMPTS} attempts: {last_error}"
    )
