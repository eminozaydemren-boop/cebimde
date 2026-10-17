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

Each generic analysis makes up to two free SearXNG price queries and one separate brochure-discovery query, then checks up to twelve candidate pages with six concurrent reads, giving distinct merchants priority before repeated pages from the same merchant. Only fresh structured TRY offers with matching identity and no conflicting pack, capacity or color are shown. Search snippets are never treated as prices. The existing four-marketplace comparison adapters remain in place; the generic flow and monitoring invoke no paid adapters. Styles are preserved. When the free search service is unavailable, the client retries generic analysis up to three times, 12 seconds apart; existing marketplace adapters are never retried by this path.

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


### V3.85: directory-wide discovery and resumable scanning

The fixed Anpa retailer input is replaced with every merchant listed by the provider's
public directory. Merchant pages reveal their actual catalog index links. Current
catalogs are queued in PostgreSQL; four standard public Ubuntu workers claim leased
three-page batches with `FOR UPDATE SKIP LOCKED`. Least-recently-attempted catalogs
run first. Large catalogs resume instead of being discarded at 32 pages. Each worker
has an 18-minute budget, with unprocessed pages retained for the next six-hour run.
Completed catalogs become due again after six hours; failed leases expire after ten
minutes. OIDC authentication remains tied to the same public main-branch workflow.
No paid runners, caches, artifacts, or paid price services are added.

A public coverage endpoint distinguishes merchants discovered, attempts, active
catalogs, indexed prices, and unavailable sources. The existing UI includes an
expandable coverage list. Directory membership never asserts that every product or
price was read. OCR supports more caption placements and red/yellow label geometry;
unreadable prices remain absent. Brochure identity stays unconfirmed and excluded
from online minima, savings, and notifications. Public-seller web discovery remains
independent of brochure directory membership. Coverage is not exhaustive worldwide.

Public seller extraction also accepts page-bound Product Open Graph metadata when
JSON-LD is absent. It requires a matching canonical host/path, an explicit product
type/title, and an explicit TRY price amount; unknown currency, stock rejection,
ranges, percentages and other-page metadata cannot become prices. Updated brochure
image hashes invalidate older prices from that image URL; expired cached brochure
records are cleaned during directory refresh.


### V3.86: shared product search recovery

The shared generic search read deadline is 30 seconds (10-second connection
deadline), allowing a free search instance to wake instead of discarding its
response after 7 seconds. Search result articles exclude footer/help links;
HTTP-200 error pages are no longer counted as completed searches. Definite
marketplace listings are removed before selecting up to twelve candidate product
pages, with distinct merchants first. Prices still require a fresh merchant
Product/Offer or explicit product metadata and a matching product identity.

All initial links and candidate selections in the web UI now explicitly use
`mode=public`, regardless of merchant. The existing marketplace adapters remain
in the backend, but this UI flow does not invoke paid services. There is no
product-specific URL or price table. Inaccessible shops and missing product
identity can still prevent a verified offer; universal store coverage is not
guaranteed.

V3.86.2 distinguishes upstream search-engine failures from a valid empty search.
The response includes only HTTP status, result count and failure class, never
endpoint configuration or credentials. When every price query reports upstream
failure, the client stops automatic identical retries and identifies a search
source failure rather than asking the user to rename the product. Live tests
found intermittent verified offers but also upstream rate limits/access denials;
this release does not establish reliable universal product discovery.


### V3.87: independent catalog discovery

Generic product discovery first searches the public Cimri and Epey catalogs by
brand/quantity or model, ranks product pages against the full input title, and
extracts merchant Offer URLs and explicit Epey data-link destinations. Up to
four catalog product pages and twelve merchant pages are read with bounded,
DNS-pinned public requests. No API keys, paid providers or per-product URL
tables are used. The SearXNG fallback has a 5-second connection and 12-second
read deadline to keep the combined request within the web worker budget.

An unreadable source product's title can be recovered only when the main catalog
Product schema explicitly links the exact submitted merchant product page.
Product-defining query parameters are preserved when checking that link.
Catalog prices are never used as verified merchant prices.

Explicit Epey offer-card prices are displayed separately with the catalog URL,
merchant URL, original offer title, read time and a clear unverified label.
Conflicting pack sizes, colors and models are rejected. Catalog quotes do not
affect minimum verified price, savings, watch receipts or target notifications.
Only fresh matching merchant reads can enter those calculations. This extends
discovery to the merchants in the catalogs; it cannot guarantee all products or
every shop on the internet.
