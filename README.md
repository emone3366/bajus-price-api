# BAJUS Gold & Silver Price API

A production-ready REST API that scrapes BAJUS (Bangladesh Jewellers' Association) gold and silver
prices from [bajushub.com](https://bajushub.com/) every 10 minutes and exposes them as a
metered, API-key-authenticated service — ready to sell to jewellery websites.

---

## Pricing

| Plan          | Monthly | Annual | Requests/month | Burst limit   |
|---------------|---------|--------|----------------|---------------|
| **Free**      | Free    | Free   | 200            | 5 req/min     |
| **Starter** ⭐ | $6/mo   | $60/yr | 10,000         | 30 req/min    |
| **Pro**       | $25/mo  | $240/yr| 100,000        | 120 req/min   |
| **Enterprise**| Custom  | Custom | 1,000,000      | 300 req/min   |

Self-serve signup: `POST /v1/billing/checkout` — customers pay via Stripe and receive their
API key by email automatically, with no manual step required.

---

## API Endpoints

Base URL: `https://api.bajusprices.com/v1`  
Auth: `Authorization: Bearer <your_api_key>` header on every request.

### Prices

| Endpoint | Plan | Description |
|---|---|---|
| `GET /prices/gold/latest` | All | Latest BAJUS gold buy price (all karats) |
| `GET /prices/gold/latest?karat=22k` | All | Single karat filter |
| `GET /prices/silver/latest` | All | Latest silver price |
| `GET /prices/latest` | All | **Gold + silver in one call** (best for jewellery widgets) |
| `GET /prices/convert?metal=gold&karat=22k&unit=vori&qty=1` | Starter+ | Unit conversion |
| `GET /prices/history?metal=gold&karat=22k` | Starter+ | Historical price series |

### Meta

| Endpoint | Description |
|---|---|
| `GET /meta/usage` | Your current-month usage vs. quota |

### Billing (public, no auth)

| Endpoint | Description |
|---|---|
| `GET /billing/plans` | List all plans with pricing |
| `POST /billing/checkout` | Create a Stripe Checkout Session (self-serve signup) |

---

## Quick Start (for jewellery website integration)

### JavaScript / Next.js

```js
// Display live gold price on your product pages
async function fetchGoldPrice() {
  const res = await fetch(
    'https://api.bajusprices.com/v1/prices/gold/latest',
    { headers: { Authorization: 'Bearer YOUR_API_KEY' } }
  );
  const data = await res.json();
  // data.prices => { "22k": 19970, "21k": 19075, "18k": 16380, "sanaton": 13380 }
  return data.prices;
}
```

### Both Gold & Silver in One Call

```js
const res = await fetch(
  'https://api.bajusprices.com/v1/prices/latest',
  { headers: { Authorization: 'Bearer YOUR_API_KEY' } }
);
const { gold, silver, as_of, stale } = await res.json();
```

### Python (backend integration)

```python
import httpx

API_KEY = "gsp_live_your_key_here"
BASE_URL = "https://api.bajusprices.com/v1"


def get_gold_price():
    r = httpx.get(
        f"{BASE_URL}/prices/gold/latest",
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    r.raise_for_status()
    return r.json()["prices"]  # {"22k": 19970.00, "21k": 19075.00, ...}
```

### Example Response

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
  "cached": true,
  "stale": false
}
```

---

## Setup & Deployment

### Prerequisites

- Python 3.11+
- PostgreSQL (or use SQLite for local/zero-dependency mode)
- Redis (or use in-memory fallback for local dev)
- Playwright chromium (`playwright install chromium`)

### Local (Zero-Dependency Mode)

No Docker, no PostgreSQL, no Redis needed:

```bat
start-dev.bat
```

This sets `POSTGRES_HOST=sqlite` and `REDIS_HOST=memory` automatically.

### Docker (Production)

```bash
cp .env.example .env
# Edit .env with your real values
docker compose up -d
```

### Environment Variables

Copy `.env.example` to `.env` and fill in:

```env
# Required for production
POSTGRES_HOST=your-db-host
POSTGRES_PASSWORD=strong_password
REDIS_HOST=your-redis-host
ADMIN_SECRET=your_random_admin_secret   # protects /v1/admin/* endpoints

# Required for email delivery of API keys
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=noreply@yourdomain.com
SMTP_PASSWORD=your_app_password
ALERT_EMAIL_TO=you@yourdomain.com       # where scraper alerts go

# Required for self-serve billing
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_MONTHLY_PRICE_ID=price_1...      # $6/month price from Stripe dashboard
STRIPE_ANNUAL_PRICE_ID=price_1...       # $60/year price from Stripe dashboard

# Optional
ALERT_SLACK_WEBHOOK_URL=https://hooks.slack.com/...
```

---

## Stripe Setup (Self-Serve Sales)

### Step 1 — Create Products in Stripe Dashboard

1. Go to **Stripe Dashboard → Products → Add Product**
2. Create "BAJUS Price API — Starter (Monthly)": $6.00 / month, recurring
3. Create "BAJUS Price API — Starter (Annual)": $60.00 / year, recurring
4. Copy the **Price IDs** (e.g. `price_1ABC...`) into your `.env`

### Step 2 — Configure the Webhook

1. In Stripe Dashboard → **Developers → Webhooks → Add endpoint**
2. URL: `https://api.bajusprices.com/v1/admin/webhook/stripe`
3. Events to listen for:
   - `checkout.session.completed`
   - `customer.subscription.deleted`
   - `customer.subscription.updated`
4. Copy the **Webhook signing secret** (`whsec_...`) into `STRIPE_WEBHOOK_SECRET`

### Step 3 — Test with Stripe CLI

```bash
stripe listen --forward-to localhost:8000/v1/admin/webhook/stripe
stripe trigger checkout.session.completed
```

### Customer Flow

1. Customer visits `GET /v1/billing/plans` — sees pricing
2. Customer calls `POST /v1/billing/checkout` with their email
3. They're redirected to Stripe's hosted checkout page
4. Payment succeeds → webhook fires → API key issued → **key emailed automatically**
5. Customer copies key from email and starts making requests

---

## Admin Operations

All admin routes require `Authorization: Bearer <ADMIN_SECRET>`.

```bash
# Issue a key manually
curl -X POST https://api.bajusprices.com/v1/admin/keys \
  -H "Authorization: Bearer $ADMIN_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"owner_email":"customer@example.com","plan":"starter"}'

# List all keys
curl https://api.bajusprices.com/v1/admin/keys \
  -H "Authorization: Bearer $ADMIN_SECRET"

# Revoke a key
curl -X DELETE https://api.bajusprices.com/v1/admin/keys/42 \
  -H "Authorization: Bearer $ADMIN_SECRET"

# View usage for a key
curl https://api.bajusprices.com/v1/admin/keys/42/usage \
  -H "Authorization: Bearer $ADMIN_SECRET"
```

---

## API Key Rotation

To rotate a customer's key:

1. Issue a new key via `POST /v1/admin/keys`
2. Email the new key to the customer
3. Revoke the old key via `DELETE /v1/admin/keys/{id}` after a grace period

---

## Architecture

```
Scheduler (every 10 min)
    ↓
Playwright Scraper (bajushub.com)
    ↓
Normalizer (Bangla digits → Decimal, sanity check)
    ↓
PostgreSQL (price_snapshots history)  ←→  Redis (latest price cache)
    ↓
FastAPI REST API
  /v1/prices/*     — authenticated, cache-first reads
  /v1/meta/*       — usage metering
  /v1/billing/*    — public self-serve checkout
  /v1/admin/*      — admin key management + Stripe webhook
```

**Reliability features:**
- Cache-first: API reads never trigger live scrapes — decouples uptime from bajushub.com
- `"stale": true` flag if data is >60 minutes old instead of returning 500
- Price anomaly detection: holds values >15% different from last for manual review
- Slack + email alert after 3 consecutive scraper failures

---

## Interactive Docs

Available at `https://api.bajusprices.com/docs` (Swagger UI) and `/redoc` (ReDoc).

---

## Legal Note

Prices are sourced from BAJUS (Bangladesh Jewellers' Association) via bajushub.com.
All API responses include `"source": "BAJUS via bajushub.com"`. Please scrape
politely (10-minute intervals, as configured) and display source attribution in
your product.
