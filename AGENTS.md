# AGIOS — public repository

This repository is public. Treat every commit and push as publication.

- Commit only product source code, maintained documentation, build configuration,
  and intentional test code or fixtures.
- Never commit generated HTML reports, QA screenshots, recordings, test-run JSON
  or JSONL results, logs, diagnostic dumps, chat transcripts, local environment
  details, credentials, tokens, virtual disks, ISO images, caches or other
  temporary artifacts. Deliver reports separately when requested.
- Keep local reports and captures under ignored `.local/`, `docs/test-results/`
  or `docs/screenshots/`. Do not force-add ignored files.
- Product HTML such as `web/static/index.html` and the Live welcome page is source
  code, not a generated report, and belongs in Git.
- Before committing, inspect the staged file list and diff for publication safety.
  Before pushing, inspect all outgoing commits, not only the working tree.
- If unwanted artifacts were already pushed, a deletion commit does not remove
  them from history. Explain that distinction and, when history rewriting is
  authorized, remove them from all affected published branches and tags, use
  explicit force-with-lease checks, and verify the remote history afterward.
