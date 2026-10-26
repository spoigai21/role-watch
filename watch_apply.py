#!/usr/bin/env python3
"""watch_apply - Snap, Airbnb and Oracle, for the reqs we intend to APPLY to.

Sibling of watch_roles.py, deliberately a separate file. watch_roles watches Netflix and Meta
and its Netflix alarm sits in front of a referral; breaking it to add three more companies
would risk the highest-stakes thing in the repo for no gain. This one has a different job:

    watch_roles : find it, tell him, he decides.
    watch_apply : find it, QUEUE it, so the next live Claude session tailors a resume and files
                  it the same hour.

Added 2026-10-25 on his instruction. All three were checked that day and none had a Summer 2027
software-engineering intern req open, which is the whole reason they are worth watching:

    Snap     careers.snap.com/api/jobs      JSON. 209 reqs, 4 intern-ish, none of them SWE.
                                            Postings link out to Workday (snapchat tenant).
    Airbnb   Greenhouse board API            JSON. 191 reqs, one intern (MBA, Finance).
    Oracle   Oracle ORC REST (CX_45001)      JSON. 2,265 reqs, zero SWE intern.

WHAT THIS CANNOT DO, said plainly because the design depends on it: it cannot apply. Applying
needs a tailored resume and a browser, and the browser is driven by a Claude session. launchd
runs whether or not a session exists, so this half does detection and hands over a queue file.
The apply half reads that queue the next time a session is live. See APPLY-RUNBOOK.md.

Usage
    python3 watch_apply.py                 # one pass, notify + queue anything new
    python3 watch_apply.py --baseline      # record what is live now WITHOUT notifying
    python3 watch_apply.py --all           # print every req seen, not just matches
    python3 watch_apply.py --test          # prove the banner works, touching nothing
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Single-sourced from the existing watcher on purpose: two copies of a matcher drift, and the
# one that drifts is the one that stops matching the job he wanted.
from watch_roles import (  # noqa: E402
    EARLY, GRAD_GATED, NOISE, SENIOR, NEWGRAD_ONLY, TARGET_KIND,
    TARGET_TERM, OTHER_TERM, TARGET_ROLE, banner,
)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

STATE = os.path.join(HERE, "state", "apply-seen.json")
QUEUE = os.path.join(HERE, "state", "APPLY-QUEUE.jsonl")
FLAG = os.path.join(HERE, "state", "APPLY-TARGET-FOUND.txt")
LOG = os.path.join(HERE, "state", "APPLY-WATCH.md")

# Software engineering, specifically. watch_roles casts wider because Netflix renames the same
# job; here a match turns into a filed application, so a Strategy Intern or a Verification
# Engineer Intern must not qualify. Snap already has both live.
SWE = re.compile(
    r"\b(software|swe|backend|back[- ]end|frontend|front[- ]end|full[- ]?stack|"
    r"infrastructure|platform|systems?|distributed|data (engineer|platform)|"
    r"machine learning|ml|ai|cloud|developer|engineering)\b", re.I)

# Disciplines that are engineering words but are not his direction (CLAUDE.md: not doing mobile;
# hardware/silicon is not his). Checked before SWE so "Verification Engineer" cannot sneak in.
WRONG_DISCIPLINE = re.compile(
    r"\b(verification|silicon|asic|rtl|analog|hardware|firmware|embedded|mechanical|optical|"
    r"ios|android|mobile|game|audio|rf|antenna|thermal|mechanical|chemical|"
    r"security research|hardware engineer)\b", re.I)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def get(url, timeout=30):
    """Fetch JSON via curl, for the reason watch_roles.get documents: the system Python on
    macOS ships without a usable CA bundle and urllib raises CERTIFICATE_VERIFY_FAILED on
    these hosts, while curl succeeds. Confirmed again here on Snap and Airbnb, 2026-10-25."""
    import subprocess
    try:
        r = subprocess.run(
            ["curl", "-sS", "--compressed", "--max-time", str(timeout),
             "-H", f"User-Agent: {UA}", "-H", "Accept: application/json", url],
            capture_output=True, text=True, timeout=timeout + 10)
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        raise RuntimeError(str(e)) from e
    if r.returncode != 0:
        raise RuntimeError((r.stderr or f"curl exit {r.returncode}").strip())
    return json.loads(r.stdout)


def wants(title):
    """Is this a software-engineering internship he would actually file?

    Same shape as watch_roles.is_target, tightened on discipline. Every clause earns its place:

      early-career      intern / co-op / university / student / apprentice
      not grad-gated    a stated Master's or PhD minimum is a knockout (CLAUDE.md)
      not senior/noise  "Manager, University Recruiting" is not a job for him
      not new-grad-only he finishes in 2028
      right term        Summer 2027, or no season named at all. A req naming Fall 2026 is out;
                        one naming nothing is kept, because most name nothing.
      right discipline  a software word, and NOT one of the disciplines he does not do. Snap
                        has a live "Verification Engineer Intern" and a "Spectacles Student
                        Worker - Software Engineer, Embedded"; neither should file itself.
    """
    if not title:
        return False
    if GRAD_GATED.search(title) or NOISE.search(title) or SENIOR.search(title):
        return False
    if not EARLY.search(title):
        return False
    if NEWGRAD_ONLY.search(title) and not TARGET_KIND.search(title):
        return False
    if WRONG_DISCIPLINE.search(title):
        return False
    if not TARGET_TERM.search(title) and OTHER_TERM.search(title):
        return False
    return bool(SWE.search(title) or TARGET_ROLE.search(title))


# --------------------------------------------------------------------------- sources

def snap():
    """careers.snap.com returns an Elasticsearch-shaped blob; the job lives in _source."""
    out = []
    data = get("https://careers.snap.com/api/jobs")
    for row in data.get("body", []):
        s = row.get("_source", {})
        title = s.get("title") or s.get("jobTitle") or ""
        if not title:
            continue
        out.append({
            "company": "Snap",
            "id": str(row.get("_id") or s.get("jobId") or title),
            "title": title,
            "location": s.get("primaryLocation") or s.get("location") or "",
            # Snap posts the description on its own site but applications run through Workday.
            "url": s.get("absolute_url") or s.get("canonicalUrl") or "https://careers.snap.com/jobs",
        })
    return out


def airbnb():
    """Airbnb runs a plain Greenhouse board - the cleanest of the three."""
    out = []
    data = get("https://boards-api.greenhouse.io/v1/boards/airbnb/jobs")
    for j in data.get("jobs", []):
        out.append({
            "company": "Airbnb",
            "id": str(j.get("id")),
            "title": j.get("title") or "",
            "location": (j.get("location") or {}).get("name", ""),
            "url": j.get("absolute_url") or "",
        })
    return out


def oracle(pages=3):
    """Oracle Cloud Recruiting. Two things this endpoint does that cost an hour to find:
    requisitionList comes back EMPTY unless `expand` asks for it, and `keyword=` is a loose
    full-text match - keyword=intern returns "Internal Auditor". So: no keyword, sort by
    posting date, walk the first few pages and filter on the title ourselves."""
    out = []
    base = ("https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/"
            "recruitingCEJobRequisitions?onlyData=true"
            "&expand=requisitionList.secondaryLocations,requisitionList.workLocation"
            "&finder=findReqs;siteNumber=CX_45001,limit=200,sortBy=POSTING_DATES_DESC")
    for p in range(pages):
        url = base + (f",offset={p * 200}" if p else "")
        try:
            data = get(url, timeout=40)
        except Exception:
            break
        items = data.get("items") or []
        if not items:
            break
        reqs = items[0].get("requisitionList") or []
        if not reqs:
            break
        for r in reqs:
            out.append({
                "company": "Oracle",
                "id": str(r.get("Id") or r.get("RequisitionId") or ""),
                "title": r.get("Title") or "",
                "location": r.get("PrimaryLocation") or "",
                "url": "https://careers.oracle.com/jobs/#en/sites/jobsearch/job/"
                       + str(r.get("Id") or ""),
            })
        if len(reqs) < 200:
            break
    return out


SOURCES = {"Snap": snap, "Airbnb": airbnb, "Oracle": oracle}


# --------------------------------------------------------------------------- state

def load_seen():
    try:
        with open(STATE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_seen(seen):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as fh:
        json.dump(seen, fh, indent=1, sort_keys=True)


def enqueue(job):
    """Append to the hand-off queue the apply half reads. JSONL so a half-written line from a
    killed process costs one row, not the file."""
    os.makedirs(os.path.dirname(QUEUE), exist_ok=True)
    row = dict(job)
    row["found_at"] = now()
    row["status"] = "pending"
    with open(QUEUE, "a") as fh:
        fh.write(json.dumps(row) + "\n")


def log(lines):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    new = not os.path.exists(LOG)
    with open(LOG, "a") as fh:
        if new:
            fh.write("# Snap / Airbnb / Oracle - apply watch\n\n"
                     "Every req these three open that matches the software-engineering intern "
                     "filter. A row here means it was queued for filing.\n\n")
        for line in lines:
            fh.write(line + "\n")


def alarm(job, repeat=4, gap=20):
    """Louder than one banner, because a banner nobody saw did not arrive. The last ring says
    what happens next rather than what happened, which is the thing he can act on."""
    head = f"{job['company']} - {job['title']}"
    body = f"{head} | {job.get('location') or 'location n/a'}"
    for i in range(max(1, repeat)):
        if i:
            time.sleep(gap)
        last = i == max(1, repeat) - 1
        banner("QUEUED TO APPLY - open Claude and say 'check the apply queue'. " + body
               if last else body,
               title=f"{job['company'].upper()} - SWE intern req is LIVE", sound="Glass")


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", action="store_true",
                    help="record what is live now without notifying or queueing")
    ap.add_argument("--all", action="store_true", help="print every req seen, not just matches")
    ap.add_argument("--test", action="store_true", help="fire a banner and exit")
    ap.add_argument("--quiet", action="store_true", help="no banners (for cron/CI)")
    args = ap.parse_args()

    if args.test:
        banner("watch_apply is alive. Snap, Airbnb, Oracle.", title="APPLY WATCH - test")
        print("banner sent")
        return 0

    seen = load_seen()
    found, errors, scanned = [], [], 0

    for name, fn in SOURCES.items():
        try:
            jobs = fn()
        except Exception as exc:                      # a dead endpoint must not kill the others
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        scanned += len(jobs)
        bucket = seen.setdefault(name, {})
        for job in jobs:
            if args.all:
                print(f"  {name:8} {job['title'][:70]}")
            if job["id"] in bucket:
                continue
            bucket[job["id"]] = job["title"]
            if wants(job["title"]):
                found.append(job)

    if args.baseline:
        save_seen(seen)
        print(f"baseline recorded: {scanned} reqs across {len(SOURCES)} sources"
              + (f"; errors: {'; '.join(errors)}" if errors else ""))
        return 0

    for job in found:
        enqueue(job)
        log([f"- **{now()}** — {job['company']}: {job['title']} "
             f"({job.get('location') or 'n/a'}) — {job.get('url')}"])
        if not args.quiet:
            alarm(job)

    if found:
        with open(FLAG, "w") as fh:
            fh.write(f"{now()}\n" + "\n".join(
                f"{j['company']}: {j['title']} -> {j.get('url')}" for j in found) + "\n")

    save_seen(seen)
    print(f"{now()}  scanned {scanned}  new matches {len(found)}"
          + (f"  ERRORS {'; '.join(errors)}" if errors else ""))
    for job in found:
        print(f"  QUEUED  {job['company']}: {job['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
