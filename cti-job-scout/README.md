# CTI Job Scout

A personal job-scouting agent for a SOC analyst moving into **Cyber Threat Intelligence, Detection Engineering, and Threat Hunting**. Once a day it pulls every open posting from a curated list of companies' public Greenhouse and Lever job boards, asks an LLM of your choice (any [LiteLLM](https://docs.litellm.ai/)-supported provider — Anthropic, OpenAI, Google, local Ollama, and 100+ more) to score each *new* posting against your role profile, emails you a digest of everything above your threshold via the Gmail API, and refreshes a filterable web dashboard.

## Architecture in plain language

1. **Fetch** — `config/companies.yaml` lists tracked companies; `fetchers.py` pulls their open postings from the public Greenhouse/Lever APIs (no auth needed). One broken company logs an error and is skipped; the run continues.
2. **Dedup** — `state/state.json` remembers every posting ID ever scored, so a posting is only scored and emailed once. The Actions workflow commits this file back to the repo after each run. (Chosen over an Actions cache/artifact deliberately: caches get evicted and artifacts expire, and either failure would re-email your entire backlog. A committed JSON file is durable and `git log state/state.json` doubles as an audit trail.)
3. **Score** — `scoring.py` sends each new posting's title, locations, and description to your configured LLM with the rubric in `prompts.py`. All model calls go through **[LiteLLM](https://docs.litellm.ai/)**, a thin adapter that exposes a single `completion()` interface over 100+ providers, so switching between Anthropic, OpenAI, Gemini, a local Ollama model, etc. is a one-line env-var change (`JOBSCOUT_MODEL`) with no code edits. The model returns strict JSON (`score` 0–100, one-line `rationale`, `matched_keywords`), validated with pydantic; malformed output triggers a corrective retry, and a posting that can't be scored is retried automatically on the next run.
4. **Digest** — `digest.py` builds an HTML email of new matches at or above the threshold (default 60), sorted by score, split into *Remote-eligible* and *On-site/Hybrid* sections, with company, title, score, rationale, location, and an apply link on every entry.
5. **Dashboard** — `dashboard.py` writes `docs/jobs.json` from the accumulated match history; `docs/index.html` is a static page that filters it live by **city/metro, state, remote-only, minimum score, and free-text search**. Email clients strip JavaScript, so interactive filtering can't live in the email itself — the digest links to this dashboard instead.
6. **Send** — `mailer.py` sends via the Gmail API with OAuth2 (scope: `gmail.send` only — the token can send as you but never read your mail). No SMTP passwords anywhere.
7. **Orchestrate** — `src/jobscout/main.py` runs the whole pipeline; `.github/workflows/job-scout.yml` schedules it daily and commits the updated state.

```
config/companies.yaml ──► fetchers ──► dedup (state.json) ──► LLM scoring (LiteLLM)
                                                             │
                        Gmail digest ◄── digest builder ◄────┤ (score ≥ threshold)
                        docs/index.html ◄── docs/jobs.json ◄─┘
```

## Local setup

```bash
git clone <your-repo-url> cti-job-scout && cd cti-job-scout
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # installs litellm, pydantic, google libs, etc.

cp .env.example .env        # fill in your secrets (see sections below)
export $(grep -v '^#' .env | grep -v '^$' | xargs)

# First run: everything except sending email
DRY_RUN=1 PYTHONPATH=src python -m jobscout.main

# Real run
PYTHONPATH=src python -m jobscout.main

# Tests
python -m pytest
```

Before your first run, pick a scoring model and set the matching provider key in `.env` — see [**LLM provider setup (LiteLLM)**](#llm-provider-setup-litellm) below. The defaults use Anthropic's Claude, but any LiteLLM-supported provider works with no code changes.

To view the dashboard locally after a run:

```bash
python -m http.server -d docs 8000   # then open http://localhost:8000
```

(Opening `docs/index.html` directly via `file://` won't work — browsers block the `jobs.json` fetch.)

## Validate the company list first

The pre-populated list in `config/companies.yaml` targets the same profile as the postings you've been saving — AI-lab threat intel (Anthropic, OpenAI), MDR/detection vendors (Red Canary, Expel, Huntress, Arctic Wolf), threat intel firms (Dragos, GreyNoise, Flashpoint, Recorded Future), security products with strong research teams (Elastic, SentinelOne, Corelight, Abnormal, Chainguard), and big-tech/fintech CTI (Cloudflare, Datadog, Coinbase, Stripe, Plaid, Palantir). **Board tokens change when companies switch ATS vendors, so verify before relying on it:**

```bash
python scripts/validate_companies.py
```

Fix or delete anything it flags. Companies from your saved postings that use proprietary ATSes (Amazon, EY, Deloitte, Bank of America, Computershare, and vendors on Workday like CrowdStrike or Palo Alto Networks) can't be polled this way — track those manually or add a fetcher later.

### Adding / removing companies

Open the company's careers page. If the URL looks like `boards.greenhouse.io/<token>` or `job-boards.greenhouse.io/<token>`, add:

```yaml
  - name: Company Name
    ats: greenhouse
    token: <token>
```

If it looks like `jobs.lever.co/<token>`, use `ats: lever`. Delete a company by removing its block. Re-run the validator after any edit. (Removing a company doesn't purge its already-seen IDs from state — harmless, they just stop matching anything.)

## LLM provider setup (LiteLLM)

All scoring runs through **[LiteLLM](https://docs.litellm.ai/)**. LiteLLM normalizes 100+ LLM providers behind one OpenAI-style `completion()` call, so **the app is not tied to any single vendor** — you choose the model with an environment variable and never touch the code. Switching from Claude to GPT-4o (or to a free local model) is just a `JOBSCOUT_MODEL` change plus the right API key. There are exactly two things to set:

1. **`JOBSCOUT_MODEL`** — the model, as a LiteLLM string in `<provider>/<model>` form. Default: `anthropic/claude-sonnet-4-6`. Common choices:

   | Provider | `JOBSCOUT_MODEL` example | API key env var |
   |---|---|---|
   | Anthropic | `anthropic/claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
   | OpenAI | `openai/gpt-4o` | `OPENAI_API_KEY` |
   | Google Gemini | `gemini/gemini-2.0-flash` | `GEMINI_API_KEY` |
   | Ollama (local, free) | `ollama/llama3` | none — see note below |

   Every supported provider and its exact model strings and key variable: <https://docs.litellm.ai/docs/providers>. The `<provider>/` prefix is required — a bare model name like `gpt-4o` will fail with a "provider not provided" error.

2. **The matching API key** — set only the key for the provider you actually use; the others can stay unset.
   - **Locally:** put both `JOBSCOUT_MODEL` and the key in `.env` (see `.env.example`).
   - **GitHub Actions:** add the key as a repo **secret** (e.g. `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) and, if you're not using the default model, set `JOBSCOUT_MODEL` as a repository **variable**. The workflow already forwards `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `GEMINI_API_KEY`; to use any other provider, add its key env var to the `Run pipeline` step's `env:` block in `.github/workflows/job-scout.yml`.

**Ollama (local, no API key, no cost):** run [Ollama](https://ollama.com) on the same machine, `ollama pull llama3`, then set `JOBSCOUT_MODEL=ollama/llama3`. LiteLLM talks to `http://localhost:11434` by default; point elsewhere with `OLLAMA_API_BASE`. Note this only works where the model server is reachable — great for local runs, not for the GitHub Actions runner (which has no Ollama server).

Cost note: only *new* postings are scored, descriptions are truncated to ~12k characters, and responses are capped at 400 tokens — after the first backfill run, daily cost is typically pennies (or zero with a local model).

## Gmail API setup from scratch

One-time, ~10 minutes:

1. **Create a Google Cloud project**: <https://console.cloud.google.com> → project picker → **New project** → name it anything (e.g. `job-scout`).
2. **Enable the Gmail API**: **APIs & Services → Library** → search "Gmail API" → **Enable**.
3. **Configure the OAuth consent screen**: **APIs & Services → OAuth consent screen** → User type **External** → fill in app name and your email → add your own Gmail address under **Test users**. (Staying in "Testing" mode is fine for personal use; refresh tokens for test users expire after 7 days *unless* you publish the app — click **Publish app** to avoid weekly re-auth. Google may show an "unverified app" warning during the one-time authorization; that's expected for a personal tool.)
4. **Create OAuth credentials**: **APIs & Services → Credentials → Create credentials → OAuth client ID** → Application type **Desktop app** → **Download JSON** → save it as `scripts/credentials.json` (gitignored).
5. **Generate the refresh token** — run the included one-time script locally:

   ```bash
   pip install google-auth-oauthlib
   python scripts/get_gmail_refresh_token.py
   ```

   A browser opens; sign in with the account that should **send** the digests and approve the `gmail.send` scope. The script prints `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, and `GMAIL_REFRESH_TOKEN` ready to paste into your secrets.

## GitHub Actions deployment

1. Push this repo to GitHub.
2. **Add repo secrets** — Settings → Secrets and variables → Actions → **New repository secret**, one per row:

   | Secret name | Value |
   |---|---|
   | `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY` / `GEMINI_API_KEY` / …) | the API key for the provider in `JOBSCOUT_MODEL` |
   | `GMAIL_CLIENT_ID` | from the token script output |
   | `GMAIL_CLIENT_SECRET` | from the token script output |
   | `GMAIL_REFRESH_TOKEN` | from the token script output |
   | `DIGEST_RECIPIENT` | email address receiving the digest |

   Optionally add repository **variables** (same page, Variables tab): `JOBSCOUT_MODEL` (default `anthropic/claude-sonnet-4-6`), `SCORE_THRESHOLD` (default 60), and `DASHBOARD_URL` (your Pages URL, once enabled).
3. **Allow the workflow to push**: Settings → Actions → General → Workflow permissions → **Read and write permissions** (needed to commit `state/state.json` and `docs/jobs.json`).
4. **Schedule**: the workflow runs at `0 12 * * *` UTC = 8:00 AM EDT. GitHub cron has no DST awareness, so it drifts to 7:00 AM in winter; edit the cron in `.github/workflows/job-scout.yml` if that matters. Scheduled runs can start up to ~15 minutes late — normal GitHub behavior.
5. **Manual run**: Actions tab → **Job Scout Daily Run** → **Run workflow**. The first run scores your entire backlog and may take a while and send a long digest; consider temporarily raising `SCORE_THRESHOLD` for it.
6. **Logs**: Actions tab → click any run → click the `scout` job → expand steps. Every fetch, score, and skip is logged.
7. **Publish the dashboard (optional but recommended)**: Settings → Pages → Source: **Deploy from a branch** → branch `main`, folder `/docs`. Your dashboard appears at `https://<user>.github.io/<repo>/` — put that URL in the `DASHBOARD_URL` variable so every digest links to it. Note: on a public repo the dashboard (and repo) is public; use a private repo if you don't want your job search visible, in which case Pages requires a paid plan — or just open the dashboard locally.

## Adjusting the score threshold

Set the `SCORE_THRESHOLD` env var (locally in `.env`, in Actions as a repository variable). Postings below it are still recorded as seen, just not emailed. The dashboard has its own independent min-score slider. To change *what scores well*, edit the rubric and profile in `src/jobscout/prompts.py` — that file is the single tuning knob for relevance.

## Troubleshooting

| Symptom | Likely cause & fix |
|---|---|
| `invalid_grant` from Gmail | Refresh token expired or revoked. Most common cause: OAuth consent screen still in "Testing" (7-day token expiry) — publish the app, then re-run `scripts/get_gmail_refresh_token.py` and update the `GMAIL_REFRESH_TOKEN` secret. |
| Digest lands in spam | Normal for self-sent automated mail at first; mark as Not Spam once, or add a Gmail filter on the subject prefix `Job Scout:`. |
| `AuthenticationError` from the LLM provider | The API key secret for your `JOBSCOUT_MODEL` provider is missing/typo'd, or the key was revoked. |
| `BadRequestError` / "LLM Provider NOT provided" | `JOBSCOUT_MODEL` isn't a valid LiteLLM model string — use `<provider>/<model>` form (e.g. `openai/gpt-4o`) and check <https://docs.litellm.ai/docs/providers>. |
| `429` / rate-limited or overloaded provider | The scorer already backs off and retries 3× per posting; unscored postings retry next run automatically. If it persists on big backfills, raise `RETRY_BASE_DELAY` in `scoring.py` or split your company list temporarily. |
| A company fetch shows `HTTP 404` | Board token is wrong or the company left Greenhouse/Lever. Run `python scripts/validate_companies.py` and fix the entry. |
| Malformed ATS response / weird locations | The fetchers skip malformed individual jobs and always keep the raw location string; extend `METRO_MAP` in `locations.py` for cities you care about that lack a metro label. |
| Workflow fails at the commit step | Repo Settings → Actions → Workflow permissions must be **Read and write**. If it fails on `git push` after a rebase conflict, someone edited `state/state.json` manually — merge or delete the conflicting change. |
| Same job emailed twice | The state commit didn't land on a previous run (see above), or the job was reposted under a new ATS ID — reposts are genuinely new IDs and will be re-scored by design. |
| Empty digest every day | Threshold too high, company list too small, or scoring failing silently — check the run logs for `[ NN] Company — Title` lines to see actual scores. |
| Dashboard shows "jobs.json not found" | Run the pipeline at least once, and serve the folder over HTTP (`python -m http.server -d docs`) or GitHub Pages rather than opening the file directly. |

## Repo layout

```
config/companies.yaml        tracked companies (edit me)
src/jobscout/
  main.py                    orchestrator (python -m jobscout.main)
  config.py                  yaml + env loading
  models.py                  pydantic models
  fetchers.py                Greenhouse + Lever API clients
  locations.py               location parsing & metro normalization
  scoring.py                 LLM scoring (LiteLLM) w/ validation + retry
  prompts.py                 the scoring rubric — your main tuning knob
  state.py                   JSON dedup/state store
  digest.py                  HTML email builder
  dashboard.py               writes docs/jobs.json
  mailer.py                  Gmail API sender (OAuth2)
docs/index.html              filterable dashboard (metro/state/remote/score)
scripts/get_gmail_refresh_token.py   one-time Gmail OAuth bootstrap
scripts/validate_companies.py        checks every board token is live
state/state.json             created on first run; committed by the workflow
tests/                       pytest suite (37 tests, no network needed)
.github/workflows/job-scout.yml      daily schedule + manual trigger
```
