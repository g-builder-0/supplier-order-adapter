# supplier-order-adapter

HackFW: MADE Challenge submission — **Supplier Relationship Management** track.

A Django REST Framework service that keeps a supplier graph, an order line's receiving status, and a webhook-driven status feed as one living system. A part can have several suppliers (different lead time, price, and certification level), and this makes that relationship queryable, keeps order-line state current as receiving events come in, and publishes status changes outward over a signed webhook — instead of three separate spreadsheets that drift out of sync.

## What's here

- **Knowledge graph** of suppliers, parts, and certifications — "who else can supply this part, and at what lead time/price/certification level" — answered with plain `select_related` queries (no N+1s; verified via Hunter trace, see below).
- **Receiving workflow** — recording a receiving event against an order line, inside a transaction, recomputing that line's received quantity and status (`pending` → `partial`/`received`/`flagged`).
- **Webhook dispatcher** — after a receiving event commits, an HMAC-SHA256-signed `order_line.*` event is POSTed to a subscriber URL, outside the DB transaction so a slow/down subscriber never holds a lock open.
- **Minimal demo UI** (`/demo/`) — a self-contained page to submit a receiving event and watch the order line's status and the webhook delivery log update live, without needing a separate frontend or a second terminal.

## Setup

Requires Python 3.12+ and a clone of this repo.

```bash
git clone https://github.com/g-builder-0/supplier-order-adapter.git
cd supplier-order-adapter
python -m venv .venv
.venv\Scripts\activate        # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
```

### Environment variables

Copy `.env.example` to `.env` and fill in real values:

```bash
cp .env.example .env
```

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Django's secret key. Generate one, don't reuse the example. |
| `DJANGO_DEBUG` | `True` for local/demo use. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hosts, e.g. `localhost,127.0.0.1`. |
| `WEBHOOK_SECRET` | Shared secret used to HMAC-sign outgoing webhook payloads. |
| `WEBHOOK_SUBSCRIBER_URL` | Where receiving-event webhooks get POSTed. For the demo UI, point this at this same server's own webhook receiver: `http://127.0.0.1:8000/api/demo/webhook-receiver/`. |

### Database and seed data

```bash
python manage.py migrate
python manage.py seed_demo_data
```

`seed_demo_data` is idempotent (`get_or_create`/`update_or_create` throughout) — running it more than once won't create duplicates. It creates 5 suppliers, 10 parts, 21 supplier↔part coverage rows (with varying lead time, certification level, and unit price), and 3 purchase orders with order lines.

### Run it

```bash
python manage.py runserver
```

Then open **http://127.0.0.1:8000/demo/** in a browser — this is the easiest way to see the whole system end to end in one place: submit a receiving event, watch the order line's status update, and watch the webhook delivery log (polled every 2 seconds) confirm the signed webhook arrived and verified.

## Key API endpoints

| Method & path | What it does |
|---|---|
| `POST /api/receiving-events/` | Record a receiving event against an order line; recomputes that line's status and dispatches a signed webhook. |
| `GET /api/parts/<sku>/suppliers/` | Every supplier for a given part, with lead time, certification level, and price — "who else could supply this." |
| `GET /api/suppliers/<pk>/certifications/` | Every part a given supplier is certified/able to provide. |
| `GET /api/demo/webhook-log/` | Last 20 webhook deliveries received (demo-only; backs the `/demo/` page's live log). |
| `POST /api/demo/webhook-receiver/` | Demo-only webhook subscriber endpoint — verifies the HMAC signature and logs the delivery. |

## How this was built

Each phase was built, then traced end-to-end with [Hunter](https://github.com/ionelmc/python-hunter) (a Python execution tracer) to verify what the code was actually doing — in particular, confirming `select_related` queries produce one SQL JOIN rather than an N+1 pattern. The trace scripts live in `tracing/`. The resulting trace write-ups (one per phase, with a per-file purpose/input/output companion doc) are linked from the project's trace index.

## Notes for a judge or reviewer

- `db.sqlite3` and `.env` are gitignored — nothing sensitive is in this repo.
- No authentication is enforced (`AllowAny` throughout) — this is a working prototype, not a hardened production surface.
- The webhook subscriber used in the demo is this same app's own `/api/demo/webhook-receiver/` endpoint, standing in for a real external subscriber — the signing/dispatch/verification logic itself is the same code that would run against any real subscriber URL.
