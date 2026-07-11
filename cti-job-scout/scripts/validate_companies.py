"""Validate every entry in config/companies.yaml against the live ATS APIs.

Board tokens go stale when companies switch ATS vendors, so run this after
editing the list (and occasionally thereafter):

    python scripts/validate_companies.py

For each company it reports OK (with current open-posting count) or the
failure reason. Exit code 1 if anything failed, so you can wire it into CI.
"""

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jobscout.config import load_companies  # noqa: E402

URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
    "lever": "https://api.lever.co/v0/postings/{token}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}",
}


def main() -> int:
    companies = load_companies(Path(__file__).resolve().parents[1] / "config/companies.yaml")
    session = requests.Session()
    session.headers["User-Agent"] = "cti-job-scout/validate"
    failures = 0

    for c in companies:
        url = URLS[c.ats].format(token=c.token)
        try:
            resp = session.get(url, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                # Greenhouse and Ashby wrap in {"jobs": [...]}; Lever is a bare list.
                n = len(data) if c.ats == "lever" else len(data.get("jobs", []))
                print(f"  OK   {c.name:<20} {c.ats}:{c.token} — {n} open postings")
            else:
                failures += 1
                print(f" FAIL  {c.name:<20} {c.ats}:{c.token} — HTTP {resp.status_code} "
                      f"(token likely wrong or company left this ATS)")
        except Exception as exc:
            failures += 1
            print(f" FAIL  {c.name:<20} {c.ats}:{c.token} — {exc}")

    print(f"\n{len(companies) - failures}/{len(companies)} boards reachable.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
