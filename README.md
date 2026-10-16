# CEBİMDE V3.77

Price comparison and persistent target-price watches. Existing comparison providers and page styles are preserved.

## Deployment

Render build: `pip install -r requirements.txt`. Start: `gunicorn app:app`.
Set `DATABASE_URL` to the same-region internal PostgreSQL URL. Tables and additive columns are created automatically. Free Render Postgres expires after 30 days; the current instance expires on 2026-11-15.

## Free scheduled monitoring

`.github/workflows/price-watch.yml` runs at 00:23, 06:23, 12:23 and 18:23 UTC, plus manual dispatch and the workflow's initial push. GitHub schedules can be delayed or disabled after prolonged repository inactivity. Standard Ubuntu runners in this public repository are free. The workflow creates no artifacts or caches and requires no database credentials.

GitHub OIDC authenticates each scan request. The backend checks the signature, issuer, audience, immutable repository and owner IDs, public visibility, main branch, workflow path, and trigger type. Forks and pull requests cannot trigger scans. Each run handles up to 30 due watches, one at a time. Each watch is eligible after six hours; queues above 30 may take longer. Failed source checks wait until the next scheduled pass.

The monitor only reads structured Product/Offer data from an explicit list of public retailers. It never calls ReefAPI, Brave, or any paid fallback. Product identity, positive finite TRY price, and any explicit availability must pass validation. Blocked pages, missing structured data, unsupported shops, foreign currency, sold-out offers, and ambiguous aggregate prices do not become current prices. The last verified price is retained and the failed attempt is shown separately.

Newly analyzed watches save signed product identity and up to three supported source URLs. Older watches fall back to their saved marketplace URL; reanalyzing and saving them once adds the independently verified source URLs.

## Notifications

An unread target-hit notice is stored per watch when a verified automatic price reaches its target. An unchanged hit is not repeated; a lower price or a new crossing can create another notice. Notices appear inside the site on synchronization, with a source link and read acknowledgement. An open page polls stored results every minute without querying price providers. This is not phone push, email, SMS, or WhatsApp delivery.

## Validation

Python: `python -m pytest -q` (requires pytest).
Frontend synchronization: `node --test tests/watch_sync.test.cjs`.
Live readiness: `/health` and `/api/watches/status`.

Saved-watch rechecks use `/api/watches/<id>/check` and only the free monitor. Rechecks require the owner key and have a one-minute per-watch cooldown. Optional `sourceUrl` must be an allowed HTTPS shop URL; it is saved only after that exact source passes identity and price verification. Acknowledging a notice does not delete the watch.

Product input validation rejects campaign/category/search pages before any price-provider request. Missing URL schemes are normalized to HTTPS. Hepsiburada `-p-` and `-pm-` product links are supported.
