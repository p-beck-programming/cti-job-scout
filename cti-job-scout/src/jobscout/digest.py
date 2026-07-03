"""Build the daily HTML email digest.

Note on filtering: Gmail (and nearly every mail client) strips JavaScript,
so the *email* cannot be interactively filterable. Instead the email shows
each posting's location prominently and separates Remote from On-site/Hybrid;
interactive filtering by city/metro/state lives in the dashboard
(docs/index.html), linked from the top of every digest.

Inline styles only — email clients ignore <style> blocks inconsistently.
"""

from __future__ import annotations

import html
from datetime import date

from .models import ScoredJob


def _score_color(score: int) -> str:
    if score >= 85:
        return "#1a7f37"  # green
    if score >= 70:
        return "#9a6700"  # amber
    return "#57606a"      # gray


def _entry_html(job: ScoredJob) -> str:
    p, s = job.posting, job.score
    locs = " &middot; ".join(html.escape(l.display()) for l in p.locations) or "Location not listed"
    keywords = ", ".join(html.escape(k) for k in s.matched_keywords[:8])
    return f"""
    <tr><td style="padding:14px 16px;border-bottom:1px solid #e5e7eb;">
      <div style="font-size:13px;color:#57606a;margin-bottom:2px;">{html.escape(p.company)}</div>
      <a href="{html.escape(p.url)}" style="font-size:16px;font-weight:600;color:#0b57d0;text-decoration:none;">{html.escape(p.title)}</a>
      <span style="display:inline-block;margin-left:8px;padding:1px 8px;border-radius:10px;background:{_score_color(s.score)};color:#fff;font-size:12px;font-weight:700;">{s.score}</span>
      <div style="font-size:13px;color:#333;margin-top:5px;">{html.escape(s.rationale)}</div>
      <div style="font-size:12px;color:#57606a;margin-top:5px;">&#128205; {locs}</div>
      {f'<div style="font-size:12px;color:#8250df;margin-top:3px;">Matched: {keywords}</div>' if keywords else ''}
      <div style="margin-top:8px;"><a href="{html.escape(p.url)}" style="font-size:13px;color:#0b57d0;">Apply &rarr;</a></div>
    </td></tr>"""


def _section(title: str, jobs: list[ScoredJob]) -> str:
    if not jobs:
        return ""
    rows = "".join(_entry_html(j) for j in jobs)
    return f"""
    <tr><td style="padding:18px 16px 6px;font-size:13px;font-weight:700;color:#57606a;text-transform:uppercase;letter-spacing:0.06em;">{html.escape(title)} ({len(jobs)})</td></tr>
    {rows}"""


def build_digest(jobs: list[ScoredJob], dashboard_url: str = "") -> tuple[str, str]:
    """Return (subject, html_body) for today's digest.

    Jobs are assumed pre-filtered to >= threshold; sorted here by score desc.
    """
    jobs = sorted(jobs, key=lambda j: j.score.score, reverse=True)
    remote = [j for j in jobs if any(l.is_remote for l in j.posting.locations)]
    onsite = [j for j in jobs if j not in remote]

    today = date.today().isoformat()
    subject = f"Job Scout: {len(jobs)} new CTI/DE/TH match{'es' if len(jobs) != 1 else ''} — {today}"

    dash_link = (
        f'<div style="margin-top:6px;font-size:13px;">'
        f'<a href="{html.escape(dashboard_url)}" style="color:#0b57d0;">'
        f"Open the dashboard to filter by city/metro, state, and score &rarr;</a></div>"
        if dashboard_url else ""
    )

    body = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f6f8fa;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 8px;">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
  <tr><td style="padding:20px 16px;background:#0d1117;">
    <div style="font-size:18px;font-weight:700;color:#ffffff;">CTI Job Scout &mdash; Daily Digest</div>
    <div style="font-size:13px;color:#9da7b3;margin-top:2px;">{today} &middot; {len(jobs)} new posting{'s' if len(jobs) != 1 else ''} above threshold</div>
    {dash_link}
  </td></tr>
  {_section("Remote-eligible", remote)}
  {_section("On-site / Hybrid", onsite)}
  <tr><td style="padding:14px 16px;font-size:12px;color:#8b949e;">
    Scores are the scoring model's relevance estimates against your CTI / Detection Engineering / Threat Hunting profile.
    Tune the rubric in <code>src/jobscout/prompts.py</code>.
  </td></tr>
</table>
</td></tr></table>
</body></html>"""
    return subject, body
