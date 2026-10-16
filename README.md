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

New Netflix reqs are then split in two. An early-career title that is not graduate-gated is
**hot**: three banners across a minute, with sound, the last one saying to get the referral filed
internally first. Everything else Netflix opens — and it opens several a day across 409 live reqs
— is **quiet**: written to `ROLE-WATCH.md`, no banner. Meta keeps the narrow filter, one banner.

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
