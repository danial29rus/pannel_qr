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

For a new independent reserve server, follow [the deployment guide in Russian](DEPLOYMENT_RU.md). It covers DNS, Docker, separate secrets/database, HTTPS, backup, verification, and deliberate activation of payment processing. The installer renders Nginx hosts from `.env.production`; it does not use the historical hardcoded domain configs.

On the new server, fill `.env.production` from `.env.production.example`, then run `sudo bash scripts/install-production.sh`. Keep `COMPOSE_PROFILES` empty for standby; use `processing` when the dedicated worker should process this installation's payments. Existing workers must be explicitly stopped before disabling that profile. The API remains available in standby.

Do not apply the reserve example env to the existing installation: changing `COMPOSE_PROJECT_NAME` selects a different PostgreSQL volume. Keep the existing server's settings, DNS and provider webhooks unchanged. A reserve deployment is independent; automatic failover and database replication are not configured.

See [HonestPlay connection instructions](INTEGRATION_HONESTPLAY_RU.md) for the partner adapter, durable UUID retries, polling, and hosted checkout limitations.

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

The synthetic-buyer seeder creates UUID users, unique logins, human-readable names, companies, non-routable Russian-format phone numbers and optional support threads. Email domains are varied for the interface (`gmail.localhost`, `yandex.localhost`, `outlook.localhost`, etc.), but all end in the reserved local `.localhost` zone, so they are not real mailbox addresses. It neither sends email nor creates payments. In production it requires the deliberate `--allow-production` flag.

To generate 10,000 users and 1,200 conversations:

```bash
docker compose exec api python -m app.scripts.seed_demo --users 10000 --conversations 1200 --namespace demo-october
```

For a production buyer pool without support conversations:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec api \
  python -m app.scripts.seed_demo --users 30000 --conversations 0 \
  --namespace buyer-pool-20261002 --email-domain clients.localhost \
  --batch-size 1000 --allow-production
```

`--namespace` must be new on every additional run because email and Telegram login are unique. Open the Support page at `http://localhost:15173` to view the generated dialogues. For a small preview, omit the arguments (it creates 200 users and 40 conversations).

To refresh a generated batch with the newer identity fields without creating another 10,000 rows:

```bash
docker compose exec api python -m app.scripts.seed_demo --namespace demo-october-2026 --refresh-namespace
```

Mailpit is a local SMTP inbox: enable it with `SMTP_ENABLED=true` in `.env`, then operator replies are delivered to the local inbox at `http://localhost:18025`; no mail leaves the machine. SMTP does not create mailboxes. Do not use public third-party recipient domains for generated data.

## Integrating the processing platform

For a PayGateCore-compatible merchant QR request, call `POST /api/v1/transactions/qr` with `Authorization: Bearer <project external token>` and this minimal body:

```json
{
  "amount": "100",
  "currency": "RUB",
  "merchant_transaction_id": "merchant-order-123"
}
```

The endpoint resolves the project from the token, selects one random active buyer with an email from the panel pool, creates the payment through the project's configured route, and returns the direct NSPK QR `payment_url`. Reusing the same `merchant_transaction_id` is idempotent.

The processor documentation was not attached yet, so the actual external calls are intentionally represented by `DemoProcessorAdapter`. Replace it with an adapter in `app/payments/adapters/` and register it in `app/payments/registry.py`. The adapter must implement `create_payment`, `get_payment`, `parse_webhook`, and `verify_webhook`; all provider credentials stay in the `payment_providers` configuration, preferably encrypted by the deployment secret manager.

### Nova AI test provider

Create a provider with `adapter_type: "nova"`. Put the Nova API token in `credentials_encrypted`, not `settings`:

```json
{
  "credentials_encrypted": {"token": "NOVA_TOKEN"},
  "settings": {"user_id": 1}
}
```

For a merchant QR request, the incoming `merchant_transaction_id` must be a UUID. It is passed to Nova unchanged as `transaction_id`; the panel returns Nova's direct `qr_url` when it is available. If Nova only returns a supported `go.pay.hot` checkout URL, the adapter reads its PayHot checkout session with the fragment token and returns `next_action.value` when it is a direct NSPK QR URL. Nova payments are checked by the existing background poller. `user_id: 1` is a temporary test recipient: every successful payment credits that Nova account.

Before enabling a real processor, decide its authentication, signature scheme, currencies, payout/refund states, and whether a limit is reserved at creation or only at success. These are supported at the domain boundary, but need the provider's actual contract.

MulenPay is registered as the `mulenpay` adapter. Its create-payment request includes the selected user's email only in the MulenPay-specific `client` field; the adapter rejects creation with HTTP 422 when that user has no email. Other adapters do not receive this field unless they explicitly declare the same requirement. The email is not copied into `transactions.extra` or the provider-attempt audit payload.

## Routing and balancing

Create a route with `POST /api/v1/projects/{project_id}/provider-routes`. When `provider_code` is omitted in a new transaction, the balancer chooses an active route that is inside its work window and has enough daily/weekly capacity. It prefers lower `priority`, then the least-used eligible route, then a higher weight. Use `PUT /api/v1/provider-routes/{route_id}` to update its time window, amount range and daily/weekly amount and payment-count limits; use `PATCH /api/v1/provider-routes/{route_id}/activation` to switch it on or off without deleting its limits.

## Payment trace for integrations

`GET /api/v1/transactions/{transaction_id}/trace` gives an operator one ordered, read-only history of the payment: the request from the external platform, local payment creation, each provider request and response, provider webhook, state changes, and final callback attempts back to the platform. The panel's **Журнал платежей** opens this trace by clicking a payment; technical request/response payloads stay collapsed until needed.
