# Bangladesh Gold & Silver Price API — Build Specification

## 0. Goal (one line)
Build a small, reliable service that extracts today's **BAJUS gold price (buy/base price, per gram, per karat)** and **silver price (per gram, per karat)** from bajushub.com, normalizes it into clean JSON, and exposes it as a metered, API-key-authenticated REST API that can be sold on monthly subscription tiers.

## 1. What data you actually want (from your annotated screenshot)

Keep (green):
- সোনার দাম (Gold **buy/base** price) — per gram — for 22k, 21k, 18k, and Sanaton (traditional)
- রুপার দাম (Silver price) — per gram — for 22k, 21k, 18k, and Sanaton

Discard (red):
- বিক্রয় মূল্য (the "sell back to shop" price column) — this is just base price minus BAJUS's 16–20% deduction, so it's derivable, not a separate primary fact.

Also capture (metadata, not a line item):
- Timestamp shown on source page (`13-09-2026 ৬:৮৪:৬৮ PM` style — needs Bangla-digit parsing, see §3)
- USD/BDT rate footnote if present (useful for your own audit trail, optional to expose)
- ভরি equivalent (1 ভরি = 11.664 g) — you can compute this yourself instead of scraping the "ভরি" toggle, so store per-gram as the source of truth and derive ভরি, ana, ounce client-side or in the API response.

## 2. Extraction strategy — important finding

I fetched the page's raw HTML and the price table numbers are **not present in server-rendered HTML** — they're injected by client-side JS after load (likely fetched from a WordPress AJAX endpoint, a plugin's REST route, or a third-party price-widget script embedded on the page). This means:

- A plain `requests` + BeautifulSoup scrape of the homepage **will not get the numbers**.
- You need one of:
  1. **Find the underlying data endpoint.** Open bajushub.com in a browser, open DevTools → Network → XHR/Fetch, reload the page, and look for a request that returns JSON/HTML fragment with the price numbers (commonly `/wp-json/...`, `/wp-admin/admin-ajax.php`, or a third-party domain like a BAJUS-price-widget CDN). If found, hit that endpoint directly — much cheaper and more reliable than rendering a browser.
  2. **Headless browser rendering** (Playwright/Puppeteer) if no clean endpoint exists — load the page, wait for the table to populate, then parse the rendered DOM. Slower and more fragile, but always works if (1) fails.
- Build the scraper to try (1) first and fall back to (2) automatically if the endpoint 404s or its shape changes — sites like this often change their theme/plugin without notice.

**Action item before writing code:** inspect bajushub.com's Network tab once manually to find the real data source. That single finding determines whether this is a 20-line HTTP scraper or a headless-browser job — worth 10 minutes before scaffolding infrastructure.

## 3. Parsing notes
- Bangla numerals (০-৯) and Bangla currency formatting (৳, commas as `,`) need conversion — write a `bn_digits_to_en()` helper and strip `৳`/commas before casting to Decimal.
- Store prices as **Decimal/integer paisa**, never float, to avoid rounding drift over a price history table.
- Treat "no change detected since last poll" as a valid, cheap outcome — don't insert a duplicate row, just update `last_confirmed_at`.

## 4. System architecture

```
                         ┌─────────────────────┐
                         │   Scheduler (cron)   │  every 5–15 min
                         └──────────┬───────────┘
                                    ▼
                         ┌─────────────────────┐
                         │  Extractor Worker     │  (HTTP endpoint call,
                         │  (Node/Python)        │   fallback: Playwright)
                         └──────────┬───────────┘
                                    ▼
                         ┌─────────────────────┐
                         │  Normalizer/Validator │  Bangla→English digits,
                         │                       │  sanity-range check,
                         │                       │  diff vs last value
                         └──────────┬───────────┘
                                    ▼
                    ┌───────────────┴────────────────┐
                    ▼                                 ▼
         ┌─────────────────┐               ┌─────────────────────┐
         │ PostgreSQL       │               │ Redis (cache)        │
         │ (price history,  │◄──────────────┤ latest snapshot,      │
         │  audit log)      │   write-through│ rate-limit counters  │
         └────────┬─────────┘               └──────────┬───────────┘
                  │                                     │
                  └───────────────┬─────────────────────┘
                                   ▼
                         ┌─────────────────────┐
                         │   API Layer (REST)   │  FastAPI / Express
                         │   + API-key auth      │
                         │   + rate limiting     │
                         │   + usage metering     │
                         └──────────┬───────────┘
                                    ▼
                    ┌───────────────┴────────────────┐
                    ▼                                 ▼
         ┌─────────────────┐               ┌─────────────────────┐
         │ Customer apps     │               │ Admin/Billing panel  │
         │ (your jewellery   │               │ - issue/revoke keys   │
         │  site + 3rd party │               │ - Stripe/bKash plans  │
         │  subscribers)     │               │ - usage dashboards     │
         └─────────────────┘               └─────────────────────┘
```

## 5. Database schema (PostgreSQL)

```sql
-- Raw + normalized price snapshots
CREATE TABLE price_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    metal           TEXT NOT NULL CHECK (metal IN ('gold','silver')),
    karat_label     TEXT NOT NULL,        -- '22k','21k','18k','sanaton'
    price_per_gram  NUMERIC(12,2) NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'BDT',
    source_url      TEXT NOT NULL DEFAULT 'https://bajushub.com/',
    source_ts       TIMESTAMPTZ,          -- timestamp shown on source page
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_changed      BOOLEAN NOT NULL,     -- true if differs from prior snapshot
    UNIQUE (metal, karat_label, source_ts)
);
CREATE INDEX idx_price_latest ON price_snapshots (metal, karat_label, fetched_at DESC);

-- API consumers
CREATE TABLE api_keys (
    id              BIGSERIAL PRIMARY KEY,
    key_hash        TEXT NOT NULL UNIQUE,   -- store hash, never raw key
    key_prefix      TEXT NOT NULL,          -- shown to user for identification, e.g. 'gsp_live_ab12'
    owner_email     TEXT NOT NULL,
    plan            TEXT NOT NULL,          -- 'free','starter','pro','enterprise'
    monthly_quota   INTEGER NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ
);

CREATE TABLE api_usage_log (
    id              BIGSERIAL PRIMARY KEY,
    api_key_id      BIGINT REFERENCES api_keys(id),
    endpoint        TEXT NOT NULL,
    called_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    status_code     INT NOT NULL
);
```

## 6. API design

Base URL: `https://api.yourdomain.com/v1`

Auth: `Authorization: Bearer <api_key>` header (never accept keys as query params in production — they end up in logs).

| Endpoint | Method | Description |
|---|---|---|
| `/prices/gold/latest` | GET | Latest price per gram for all karats |
| `/prices/gold/latest?karat=22k` | GET | Single karat |
| `/prices/silver/latest` | GET | Latest silver, all karats |
| `/prices/history?metal=gold&karat=22k&from=&to=` | GET | Historical series (paid tiers only) |
| `/prices/convert?metal=gold&karat=22k&unit=vori&qty=1` | GET | Convenience unit conversion, computed server-side |
| `/meta/usage` | GET | Caller's current-month usage against quota |

Example response:
```json
{
  "metal": "gold",
  "as_of": "2026-09-13T18:04:00+06:00",
  "currency": "BDT",
  "unit": "gram",
  "prices": {
    "22k": 19970.00,
    "21k": 19075.00,
    "18k": 16380.00,
    "sanaton": 13380.00
  },
  "source": "BAJUS via bajushub.com",
  "cached": true
}
```

Design choices worth locking in early:
- **Cache-first reads.** Your scraper runs on its own schedule; API reads should always hit Redis, never trigger a live scrape per request — decouples your uptime from bajushub.com's uptime.
- **Stale-data flag.** If the scraper hasn't successfully refreshed in, say, 60 minutes, return the cached value plus `"stale": true` rather than an error — jewellery clients would rather have yesterday's number labeled stale than a 500.
- **Versioned URL (`/v1/`)** from day one, since you'll want to change response shape later without breaking paying customers.

## 7. Auth, rate limiting, subscription tiers

- Generate keys as `gsp_live_<32 random chars>`; store only a SHA-256 hash in the DB, show the raw key once at creation.
- Rate limit both by **requests/minute** (burst control, via Redis token bucket) and **requests/month** (plan quota, via `api_usage_log` count or a Redis counter reset monthly).
- Suggested tiers (adjust to your market):
  - Free: 100 req/month, latest-price endpoints only, 1-hour-old data allowed
  - Starter (~$5–10/mo): 5,000 req/month, latest + convert
  - Pro (~$25–40/mo): 50,000 req/month, + history endpoint, near-real-time refresh
  - Enterprise: custom quota, webhook push on price change instead of polling
- Billing: Stripe Billing (or a local gateway like SSLCommerz/bKash if most customers are Bangladeshi jewellery shops) with a webhook that flips `is_active` on `api_keys` when a subscription lapses.

## 8. Reliability & monitoring
- Alert (email/Slack) if the scraper fails 3 consecutive runs, or if a newly scraped price is >15% different from the previous one (likely a parsing bug, not a real market move) — hold that value for manual review instead of publishing it.
- Log every scrape attempt (success/failure, raw response snippet) for a rolling 7 days, so when bajushub.com changes their markup you can diagnose fast.
- Since you're dependent on one upstream site with no SLA, keep the fallback headless-browser path warm/tested even if the primary AJAX-endpoint path is what runs day to day.

## 9. Suggested stack
- **Extractor + API**: Node.js (Express/Fastify) or Python (FastAPI) — either is fine; FastAPI pairs well if you later want async scraping with `httpx`/Playwright.
- **DB**: PostgreSQL (Supabase or self-hosted, consistent with your existing self-hosted preference).
- **Cache/rate-limit store**: Redis.
- **Scheduler**: cron (simple) or a lightweight queue (BullMQ if Node) if you want retry/backoff logic.
- **Headless fallback**: Playwright (more stable than Puppeteer for this kind of "wait for late JS" scraping).
- **Docs**: auto-generate OpenAPI/Swagger from FastAPI/Express + swagger-ui, so subscribers get a self-serve docs page.

## 10. Legal/ethical note (read before shipping)
bajushub.com is itself republishing BAJUS committee prices — you're one hop removed from the primary source. Before reselling this commercially:
- Check bajushub.com's Terms/robots.txt for scraping restrictions.
- Poll politely (5–15 min interval, not per-second) and identify your scraper with a descriptive User-Agent.
- Consider displaying "Source: BAJUS, via bajushub.com" in your product — reduces legal exposure and is more accurate anyway, since BAJUS is the actual price-setting body.
- If this becomes a real revenue line, it may be worth reaching out to BAJUS or bajushub.com directly about a data-sharing arrangement rather than depending indefinitely on scraping a page that can change its markup any time.

---

## Ready-to-use build prompt (paste this to a coding agent / your dev)

> Build a REST API service in [FastAPI/Express — pick one] that:
> 1. Runs a background job every 10 minutes that fetches the current gold and silver prices (per gram, by karat: 22k/21k/18k/sanaton) from bajushub.com. First try calling the underlying JSON/AJAX endpoint the page's frontend uses (inspect via browser DevTools Network tab to find it); if unavailable, fall back to a Playwright headless-browser render of https://bajushub.com/ and parse the rendered DOM table. Only extract the "সোনার দাম" (buy/base price) column and the silver price table — ignore "বিক্রয় মূল্য" (sell price) entirely.
> 2. Converts Bangla numerals/currency formatting to standard Decimal values, validates the new price is within 15% of the prior stored value (flag and hold for review otherwise), and writes a new row to a `price_snapshots` table (schema in section 6 above) only if the value changed.
> 3. Writes the latest snapshot to Redis for fast reads, keyed by metal+karat.
> 4. Exposes versioned REST endpoints (`/v1/prices/gold/latest`, `/v1/prices/silver/latest`, `/v1/prices/history`, `/v1/prices/convert`, `/v1/meta/usage`) that read from Redis (never trigger a live scrape per request), and return `"stale": true` if the cache is older than 60 minutes.
> 5. Authenticates every request via an `Authorization: Bearer <key>` header checked against a hashed `api_keys` table; enforces per-minute burst limits and per-month quota by plan tier; logs every call to `api_usage_log`.
> 6. Includes an admin route (protected separately) to issue/revoke keys and view usage per key, plus a Stripe webhook handler that deactivates a key when its subscription lapses.
> 7. Auto-generates OpenAPI docs for the public API.
> 8. Sends an alert (email or Slack webhook) if the scraper fails 3 runs in a row or a price move exceeds the sanity threshold.
>
> Deliver as a dockerized service with a `docker-compose.yml` for Postgres + Redis + the API, environment-variable-based config, and a README covering setup, the scraper's fallback logic, and how to rotate/issue API keys.
