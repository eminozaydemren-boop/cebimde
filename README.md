# CEBİMDE V3.83

Price comparison and persistent target-price watches. Existing comparison providers and page styles are preserved.

## Deployment

Render build: `pip install -r requirements.txt`. Start: `gunicorn app:app`.
Set `DATABASE_URL` to the same-region internal PostgreSQL URL. Tables and additive columns are created automatically. Free Render Postgres expires after 30 days; the current instance expires on 2026-11-15.

## Free scheduled monitoring

`.github/workflows/price-watch.yml` runs at 00:23, 06:23, 12:23 and 18:23 UTC, plus manual dispatch and the workflow's initial push. GitHub schedules can be delayed or disabled after prolonged repository inactivity. Standard Ubuntu runners in this public repository are free. The workflow creates no artifacts or caches and requires no database credentials.

GitHub OIDC authenticates each scan request. The backend checks the signature, issuer, audience, immutable repository and owner IDs, public visibility, main branch, workflow path, and trigger type. Forks and pull requests cannot trigger scans. Each run handles up to 30 due watches, one at a time. Each watch is eligible after six hours; queues above 30 may take longer. Failed source checks wait until the next scheduled pass.

The monitor only reads structured Product/Offer data from public retailers without a seller whitelist. It never calls ReefAPI, Brave, or any paid fallback. Product identity, positive finite TRY price, and any explicit availability must pass validation. Blocked pages, missing structured data, foreign currency, sold-out offers, and ambiguous aggregate prices do not become current prices. The last verified price is retained and the failed attempt is shown separately.

Newly analyzed watches save signed product identity and up to three verified source URLs. Older watches fall back to their saved marketplace URL; reanalyzing and saving them once adds the independently verified source URLs.

## Notifications

An unread target-hit notice is stored per watch when a verified automatic price reaches its target. An unchanged hit is not repeated; a lower price or a new crossing can create another notice. Notices appear inside the site on synchronization, with a source link and read acknowledgement. An open page polls stored results every minute without querying price providers. This is not phone push, email, SMS, or WhatsApp delivery.

## Validation

Python: `python -m pytest -q` (requires pytest).
Frontend synchronization: `node --test tests/watch_sync.test.cjs`.
Live readiness: `/health` and `/api/watches/status`.

Saved-watch rechecks use `/api/watches/<id>/check` and only the free monitor. Rechecks require the owner key and have a one-minute per-watch cooldown. Optional `sourceUrl` must be a public HTTP(S) shop URL; it is saved only after that exact source passes identity and price verification. Acknowledging a notice does not delete the watch.

Product input validation rejects campaign/category/search pages before any price-provider request. Missing URL schemes are normalized to HTTPS. Hepsiburada `-p-` and `-pm-` product links are supported.


## Seller-independent discovery

Any public seller product URL can enter analysis, watch storage and free rechecks. Known marketplace campaign and listing URLs are rejected early. Other input pages are read for structured Product identity, GTIN, brand, model and title; missing identity falls back to page metadata, URL words or an optional user-provided name/barcode. An unverified title is not a verified price.

Each generic analysis makes up to two free SearXNG price queries and one separate brochure-discovery query, then checks up to six candidate pages concurrently, giving distinct merchants priority before repeated pages from the same merchant. Only fresh structured TRY offers with matching identity and no conflicting pack, capacity or color are shown. Search snippets are never treated as prices. The existing four-marketplace comparison adapters remain in place; the generic flow and monitoring invoke no paid adapters. Styles are preserved. When the free search service is unavailable, the client retries generic analysis up to three times, 12 seconds apart; existing marketplace adapters are never retried by this path.

Public reads validate every redirect and DNS result, pin connections to a validated public IP, verify TLS against the original hostname, and bound response size and read time. Private networks and credentials in URLs are rejected. Blocked retailers, missing structured data and unindexed products can still yield no verified offers. Acceptance of a seller URL does not promise exhaustive coverage of all sellers.

V3.83 reads a complete priced Product schema in the HTML head without waiting for large menus below it. Pack suffixes such as 40li and 100lu are excluded from model codes; consumer products get an unquoted name query. The optional product input has responsive form styling, and release URLs invalidate cached frontend assets.

When the original merchant denies server reads, the product identity can remain unconfirmed. Plausible consumer offers require the input brand in their verified product metadata, all descriptive input anchors and matching pack quantities. They are shown separately as unconfirmed candidates, never as verified comparisons, savings, signed snapshots or automatic watch prices. Structured brand arrays and HTML-encoded names are parsed. Public input read diagnostics contain only stage, status, byte count and error class.

V3.83 lets the user continue with an unconfirmed candidate as a new input product. The selected page is fetched again through `mode=public` and must independently supply identity and a valid price before comparison or watch saving. The former blocked input is not reclassified as verified. This route never enters paid marketplace adapters, even when a candidate is on one of the original four marketplaces. Exact descriptive title token multisets may match despite word order changes; all identifier, brand and pack conflict checks still apply.

V3.83 exposes brochure and comparison-source discovery separately. Source links do not claim a live price, an exact product match, an active campaign, branch availability or stock. They never enter price sorting, savings, signed snapshots or watch metadata. The displayed minimum is explicitly limited to found product-page offers; shipping and branch/member/brochure conditions are excluded.


### V3.84: conditional brochure prices

The existing free `price-watch.yml` workflow now has a separate public Ubuntu OCR job.
It discovers current Anpa Gross catalogs from Katalog24, follows page image links,
segments red price labels, and reads each isolated caption and raised decimal digits
with Tesseract. Prices are not fixtures or search snippets. The worker imports public
campaign cards using the existing repository-bound short-lived OIDC identity.
Only requests/Pillow/Tesseract are used; Render does not run OCR or call a paid API.

PostgreSQL retains the source page/image, image hash, product-card rectangle,
source dates, merchant, and scope as printed in the campaign title. Matching requires
brand, equal pack size, and descriptive words; one OCR character error is allowed
for words of five or more letters, but never for the brand. Matches remain explicitly
unconfirmed product variants and show the original image for checking. They never
change the verified online minimum, savings, signed price snapshot, or alerts.
Expired, future, and more-than-24-hour-stale imported cards are excluded. Stock and
national availability are not asserted. The first supported brochure provider is
Katalog24 and the first automatically scanned retailer is Anpa Gross; online seller
discovery remains open to public sellers. This does not guarantee exhaustive coverage.
