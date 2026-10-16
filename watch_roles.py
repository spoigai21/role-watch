#!/usr/bin/env python3
"""Watch Netflix and Meta for new early-career reqs, and say only what is new.

    python3 watch_roles.py --baseline   # first run: record what exists, alert on nothing
    python3 watch_roles.py              # every run after: report only new reqs
    python3 watch_roles.py --test       # prove the alert path works without touching state
    python3 watch_roles.py --all        # ignore the keyword filter, show every new req

Both companies open reqs on short windows and pull them when filled - Netflix postings state
"Job is open for no less than 7 days and will be removed when the position is filled" - and
neither emails you when one opens. Missing the opening is the whole failure mode.

HOW EACH ONE IS READ

  Netflix - a real JSON API, no browser needed:
      https://explore.jobs.netflix.net/api/apply/v2/jobs?domain=netflix.com
    Returns `positions[]` with id, name, locations[], department, display_job_id (the JRxxxxx a
    recruiter quotes), canonicalPositionUrl and t_create, plus `count` - the true size of the
    result set, which is how a paginated walk knows when it is finished.

    THE PAGE SIZE IS TEN AND `num` IS IGNORED. Verified 2026-10-16: num=10, num=20 and num=50
    all return exactly 10 positions. The previous version of this file asked for num=50 and
    believed it was seeing 50, so it was blind to every intern req past the tenth - a silent
    blind spot in the one check that matters. Pagination is by `start`, ten at a time, until
    `count` is reached.

  Meta - metacareers.com is JS-rendered and returns nothing useful to curl, BUT:
      https://www.metacareers.com/jobsearch/sitemap.xml
    is plain-fetchable and lists every live job URL (~1,200). It has no titles, so a new id is
    fetched once for its og:title, which the page DOES expose server-side. First run records
    ids without fetching, so the baseline costs one request rather than a thousand.

WHY NETFLIX IS READ THREE WAYS. A keyword query only finds a req whose title already contains
the keyword, so a req named something we did not guess is invisible to it. So the Netflix pass
is:

  1. `sort_by=new`, walked from the top until a whole page is already-seen - every brand new
     req at Netflix regardless of its title, however long the laptop was off.
  2. `query=intern`, paginated in full.
  3. `query=new grad`, paginated in full.

(1) is the safety net: it cannot miss a req because the title surprised us.

State lives in `.roles-seen.json` (gitignored). Delete it to start over.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone

# State and log sit NEXT TO THIS FILE, not in the repo.
#
# On macOS, privacy protection (TCC) forbids a launchd agent from reading ~/Desktop, ~/Documents
# or ~/Downloads, failing with a bare "Operation not permitted" rather than a prompt. Keeping
# state beside the script means it works wherever the script is installed.
HERE = pathlib.Path(__file__).resolve().parent
STATE = HERE / ".roles-seen.json"
LOG = HERE / "ROLE-WATCH.md"

NFLX = "https://explore.jobs.netflix.net/api/apply/v2/jobs?domain=netflix.com"

# No spoofed User-Agent. Meta's sitemap REJECTS a browser UA and serves an error page, while
# curl's own default is accepted. Both Netflix endpoints are happy either way. Verified 2026-09-28.

# EARLY-CAREER, read widely. This is the net for Netflix, and it is deliberately wider than
# "intern": the req being waited for is named by Netflix, not by us, and a net that only
# catches the word we guessed is not a net.
EARLY = re.compile(r"\b(intern|interns|internship|co-?op|new ?grad(uate)?|university|student|"
                   r"early[- ]career|apprentice\w*|campus|pathways?|returnship|"
                   r"entry[- ]level|associate engineer)\b", re.I)

# "Internal Audit" and "International Partnerships" both contain "intern". Neither is a job for
# a sophomore.
NOISE = re.compile(r"\b(internal|international)\b", re.I)

# Seniority words that mean the title is not early-career no matter what else it says, e.g.
# "Manager, University Recruiting" - a real job, for someone else.
SENIOR = re.compile(r"\b(manager|director|principal|staff|senior|sr\.?|lead|head of|vp|"
                    r"recruiter|recruiting)\b", re.I)

# A stated graduate-degree requirement in the TITLE. Not filtered away - reported quietly,
# because CLAUDE.md treats a Master's/PhD minimum as a knockout, and an unseen req is worse
# than an irrelevant one.
GRAD_GATED = re.compile(r"\b(phd|ph\.d|doctoral|masters?|m\.s\.?|mba)\b", re.I)

# THE ONE HE IS WAITING FOR: Netflix Software Engineer Intern, Summer 2027, which he has a
# referral for. This is an ESCALATION on top of `hot`, never a filter - a title that fails to
# match here still rings as hot, so narrowing it can cost noise but can never cost the alert.
#
# "engineer|engineering|developer" is deliberately wider than "software": Netflix has titled
# this req "Software Engineering Intern" in some years and hung the discipline off the team
# name in others, and an extra loud banner is cheap against a missed one.
TARGET_ROLE = re.compile(r"\b(software|swe|engineer|engineering|developer)\b", re.I)
TARGET_KIND = re.compile(r"\b(intern|interns|internship|co-?op)\b", re.I)
NEWGRAD_ONLY = re.compile(r"\bnew ?grad(uate)?\b", re.I)
TARGET_TERM = re.compile(r"\bsummer\s*,?\s*2027\b", re.I)
# A season that is NOT his. Only used to rule a req out when it names a term and that term is
# the wrong one - a req naming no season at all still counts, because plenty do not.
#
# This must be checked even when the year is right. Matching on a bare "2027" made "Software
# Engineering Intern, Winter 2027" escalate as the target, because the year matched and the
# `or` short-circuited before the season was ever read. A Winter req is still something he
# wants - CLAUDE.md says an off-cycle term is not a knockout - so it still rings as `hot`,
# three banners. It just is not THE one.
OTHER_TERM = re.compile(r"\b(fall|autumn|winter|spring)\s*,?\s*20\d\d\b", re.I)


def is_target(title):
    """Netflix SWE Intern, Summer 2027 - the req with the referral behind it.

    THIS IS THE ONLY THING THAT PRODUCES A NOTIFICATION. His instruction, 2026-10-16: *"you
    got to make sure only notify when its the right one"*. Everything else either company
    opens is written to ROLE-WATCH.md and makes no sound at all.

    That raises the stakes on this function, because a title it fails to match is now a title
    he never hears about. So it is drawn as the widest net that is still honestly "the right
    one", and each clause below says what it is buying:

      early-career       - intern, co-op, new grad, university, student, pathways, apprentice.
                           Netflix has used several of these for the same job.
      not grad-gated     - a stated Master's/PhD minimum is a knockout (CLAUDE.md).
      not senior / noise - "Manager, University Recruiting" and "Internal Audit" are not it.
      right term         - Summer 2027, or NO season named at all. Many reqs name none, and a
                           silent req is far likelier to be his than a Fall 2026 one.
      right discipline   - an engineering word, OR the title says Summer 2027 outright. The
                           second half is deliberate: a Netflix intern req that names his exact
                           term is worth a banner whatever the discipline line calls it.
    """
    if not title or GRAD_GATED.search(title) or NOISE.search(title) or SENIOR.search(title):
        return False
    if not EARLY.search(title):
        return False
    # A new-grad req is a full-time job for someone finishing this year. He finishes in 2028,
    # so it is not his and it does not ring - but it is still scanned and still logged, and
    # a title carrying BOTH words ("New Grad / Intern Program") is kept, since that pairing
    # usually means the intern track.
    if NEWGRAD_ONLY.search(title) and not TARGET_KIND.search(title):
        return False
    summer = bool(TARGET_TERM.search(title))
    if not summer and OTHER_TERM.search(title):
        return False                      # it names a season, and it is not his
    return summer or bool(TARGET_ROLE.search(title))


class FetchError(Exception):
    pass


def get(url, timeout=30):
    """Fetch via curl.

    Not urllib: the system Python on macOS ships without a usable CA bundle, so urllib raises
    CERTIFICATE_VERIFY_FAILED on both of these hosts while curl succeeds. curl is always present
    on macOS, so this removes an entire class of "it worked for me" failure.
    """
    try:
        r = subprocess.run(
            ["curl", "-sS", "--compressed", "--max-time", str(timeout), url],
            capture_output=True, text=True, timeout=timeout + 10)
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        raise FetchError(str(e)) from e
    if r.returncode != 0:
        raise FetchError((r.stderr or f"curl exit {r.returncode}").strip())
    return r.stdout


# --------------------------------------------------------------------------- Netflix

def nflx_page(extra):
    """One page of ten. Returns ({key: record}, count), where count is the size of the whole
    result set, not of this page."""
    try:
        d = json.loads(get(NFLX + extra))
    except (FetchError, json.JSONDecodeError) as e:
        raise FetchError(f"netflix '{extra}': {e}") from e
    out = {}
    for p in d.get("positions", []):
        locs = p.get("locations") or [p.get("location") or ""]
        out[f"netflix:{p['id']}"] = {
            "company": "Netflix",
            "title": (p.get("name") or "").strip(),
            "location": ", ".join(x for x in locs if x)[:120],
            "team": p.get("department") or "",
            "req": p.get("display_job_id") or "",
            "url": (p.get("canonicalPositionUrl")
                    or f"https://explore.jobs.netflix.net/careers/job/{p['id']}"),
            "created": p.get("t_create"),
        }
    return out, d.get("count", 0)


def nflx_walk(query, max_pages=12):
    """A keyword query, paginated in full (to the cap). Ten results per page, always."""
    out = {}
    qs = urllib.parse.quote(query)
    try:
        page, count = nflx_page(f"&query={qs}&start=0")
    except FetchError as e:
        print(f"  ! {e}", file=sys.stderr)
        return out
    out.update(page)
    start = 10
    while start < min(count, max_pages * 10):
        try:
            page, _ = nflx_page(f"&query={qs}&start={start}")
        except FetchError as e:
            print(f"  ! {e}", file=sys.stderr)
            break
        if not page:
            break
        out.update(page)
        start += 10
    return out


def nflx_newest(seen, max_pages=10):
    """Every req Netflix has opened lately, whatever it is called.

    Walks `sort_by=new` from the top and stops at the first page where nothing is new. That
    stopping rule is what makes a week of the laptop being off harmless: a long gap simply
    costs a few more pages, and a quiet hour costs exactly one request.
    """
    out = {}
    for i in range(max_pages):
        try:
            page, count = nflx_page(f"&sort_by=new&start={i * 10}")
        except FetchError as e:
            print(f"  ! {e}", file=sys.stderr)
            break
        if not page:
            break
        out.update(page)
        if not any(k not in seen for k in page):
            break                      # caught up with what was already known
        if (i + 1) * 10 >= count:
            break
    return out


def netflix(seen, deep=False):
    """All three Netflix passes, merged. `deep` ignores the already-seen stopping rule, which
    is what a baseline wants."""
    out = {}
    out.update(nflx_newest({} if deep else seen, max_pages=12 if deep else 10))
    out.update(nflx_walk("intern"))
    out.update(nflx_walk("new grad"))
    return out


# --------------------------------------------------------------------------- Meta

def meta_ids():
    """Every live Meta job id, from the sitemap. Titles are fetched separately, only for new ids."""
    try:
        xml = get("https://www.metacareers.com/jobsearch/sitemap.xml", timeout=45)
    except FetchError as e:
        print(f"  ! meta sitemap failed: {e}", file=sys.stderr)
        return {}
    return {f"meta:{m}": m for m in re.findall(r"/job_details/(\d+)/", xml)}


def meta_title(job_id):
    """metacareers.com is JS-rendered, but og:title is in the served HTML."""
    try:
        html = get(f"https://www.metacareers.com/profile/job_details/{job_id}/", timeout=25)
    except FetchError:
        return None
    m = re.search(r'"og:title"\s+content="([^"]*)"', html)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- classify

def meta_interesting(title):
    """Meta's filter stays narrow. Meta has ~1,200 live reqs and opens a dozen a day; an
    unfiltered Meta feed is not an alert, it is a mailing list."""
    if not title or not EARLY.search(title) or NOISE.search(title):
        return False
    return not (SENIOR.search(title) or GRAD_GATED.search(title))


def netflix_tier(title):
    """'hot' or 'quiet'.

    hot   - an undergraduate-shaped early-career req. The thing being watched for.
    quiet - early-career but graduate-degree-gated, or any other new Netflix req. Logged and
            printed, no banner: Netflix keeps ~409 reqs live and opens several a day.
    """
    if not title:
        return "quiet"
    if EARLY.search(title) and not NOISE.search(title) and not SENIOR.search(title):
        return "quiet" if GRAD_GATED.search(title) else "hot"
    return "quiet"


# --------------------------------------------------------------------------- output

def summary(text):
    """Write one line into the GitHub Actions run summary, so a run's conclusion is visible in
    the UI without needing a commit. Silently does nothing outside CI."""
    import os
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as fh:
            fh.write(text + "\n")


def banner(body, title="New req", sound="Glass"):
    """One macOS notification. Silently does nothing anywhere else."""
    body = body[:230].replace("\\", "").replace('"', "'")
    title = title.replace('"', "'")
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification "{body}" with title "{title}" '
                        f'sound name "{sound}"'],
                       check=False, capture_output=True, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError):
        pass


def alarm(lines, repeat=3, gap=18, title="NETFLIX - early-career req is LIVE"):
    """The loud one. A banner nobody was at the desk for is a banner that did not arrive, so a
    hot req rings three times across a minute rather than once.

    The last ring says what to DO, not what happened. Netflix is the one company here where
    the move is not "open the posting" - there is a referral, so the first action is to tell
    the referrer to file it internally, and a banner that only names the req invites the
    wrong one.
    """
    body = "; ".join(lines)
    for i in range(max(1, repeat)):
        if i:
            time.sleep(gap)
        last = i == max(1, repeat) - 1
        banner("REFERRAL FIRST - have them file it internally, then apply. " + body if last
               else body,
               title=title, sound="Glass")


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", action="store_true",
                    help="record what exists now and alert on nothing (run this first)")
    ap.add_argument("--all", action="store_true",
                    help="print every new req, not just the ones worth a notification")
    ap.add_argument("--meta-notify", action="store_true",
                    help="also notify on new Meta early-career reqs. OFF by default since "
                         "2026-10-16: he asked to be notified only for the Netflix req he is "
                         "waiting for. Meta is still scanned and still logged.")
    ap.add_argument("--test", action="store_true",
                    help="inject one fake finding to prove the alert path works, and do not "
                         "record it, so a real req is still reported later")
    ap.add_argument("--max-new-meta", type=int, default=40,
                    help="cap Meta title lookups per run (default 40)")
    ap.add_argument("--meta-every", type=int, default=10,
                    help="check Meta at most once every N minutes (default 10). Netflix is "
                         "checked every run; Meta's sitemap is ~1 MB and does not need that "
                         "cadence.")
    ap.add_argument("--state", help="path to the seen-reqs file (default: beside this script)")
    ap.add_argument("--log", help="path to the findings markdown (default: beside this script)")
    ap.add_argument("--github-output", action="store_true",
                    help="in CI: write found=1 and a summary to $GITHUB_OUTPUT")
    a = ap.parse_args()

    global STATE, LOG
    if a.state:
        STATE = pathlib.Path(a.state)
    if a.log:
        LOG = pathlib.Path(a.log)
    STATE.parent.mkdir(parents=True, exist_ok=True)

    if a.test:
        hits = [{"company": "Netflix", "title": "TEST - Software Engineer Intern (Summer 2027)",
                 "location": "Los Gatos, CA", "team": "Engineering", "req": "JR00000",
                 "url": "https://explore.jobs.netflix.net/careers", "created": None}]
        print("--test: injecting one fake finding. Nothing real is recorded or suppressed.")
        print(f"    is_target: {is_target(hits[0]['title'])}")
        alarm([f"{h['company']}: {h['title']}" for h in hits], repeat=2, gap=4,
              title="NETFLIX SWE INTERN SUMMER 2027 IS LIVE")
        if a.github_output and (gh := __import__("os").environ.get("GITHUB_OUTPUT")):
            body = "\n".join(f"- **{f['company']}** - {f['title']}\n  {f['url']}" for f in hits)
            with open(gh, "a") as fh:
                fh.write("found=1\ncount=1\n")
                fh.write("body<<ROLEWATCH_EOF\n" + body + "\nROLEWATCH_EOF\n")
        print("test alert sent. State and findings log untouched.")
        return 0

    seen = json.loads(STATE.read_text()) if STATE.exists() else {}
    now = datetime.now(timezone.utc)
    stamp = now.astimezone().strftime("%Y-%m-%d %H:%M")

    nf = netflix(seen, deep=a.baseline)

    # Meta runs on its own, slower clock. Keys starting with "_" are bookkeeping, never req ids.
    last_meta = seen.get("_meta_checked", 0)
    due = a.baseline or (now.timestamp() - last_meta) >= a.meta_every * 60
    mids = meta_ids() if due else {}
    if due:
        seen["_meta_checked"] = now.timestamp()
    fresh_meta = [k for k in mids if k not in seen]

    if a.baseline:
        seen.update({k: {"title": v["title"]} for k, v in nf.items()})
        seen.update({k: {"title": None} for k in mids})
        STATE.write_text(json.dumps(seen, indent=1, sort_keys=True))
        print(f"baseline recorded: {len(nf)} Netflix reqs, {len(mids)} Meta reqs. "
              f"Nothing will be reported until something changes.")
        return 0

    new_nf = [v for k, v in nf.items() if k not in seen]

    # Meta has no titles in the sitemap, so only NEW ids cost a request.
    new_meta = []
    if len(fresh_meta) > a.max_new_meta:
        print(f"  note: {len(fresh_meta)} new Meta ids, checking the first {a.max_new_meta}",
              file=sys.stderr)
    for key in fresh_meta[: a.max_new_meta]:
        t = meta_title(mids[key])
        seen[key] = {"title": t}
        if t:
            new_meta.append({"company": "Meta", "title": t, "location": "", "team": "", "req": "",
                             "url": f"https://www.metacareers.com/profile/job_details/{mids[key]}/",
                             "created": None})
    for key in fresh_meta[a.max_new_meta:]:
        seen[key] = {"title": None}          # record it so it is not re-checked forever

    for k, v in nf.items():
        seen.setdefault(k, {"title": v["title"]})
    STATE.write_text(json.dumps(seen, indent=1, sort_keys=True))

    # ONE rule decides whether anything makes a sound: is this the Netflix req he is waiting
    # for. Meta reqs and every other Netflix opening are recorded, never announced.
    hot = [f for f in new_nf if f["company"] == "Netflix" and is_target(f["title"])]
    quiet = [f for f in new_nf if f not in hot] + new_meta
    if a.meta_notify:
        hot += [f for f in new_meta if meta_interesting(f["title"])]
        quiet = [f for f in quiet if f not in hot]

    if not hot and not quiet:
        line = (f"{stamp} - nothing new ({len(nf)} Netflix reqs scanned"
                + (f", {len(mids)} Meta reqs live" if due else ", Meta skipped") + ")")
        print(line)
        summary("OK " + line)
        return 0

    def describe(f):
        where = " - ".join(x for x in (f.get("location", ""), f.get("team", "")) if x)
        req = f" [{f['req']}]" if f.get("req") else ""
        return f"{f['company']}: {f['title']}{req}" + (f"  ({where})" if where else "")

    if quiet:
        print(f"\n-- {len(quiet)} other new req(s), logged, no notification --")
        for f in (quiet if a.all else quiet[:12]):
            print(f"   {describe(f)}\n   {f['url']}")
        if not a.all and len(quiet) > 12:
            print(f"   ... and {len(quiet) - 12} more, in {LOG.name}")

    if hot:
        summary(f"## {len(hot)} new req(s) - {stamp}\n")
        for f in hot:
            print(f"\n*** {describe(f)}")
            print(f"    {f['url']}")
            summary(f"- **{f['company']}** - {f['title']}  \n  {f['url']}")

    with LOG.open("a") as fh:
        fh.write(f"\n## {stamp}\n\n")
        for f in hot:
            fh.write(f"- **ALERT {f['company']}** - {f['title']}  \n  {f['url']}\n")
        for f in quiet:
            fh.write(f"- *(quiet)* {f['company']} - {f['title']}  \n  {f['url']}\n")

    target = [f for f in hot if f["company"] == "Netflix"]
    if target:
        # Five rings across two and a half minutes. This is the req the whole watcher exists
        # for, and now the only one that rings at all.
        alarm([describe(f) for f in target], repeat=5, gap=30,
              title="NETFLIX SWE INTERN SUMMER 2027 IS LIVE")
        (LOG.parent / "TARGET-FOUND.txt").write_text(
            stamp + "\n" + "\n".join(f"{describe(f)}\n{f['url']}" for f in target) + "\n")
    other = [f for f in hot if f["company"] != "Netflix"]      # only with --meta-notify
    if other:
        banner("; ".join(describe(f) for f in other), title="New req")

    if a.github_output and hot and (gh := __import__("os").environ.get("GITHUB_OUTPUT")):
        body = "\n".join(f"- **{f['company']}** - {f['title']}\n  {f['url']}" for f in hot)
        with open(gh, "a") as fh:
            fh.write("found=1\n")
            fh.write(f"count={len(hot)}\n")
            fh.write("body<<ROLEWATCH_EOF\n" + body + "\nROLEWATCH_EOF\n")

    print(f"\n{len(hot)} notified, {len(quiet)} logged silently. Logged to {LOG.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
