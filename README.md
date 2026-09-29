# role-watch

Checks Netflix and Meta every 5 minutes for new **undergraduate internship** reqs and opens an
issue when one appears.

Both companies pull reqs when they fill — Netflix's own postings say "open for no less than 7 days
and will be removed when the position is filled" — and neither emails you when one opens.

- **Netflix** has a JSON careers API.
- **Meta**'s site is JS-rendered, but its `jobsearch/sitemap.xml` lists every live job URL, and each
  job page exposes `og:title` to a plain request.

## Local agent (optional)

`bash install_watcher.sh` also runs it every 2 hours on macOS for a desktop notification while
the machine is awake; `--off` removes it. The Actions workflow covers 24/7 by itself.

No credentials, no personal data — it reads two public endpoints and writes what it saw to `state/`.
