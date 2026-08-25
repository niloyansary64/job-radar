#!/usr/bin/env python3
"""
Job Radar - collects remote IT jobs from public job-board APIs and scores
each one for whether someone outside the US/EU can realistically apply.

Run:  python3 fetch_jobs.py
Demo: python3 fetch_jobs.py --demo   (builds a sample page with no internet)
"""

import json
import re
import sys
import html
import hashlib
import datetime as dt
from xml.etree import ElementTree

import requests

HERE = __import__("os").path.dirname(__import__("os").path.abspath(__file__))
CONFIG_PATH = f"{HERE}/config.json"
JOBS_PATH = f"{HERE}/jobs.json"
DIGEST_PATH = f"{HERE}/digest.html"

UA = {"User-Agent": "JobRadar/1.0 (personal job search tool)"}
TIMEOUT = 25

with open(CONFIG_PATH) as f:
    CFG = json.load(f)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def clean(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(text))
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def any_of(needles, haystack):
    return [n for n in needles if n in haystack]


def job_id(title, company):
    return hashlib.md5(f"{title}|{company}".lower().encode()).hexdigest()[:12]


def parse_date(value):
    if not value:
        return None
    value = str(value)[:19].replace("/", "-")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%a, %d %b %Y %H:%M:%S"):
        try:
            return dt.datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def fetch_json(url, key=None):
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if key:
        data = data.get(key, [])
    return data if isinstance(data, list) else []


# --------------------------------------------------------------------------
# sources - every one is a public, documented endpoint
# --------------------------------------------------------------------------

def src_remotive():
    out = []
    for item in fetch_json("https://remotive.com/api/remote-jobs?limit=200", "jobs"):
        out.append({
            "title": clean(item.get("title")),
            "company": clean(item.get("company_name")),
            "location": clean(item.get("candidate_required_location")),
            "body": clean(item.get("description"))[:4000],
            "url": item.get("url", ""),
            "posted": item.get("publication_date"),
            "employment": clean(item.get("job_type")),
            "source": "Remotive",
        })
    return out


def src_remoteok():
    out = []
    data = fetch_json("https://remoteok.com/api")
    for item in data:
        if not isinstance(item, dict) or not item.get("position"):
            continue
        out.append({
            "title": clean(item.get("position")),
            "company": clean(item.get("company")),
            "location": clean(item.get("location")),
            "body": clean(item.get("description"))[:4000],
            "url": item.get("url", ""),
            "posted": item.get("date"),
            "employment": "",
            "source": "RemoteOK",
        })
    return out


def src_arbeitnow():
    out = []
    for item in fetch_json("https://www.arbeitnow.com/api/job-board-api", "data"):
        out.append({
            "title": clean(item.get("title")),
            "company": clean(item.get("company_name")),
            "location": clean(item.get("location")),
            "body": clean(item.get("description"))[:4000],
            "url": item.get("url", ""),
            "posted": dt.datetime.fromtimestamp(
                item.get("created_at", 0)).isoformat() if item.get("created_at") else None,
            "employment": ", ".join(item.get("job_types") or []),
            "source": "Arbeitnow",
        })
    return out


def src_jobicy():
    out = []
    for item in fetch_json("https://jobicy.com/api/v2/remote-jobs?count=50", "jobs"):
        out.append({
            "title": clean(item.get("jobTitle")),
            "company": clean(item.get("companyName")),
            "location": clean(item.get("jobGeo")),
            "body": clean(item.get("jobExcerpt") or item.get("jobDescription"))[:4000],
            "url": item.get("url", ""),
            "posted": item.get("pubDate"),
            "employment": ", ".join(item.get("jobType") or []),
            "source": "Jobicy",
        })
    return out


def src_himalayas():
    out = []
    for item in fetch_json("https://himalayas.app/jobs/api?limit=100", "jobs"):
        out.append({
            "title": clean(item.get("title")),
            "company": clean(item.get("companyName")),
            "location": ", ".join(item.get("locationRestrictions") or []) or "Not stated",
            "body": clean(item.get("description"))[:4000],
            "url": item.get("applicationLink") or item.get("guid", ""),
            "posted": dt.datetime.fromtimestamp(
                item.get("pubDate", 0)).isoformat() if item.get("pubDate") else None,
            "employment": item.get("employmentType", ""),
            "source": "Himalayas",
        })
    return out


def src_wwr():
    feeds = [
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
        "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
    ]
    out = []
    for feed in feeds:
        r = requests.get(feed, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        root = ElementTree.fromstring(r.content)
        for item in root.iter("item"):
            raw = clean(item.findtext("title"))
            company, _, title = raw.partition(":")
            out.append({
                "title": clean(title) or raw,
                "company": clean(company),
                "location": clean(item.findtext("region")) or "Not stated",
                "body": clean(item.findtext("description"))[:4000],
                "url": clean(item.findtext("link")),
                "posted": item.findtext("pubDate"),
                "employment": "",
                "source": "We Work Remotely",
            })
    return out


def src_reliefweb():
    out = []
    base = ("https://api.reliefweb.int/v1/jobs?appname=jobradar-personal"
            "&limit=40&sort[]=date:desc"
            "&fields[include][]=title&fields[include][]=source"
            "&fields[include][]=url&fields[include][]=date"
            "&fields[include][]=body&fields[include][]=type"
            "&query[value]=")
    for q in CFG["reliefweb_queries"]:
        r = requests.get(base + requests.utils.quote(q), headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        for entry in r.json().get("data", []):
            f = entry.get("fields", {})
            sources = f.get("source") or [{}]
            out.append({
                "title": clean(f.get("title")),
                "company": clean(sources[0].get("name")),
                "location": "See posting",
                "body": clean(f.get("body"))[:4000],
                "url": f.get("url", ""),
                "posted": (f.get("date") or {}).get("created"),
                "employment": ", ".join(t.get("name", "") for t in (f.get("type") or [])),
                "source": "ReliefWeb (NGO)",
            })
    return out


SOURCES = [
    ("Remotive", src_remotive),
    ("RemoteOK", src_remoteok),
    ("Arbeitnow", src_arbeitnow),
    ("Jobicy", src_jobicy),
    ("Himalayas", src_himalayas),
    ("We Work Remotely", src_wwr),
    ("ReliefWeb", src_reliefweb),
]


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

def score(job):
    """Returns the job with verdict fields added, or None if it should be dropped."""
    text = f"{job['title']} {job['location']} {job['body']}".lower()
    title = job["title"].lower()

    if any_of(CFG["scam_signals"], text):
        return None
    if any_of(CFG["exclude_keywords"], title):
        return None

    matched = any_of(CFG["role_keywords"], title)
    if not matched:
        return None

    posted = parse_date(job.get("posted"))
    if posted:
        age = (dt.datetime.now() - posted).days
        if age > CFG["max_age_days"]:
            return None
    else:
        age = None

    blocked = any_of(CFG["blocked_signals"], text)
    worldwide = any_of(CFG["worldwide_signals"], text)
    regional = any_of(CFG["region_signals"], text)
    sponsors = any_of(CFG["sponsorship_signals"], text)

    if worldwide and not blocked:
        verdict, rank = "Open to anywhere", 1
    elif regional and not blocked:
        verdict, rank = "May include your region", 2
    elif blocked:
        verdict, rank = "Likely restricted", 4
    else:
        verdict, rank = "Location unclear", 3

    if sponsors:
        rank -= 0.5

    job.update({
        "id": job_id(job["title"], job["company"]),
        "verdict": verdict,
        "rank": rank,
        "sponsors": bool(sponsors),
        "matched_on": matched[0],
        "age_days": age,
        "posted_human": posted.strftime("%d %b %Y") if posted else "Date not stated",
        "why": (worldwide + regional + blocked + sponsors)[:3],
    })
    job.pop("body", None)
    return job


# --------------------------------------------------------------------------
# digest email
# --------------------------------------------------------------------------

def build_digest(new_jobs, total):
    if not new_jobs:
        rows = "<p>No new matches today. The full list is still on your page.</p>"
    else:
        rows = ""
        for j in new_jobs[:25]:
            rows += (
                f'<p style="margin:0 0 14px 0">'
                f'<strong>{html.escape(j["title"])}</strong> &mdash; {html.escape(j["company"])}<br>'
                f'<span style="color:#0f6b4f">{j["verdict"]}</span>'
                f'{" &middot; sponsorship mentioned" if j["sponsors"] else ""}'
                f' &middot; {j["source"]}<br>'
                f'<a href="{html.escape(j["url"])}">Open the posting</a></p>'
            )
    doc = (
        '<div style="font-family:system-ui,sans-serif;max-width:600px;color:#10241d">'
        f'<h2 style="font-weight:500">{len(new_jobs)} new match'
        f'{"es" if len(new_jobs) != 1 else ""}</h2>'
        f'<p style="color:#5b6b66">{total} jobs on the board in total.</p>'
        f'{rows}</div>'
    )
    with open(DIGEST_PATH, "w") as f:
        f.write(doc)
    return doc


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def demo_jobs():
    samples = [
        ("IT Support Specialist", "Northwind Cloud", "Worldwide", "Remotive",
         "Fully remote, anywhere. We sponsor work permits for the right candidate."),
        ("Service Desk Analyst (Tier 2)", "Meridian Systems", "Asia, EMEA", "Himalayas",
         "Open to candidates across Asia and EMEA, any timezone."),
        ("Microsoft 365 Administrator", "Balto Group", "Not stated", "Arbeitnow",
         "Managing Intune, Entra and endpoint compliance for 900 staff."),
        ("ICT Officer", "Save the Children", "See posting", "ReliefWeb (NGO)",
         "Supporting country office infrastructure and end user support."),
        ("Desktop Support Engineer", "Cadence Retail", "United States", "RemoteOK",
         "US only. Must be authorized to work in the United States."),
    ]
    out = []
    for i, (t, c, loc, src, body) in enumerate(samples):
        out.append({
            "title": t, "company": c, "location": loc, "body": body,
            "url": "https://example.com/job", "employment": "Full time",
            "posted": (dt.datetime.now() - dt.timedelta(days=i)).isoformat(),
            "source": src,
        })
    return out


def main():
    demo = "--demo" in sys.argv
    raw, log = [], []

    if demo:
        raw = demo_jobs()
        log.append("Demo mode - sample data, no internet used")
    else:
        for name, fn in SOURCES:
            try:
                got = fn()
                raw.extend(got)
                log.append(f"{name}: {len(got)} fetched")
            except Exception as exc:
                log.append(f"{name}: unavailable ({type(exc).__name__})")

    scored, seen = [], set()
    for job in raw:
        result = score(job)
        if result and result["id"] not in seen:
            seen.add(result["id"])
            scored.append(result)

    scored.sort(key=lambda j: (j["rank"], j["age_days"] if j["age_days"] is not None else 99))

    previous = set()
    try:
        with open(JOBS_PATH) as f:
            previous = {j["id"] for j in json.load(f).get("jobs", [])}
    except Exception:
        pass

    for job in scored:
        job["is_new"] = job["id"] not in previous

    new_jobs = [j for j in scored if j["is_new"] and j["rank"] <= 3]

    payload = {
        "updated": dt.datetime.now().strftime("%d %b %Y, %H:%M UTC"),
        "total": len(scored),
        "new_count": len(new_jobs),
        "source_log": log,
        "jobs": scored,
    }
    with open(JOBS_PATH, "w") as f:
        json.dump(payload, f, indent=1)

    build_digest(new_jobs, len(scored))
    print("\n".join(log))
    print(f"Kept {len(scored)} matching jobs, {len(new_jobs)} of them new.")


if __name__ == "__main__":
    main()
