# role-watch

Checks Netflix and Meta for new **undergraduate internship** reqs and says so immediately.

Two halves, and the local one is now the primary:

- **On this Mac** — a launchd agent, Netflix every **3 minutes**, Meta every 10, with a macOS
  notification the moment something lands. It runs whenever the machine is on and needs no
  terminal, no session and no login. See *Local agent* below.
- **On GitHub Actions** — every 5 minutes around the clock, posting to Discord, as the backstop
  for when the Mac is off. GitHub's cron is best-effort and routinely runs ten to twenty minutes
  late, which is exactly why the local agent exists.

## Setup

Add a repository secret `DISCORD_WEBHOOK` (Discord → channel → Edit Channel → Integrations →
Webhooks → New Webhook → Copy Webhook URL). Optionally `DISCORD_MENTION`, e.g. `<@YOUR_USER_ID>`,
to get a push notification rather than a quiet message.

**Do not rely on GitHub's own notifications here** — issues opened, assigned or @-mentioned by
`github-actions[bot]` with the default token do not generate them, and watch settings cannot
override that.

Both companies pull reqs when they fill — Netflix's own postings say "open for no less than 7 days
and will be removed when the position is filled" — and neither emails you when one opens.

- **Netflix** has a JSON careers API.
- **Meta**'s site is JS-rendered, but its `jobsearch/sitemap.xml` lists every live job URL, and each
  job page exposes `og:title` to a plain request.

## How Netflix is read, and why three ways

The API returns **ten positions per page and ignores `num`** — `num=50` returns ten, which the
first version of this file did not know, so it was blind to every intern req past the tenth.
Pagination is by `start`, and the response carries `count`, the true size of the result set.

A keyword query only finds a req whose title already contains the keyword, so each run does:

1. `sort_by=new`, walked from the top until a whole page is already-seen — catches a brand new
   req **whatever it is called**, and a long gap just costs a few more pages.
2. `query=intern`, paginated in full.
3. `query=new grad`, paginated in full.

A steady-state run is three requests and about **one second**.

## One notification, for one req

**The only thing that makes a sound is the Netflix Software Engineer Intern, Summer 2027** — the
req there is a referral behind. His instruction, 2026-10-16: *"you got to make sure only notify
when its the right one."*

Everything else either company opens is still scanned and still written to `ROLE-WATCH.md`. It
just does not ring. That includes every Meta req; `--meta-notify` turns those banners back on.

A match rings **five times across two and a half minutes**, with sound, under its own banner, and
drops a `TARGET-FOUND.txt` beside the log. The last ring reads *"REFERRAL FIRST — have them file
it internally, then apply"*, because that is the actual first move, not opening the posting.

Since a title the matcher misses is now a title he never hears about, the net is the widest thing
that is still honestly *the right one*:

| Clause | Buys |
| --- | --- |
| early-career | intern · co-op · university · student · pathways · apprentice — Netflix has used several of these for the same job |
| not graduate-gated | a stated Master's/PhD minimum is a knockout |
| not senior, not "internal"/"international" | "Manager, University Recruiting" and "Internal Audit" are not it |
| right term | Summer 2027, **or no season named at all** — many reqs name none, and a silent req is likelier to be his than a Fall 2026 one |
| right discipline | an engineering word, **or** the title says Summer 2027 outright |
| not new-grad-only | a new-grad req is a full-time job for someone finishing this year; he finishes 2028 |

19 titles are verified against it, near misses included.

## Local agent

```bash
bash install_watcher.sh            # install or update
bash install_watcher.sh --off      # stop and remove
python3 watch_roles.py --test      # prove the banner works, touching nothing
```

It installs to `~/Library/Application Support/rolewatch/` rather than running from the repo,
because macOS privacy protection blocks launchd from reading `~/Desktop` and fails silently with
"Operation not permitted". **Re-run the installer after editing `watch_roles.py`.**

launchd runs a `StartInterval` job on wake if its turn came round while the machine was asleep,
so closing the lid costs one cycle, not the watch.

No credentials, no personal data — it reads two public endpoints and writes what it saw to `state/`.
