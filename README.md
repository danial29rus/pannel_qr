# Payments Control Panel

Backend and compact dashboard for payment operations. The project is deliberately built around an adapter boundary: a new payment processor is added without changing transaction, limit, audit, or support-chat logic.

## Run

```bash
docker compose up --build
```

Open the React dashboard at `http://localhost:15173`, API documentation at `http://localhost:18080/docs`, and PostgreSQL locally at `127.0.0.1:55432`.
Defaults are development-only; create `.env` from `.env.example` to override them.

For a domain, use [the Nginx template](deploy/nginx/panel.conf.example), replace `panel.example.com`, add TLS, and keep the frontend/API bound to the local non-standard ports `15173`/`18080`.

## Production deployment

Production uses the server's Nginx, PostgreSQL volumes, a separate worker, and Alembic migrations. Copy `.env.production.example` to `.env.production` on the server, generate long secrets, point both DNS A records to the server, then run:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

`panel.workkit-studio.ru` serves the dashboard; `api.workkit-studio.ru` exposes the API/webhook host. Install the two supplied Nginx site templates, then issue their certificates with Certbot. The migration container runs `alembic upgrade head` before API and worker start. Never use `down`, `rm -v`, or a new volume name on a production update: the `postgres_data` Docker volume contains the audit trail and payment data.

Generate a password hash locally without placing the plaintext password in the environment:

```bash
python -c 'import base64, hashlib, os, getpass; p=getpass.getpass().encode(); s=os.urandom(16); print("scrypt$"+base64.urlsafe_b64encode(s).rstrip(b"=").decode()+"$"+base64.urlsafe_b64encode(hashlib.scrypt(p,salt=s,n=2**14,r=8,p=1)).rstrip(b"=").decode())'
```

Put that value into `PANEL_ADMIN_PASSWORD_HASH`. The panel login issues a time-limited signed session; API automation may use the separate `ADMIN_TOKEN`, `OPERATOR_TOKEN`, or `VIEWER_TOKEN` headers.

Generate production secrets with `sh scripts/generate-secrets.sh`; it prints values and never overwrites an existing env file.

After filling the non-password production values, run `sudo bash scripts/install-production.sh`. It prompts twice for the panel password without putting it into shell history, rotates the signed-session secret, builds the stack, installs the two Nginx hosts, validates Nginx, and asks Certbot for both certificates. DNS must already point at the server.

Schedule one daily database backup on the server (and copy this directory to off-server storage):

```bash
0 3 * * * cd /srv/pannel_qr && BACKUP_DIR=/var/backups/clearpay sh scripts/backup-postgres.sh >> /var/log/clearpay-backup.log 2>&1
```

Test a backup before relying on it: `pg_restore --list /var/backups/clearpay/panel-<timestamp>.dump`.

`frontend/Dockerfile` is a production multi-stage React build served by Nginx; `frontend/Dockerfile.dev` is used by Compose for hot reload locally.

## What is already included

- PostgreSQL entities for users (name, Telegram, business, registration date), projects, providers, transactions, transaction events, limits, support conversations/messages, products, orders, and external catalogue sources.
- Immutable transaction-event audit trail. The transaction row stores the latest state; its history is never overwritten.
- Idempotent transaction creation (`Idempotency-Key` header).
- Daily/monthly/all-time limit validation which counts transactions that reserve or consume funds.
- `PaymentAdapter` protocol and `DemoProcessorAdapter`, including webhook signature verification hook. Production adapters receive only their processor-specific code.
- Dashboard aggregation API matching the shown turnover / credited / margin style.
- Project payment routes: enable/disable each connected payment system, define min/max payment amount, a work-time window, daily/weekly turnover and transaction quotas, priority, and balancing weight.
- `/api/v1/analytics/projects` returns every project with its financial and operational limits plus live daily/weekly usage for each provider route.

## WorkKit catalogue from SQLite

The panel can copy products and variants from a WorkKit SQLite file directly into its own PostgreSQL database. The source database is always opened read-only; checkout uses the copied product snapshot, so it continues working if the source file is unavailable later.

For local development, the supplied override mounts the WorkKit backend folder read-only:

```bash
docker compose -f docker-compose.yml -f docker-compose.workkit.local.yml up --build
```

Create a source after creating its panel project (the path is inside the API container):

```json
POST /api/v1/catalog-sources
{
  "project_id": "<project UUID>",
  "code": "workkit-main",
  "name": "WorkKit SQLite",
  "adapter_type": "workkit_sqlite",
  "settings": {
    "db_path": "/catalogs/workkit-market/workkit.db",
    "currency": "RUB"
  }
}
```

Run `POST /api/v1/catalog-sources/{source_id}/sync` to upsert WorkKit variants by SKU. Each variant becomes a panel product with its actual price, name and active state. The adapter supports the WorkKit `products` and `product_variants` schema only.

The provided `workkit-market-final` directory currently contains no SQLite database file: its Docker configuration uses PostgreSQL, while SQLite is only a local default. Put a legitimate `workkit.db` export into `backend/` or provide the authorised PostgreSQL connection details before the first sync.

Use only genuine catalogue positions, cart lines, delivery, taxes, and documented discounts when producing an order amount. The panel intentionally does not create fictitious products merely to reach a requested payment total.

## Demo users and visible support conversations

The development-only seeder creates UUID users, unique logins, human-readable names, companies, non-routable Russian-format phone numbers and readable Russian support threads. Email domains are varied for the interface (`gmail.localhost`, `yandex.localhost`, `outlook.localhost`, etc.), but all end in the reserved local `.localhost` zone, so they are not real mailbox addresses. It neither sends email nor creates real payments. It refuses to run outside `ENVIRONMENT=development` or `test`.

To generate 10,000 users and 1,200 conversations:

```bash
docker compose exec api python -m app.scripts.seed_demo --users 10000 --conversations 1200 --namespace demo-october
```

`--namespace` must be new on every additional run because email and Telegram login are unique. Open the Support page at `http://localhost:15173` to view the generated dialogues. For a small preview, omit the arguments (it creates 200 users and 40 conversations).

To refresh a generated batch with the newer identity fields without creating another 10,000 rows:

```bash
docker compose exec api python -m app.scripts.seed_demo --namespace demo-october-2026 --refresh-namespace
```

Mailpit is a local SMTP inbox: enable it with `SMTP_ENABLED=true` in `.env`, then operator replies are delivered to the local inbox at `http://localhost:18025`; no mail leaves the machine. SMTP does not create mailboxes. Do not use public third-party recipient domains for generated data.

## Integrating the processing platform

The processor documentation was not attached yet, so the actual external calls are intentionally represented by `DemoProcessorAdapter`. Replace it with an adapter in `app/payments/adapters/` and register it in `app/payments/registry.py`. The adapter must implement `create_payment`, `get_payment`, `parse_webhook`, and `verify_webhook`; all provider credentials stay in the `payment_providers` configuration, preferably encrypted by the deployment secret manager.

Before enabling a real processor, decide its authentication, signature scheme, currencies, payout/refund states, and whether a limit is reserved at creation or only at success. These are supported at the domain boundary, but need the provider's actual contract.

MulenPay is registered as the `mulenpay` adapter. Its create-payment request includes the selected user's email only in the MulenPay-specific `client` field; the adapter rejects creation with HTTP 422 when that user has no email. Other adapters do not receive this field unless they explicitly declare the same requirement. The email is not copied into `transactions.extra` or the provider-attempt audit payload.

## Routing and balancing

Create a route with `POST /api/v1/projects/{project_id}/provider-routes`. When `provider_code` is omitted in a new transaction, the balancer chooses an active route that is inside its work window and has enough daily/weekly capacity. It prefers lower `priority`, then the least-used eligible route, then a higher weight. Use `PATCH /api/v1/provider-routes/{route_id}/activation` to switch a route on or off without deleting its limits.
