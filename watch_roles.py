#!/usr/bin/env python3
"""Watch Netflix and Meta for new early-career reqs, and say only what is new.

    python3 apply/watch_roles.py --baseline   # first run: record what exists, alert on nothing
    python3 apply/watch_roles.py              # every run after: print only new reqs
    python3 apply/watch_roles.py --all        # ignore the keyword filter, show every new req

Both companies open reqs on short windows and pull them when filled - Netflix postings state
"Job is open for no less than 7 days and will be removed when the position is filled" - and
neither emails you when one opens. Missing the opening is the whole failure mode.

HOW EACH ONE IS READ (both verified working 2026-09-28):

  Netflix - a real JSON API, no browser needed:
      https://explore.jobs.netflix.net/api/apply/v2/jobs?domain=netflix.com&query=intern
    Returns `positions[]` with id, name, location, department, t_create. Full description for
    one req: .../api/apply/v2/jobs/<id>?domain=netflix.com

  Meta - metacareers.com is JS-rendered and returns nothing useful to curl, BUT:
      https://www.metacareers.com/jobsearch/sitemap.xml
    is plain-fetchable and lists every live job URL (~1,028). It has no titles, so a new id is
    fetched once for its og:title, which the page DOES expose server-side. First run records
    ids without fetching, so the baseline costs one request rather than a thousand.

State lives in `.roles-seen.json` (gitignored). Delete it to start over.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
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

# No spoofed User-Agent. Meta's sitemap REJECTS a browser UA and serves an error page, while
# curl's own default is accepted. Both Netflix endpoints are happy either way. Verified 2026-09-28.

# UNDERGRADUATE INTERN ROLES ONLY. Not new-grad, which is a post-graduation role, and not
# PhD- or Masters-gated intern reqs, which an undergraduate cannot apply to.
WANTED = re.compile(r"\b(intern|internship|co-?op)\b", re.I)
UNWANTED = re.compile(
    r"\b(internal|international|"                       # false matches on "intern"
    r"phd|ph\.d|doctoral|masters?|m\.s|mba|graduate student|"   # degree-gated
    r"new ?grad|university ?grad|"                      # post-graduation, not an internship
    r"manager|director|principal|staff|senior|lead)\b", re.I)


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


def netflix():
    """Every intern/new-grad req Netflix has live, as {id: {...}}."""
    out = {}
    for query in ("intern", "new grad"):
        url = ("https://explore.jobs.netflix.net/api/apply/v2/jobs"
               f"?domain=netflix.com&start=0&num=50&query={urllib.parse.quote(query)}"
               "&sort_by=timestamp")
        try:
            data = json.loads(get(url))
        except (FetchError, json.JSONDecodeError) as e:
            print(f"  ! netflix '{query}' failed: {e}", file=sys.stderr)
            continue
        for p in data.get("positions", []):
            out[f"netflix:{p['id']}"] = {
                "company": "Netflix",
                "title": p.get("name", ""),
                "location": p.get("location", ""),
                "team": p.get("department", ""),
                "url": f"https://explore.jobs.netflix.net/careers/job/{p['id']}",
                "created": p.get("t_create"),
            }
    return out


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


def interesting(title):
    return bool(title) and bool(WANTED.search(title)) and not UNWANTED.search(title)


def summary(text):
    """Write one line into the GitHub Actions run summary, so a run's conclusion is visible in
    the UI without needing a commit. Silently does nothing outside CI."""
    import os
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as fh:
            fh.write(text + "\n")


def notify(lines):
    """macOS banner. Silently does nothing anywhere else."""
    body = "; ".join(lines)[:230].replace('"', "'")
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification "{body}" with title "New req" sound name "Glass"'],
                       check=False, capture_output=True, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError):
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", action="store_true",
                    help="record what exists now and alert on nothing (run this first)")
    ap.add_argument("--all", action="store_true", help="skip the keyword filter")
    ap.add_argument("--max-new-meta", type=int, default=40,
                    help="cap Meta title lookups per run (default 40)")
    ap.add_argument("--state", help="path to the seen-reqs file (default: beside this script)")
    ap.add_argument("--log", help="path to the findings markdown (default: beside this script)")
    ap.add_argument("--github-output", action="store_true",
                    help="in CI: write found=1 and a summary to $GITHUB_OUTPUT")
    ap.add_argument("--test", action="store_true",
                    help="inject one fake finding to prove the alert path works, and do not "
                         "record it, so a real req is still reported later")
    a = ap.parse_args()

    global STATE, LOG
    if a.state:
        STATE = pathlib.Path(a.state)
    if a.log:
        LOG = pathlib.Path(a.log)
    STATE.parent.mkdir(parents=True, exist_ok=True)

    seen = json.loads(STATE.read_text()) if STATE.exists() else {}
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")

    nf = netflix()
    mids = meta_ids()
    fresh_meta = [k for k in mids if k not in seen]

    if a.baseline:
        seen.update({k: {"title": v["title"]} for k, v in nf.items()})
        seen.update({k: {"title": None} for k in mids})
        STATE.write_text(json.dumps(seen, indent=1, sort_keys=True))
        print(f"baseline recorded: {len(nf)} Netflix reqs, {len(mids)} Meta reqs. "
              f"Nothing will be reported until something changes.")
        return 0

    found = [v for k, v in nf.items() if k not in seen]

    # Meta has no titles in the sitemap, so only NEW ids cost a request.
    if len(fresh_meta) > a.max_new_meta:
        print(f"  note: {len(fresh_meta)} new Meta ids, checking the first {a.max_new_meta}",
              file=sys.stderr)
    for key in fresh_meta[: a.max_new_meta]:
        t = meta_title(mids[key])
        seen[key] = {"title": t}
        if t:
            found.append({"company": "Meta", "title": t, "location": "", "team": "",
                          "url": f"https://www.metacareers.com/profile/job_details/{mids[key]}/",
                          "created": None})
    for key in fresh_meta[a.max_new_meta:]:
        seen[key] = {"title": None}          # record it so it is not re-checked forever

    for k, v in nf.items():
        seen.setdefault(k, {"title": v["title"]})
    STATE.write_text(json.dumps(seen, indent=1, sort_keys=True))

    hits = found if a.all else [f for f in found if interesting(f["title"])]

    if a.test:
        hits = [{"company": "Netflix", "title": "TEST — Software Engineer Intern (Summer 2027)",
                 "location": "Los Gatos, CA", "team": "Engineering",
                 "url": "https://explore.jobs.netflix.net/careers", "created": None}]
        print("--test: injecting one fake finding. Nothing real is recorded or suppressed.")

    if not hits:
        line = (f"{stamp} — nothing new "
                f"({len(nf)} Netflix early-career reqs live, {len(mids)} Meta reqs live)")
        print(line)
        summary("✅ " + line)
        return 0

    summary(f"## 🔔 {len(hits)} new req(s) — {stamp}\n")
    lines = []
    for f in hits:
        where = " - ".join(x for x in (f["location"], f["team"]) if x)
        lines.append(f"{f['company']}: {f['title']}" + (f"  [{where}]" if where else ""))
        print(f"\n*** {f['company']}: {f['title']}")
        if where:
            print(f"    {where}")
        print(f"    {f['url']}")
        summary(f"- **{f['company']}** — {f['title']}" + (f" *({where})*" if where else "")
                + f"  \n  {f['url']}")

    if a.test:
        notify([h["title"] for h in hits])
        if a.github_output and (gh := __import__("os").environ.get("GITHUB_OUTPUT")):
            body = "\n".join(f"- **{f['company']}** - {f['title']}\n  {f['url']}" for f in hits)
            with open(gh, "a") as fh:
                fh.write("found=1\ncount=1\n")
                fh.write("body<<ROLEWATCH_EOF\n" + body + "\nROLEWATCH_EOF\n")
        print("\ntest alert sent. State and findings log untouched.")
        return 0

    with LOG.open("a") as fh:
        fh.write(f"\n## {stamp}\n\n")
        for f in hits:
            fh.write(f"- **{f['company']}** — {f['title']}  \n  {f['url']}\n")
    notify(lines)

    if a.github_output and (gh := __import__("os").environ.get("GITHUB_OUTPUT")):
        body = "\n".join(
            f"- **{f['company']}** - {f['title']}\n  {f['url']}" for f in hits)
        with open(gh, "a") as fh:
            fh.write("found=1\n")
            fh.write(f"count={len(hits)}\n")
            fh.write("body<<ROLEWATCH_EOF\n" + body + "\nROLEWATCH_EOF\n")

    print(f"\n{len(hits)} new. Logged to {LOG.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
