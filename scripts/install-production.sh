#!/usr/bin/env bash
# First installation on the NEW server only. Other application servers are not modified.
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
[[ "${EUID}" -eq 0 ]] || { echo "Run with sudo: sudo bash scripts/install-production.sh" >&2; exit 1; }
[[ -f .env.production ]] || { cp .env.production.example .env.production; chmod 600 .env.production; echo "Fill .env.production, then run again." >&2; exit 1; }
chmod 600 .env.production
set -a
source ./.env.production
set +a
required=(COMPOSE_PROJECT_NAME POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD ADMIN_TOKEN OPERATOR_TOKEN VIEWER_TOKEN PANEL_DOMAIN ACME_EMAIL)
for name in "${required[@]}"; do
  value="${!name:-}"
  if [[ -z "$value" || "$value" == *generate-a-* || "$value" == *replace-with* || "$value" == *example.com* ]]; then
    echo "Set a real value for $name in .env.production." >&2; exit 1
  fi
done
DEPLOY_MODE="${DEPLOY_MODE:-standalone-nginx}"
PROXY_NETWORK="${PROXY_NETWORK:-vitrina_proxy}"
[[ "$DEPLOY_MODE" == caddy-shared || "$DEPLOY_MODE" == standalone-nginx ]] || { echo "DEPLOY_MODE must be caddy-shared or standalone-nginx" >&2; exit 1; }
export DEPLOY_MODE PROXY_NETWORK
[[ "$COMPOSE_PROJECT_NAME" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || { echo "Invalid COMPOSE_PROJECT_NAME" >&2; exit 1; }
API_DOMAIN="${API_DOMAIN:-$PANEL_DOMAIN}"
export API_DOMAIN
[[ "$PANEL_DOMAIN" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ && "$PANEL_DOMAIN" == *.* ]] || { echo "Invalid panel domain" >&2; exit 1; }
if [[ "$DEPLOY_MODE" == standalone-nginx ]]; then
  for domain in "$PANEL_DOMAIN" "$API_DOMAIN"; do
    [[ "$domain" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ && "$domain" == *.* ]] || { echo "Invalid domain" >&2; exit 1; }
    if [[ -e "/etc/nginx/sites-available/$domain" || -e "/etc/nginx/sites-enabled/$domain" ]]; then
      echo "Nginx host $domain already exists; first-install script refuses to overwrite it." >&2; exit 1
    fi
  done
fi
API_BIND_PORT="${API_BIND_PORT:-18180}"
PANEL_BIND_PORT="${PANEL_BIND_PORT:-15174}"
export API_BIND_PORT PANEL_BIND_PORT
[[ "$API_BIND_PORT" != "$PANEL_BIND_PORT" ]] || { echo "Local ports must differ" >&2; exit 1; }
for port in "$API_BIND_PORT" "$PANEL_BIND_PORT"; do
  [[ "$port" =~ ^[0-9]{2,5}$ && "$port" -gt 1024 && "$port" -le 65535 ]] || { echo "Invalid port" >&2; exit 1; }
  if ss -ltn "sport = :$port" | grep -q LISTEN; then
    echo "Local port $port is occupied; select another port." >&2; exit 1
  fi
done
commands=(docker python3)
if [[ "$DEPLOY_MODE" == standalone-nginx ]]; then commands+=(nginx certbot envsubst); fi
for command in "${commands[@]}"; do
  command -v "$command" >/dev/null || { echo "Install $command first." >&2; exit 1; }
done
docker compose version >/dev/null
python3 - .env.production <<'PY'
import base64, hashlib, os, re, secrets, sys, getpass

path = sys.argv[1]
password = getpass.getpass("New panel password (hidden): ")
repeat = getpass.getpass("Repeat password: ")
if password != repeat:
    raise SystemExit("Passwords do not match")
if len(password) < 8:
    raise SystemExit("Password must contain at least 8 characters")
if len(password) < 14:
    print("Warning: use a longer password after initial login.")
salt = os.urandom(16)
digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
password_hash = "scrypt$" + base64.urlsafe_b64encode(salt).rstrip(b"=").decode() + "$" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
session_secret = secrets.token_hex(32)
text = open(path).read()
def put(name, value, quoted=False):
    global text
    quote = "'" if quoted else ""
    line = f"{name}={quote}{value}{quote}"
    pattern = rf"^{re.escape(name)}=.*$"
    text = re.sub(pattern, line, text, flags=re.M) if re.search(pattern, text, re.M) else text.rstrip()+"\n"+line+"\n"
put("PANEL_ADMIN_PASSWORD_HASH", password_hash, True)
put("PANEL_SESSION_SECRET", session_secret)
open(path, "w").write(text)
PY

# Reload generated values: exported shell variables override Compose's --env-file.
set -a
source ./.env.production
set +a
API_DOMAIN="${API_DOMAIN:-$PANEL_DOMAIN}"
export API_DOMAIN

docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
if ! docker network inspect "$PROXY_NETWORK" >/dev/null 2>&1; then
  if [[ "$DEPLOY_MODE" == caddy-shared ]]; then
    echo "Docker network $PROXY_NETWORK is missing. Start the Vitrina Compose stack first." >&2; exit 1
  fi
  docker network create "$PROXY_NETWORK" >/dev/null
fi
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
for attempt in {1..30}; do
  if curl -fsS "http://127.0.0.1:$API_BIND_PORT/ready" >/dev/null; then break; fi
  if [[ "$attempt" -eq 30 ]]; then echo "API failed readiness; inspect compose logs." >&2; exit 1; fi
  sleep 2
done
if [[ "$DEPLOY_MODE" == standalone-nginx ]]; then
  for name in panel api; do
    if [[ "$name" == api && "$API_DOMAIN" == "$PANEL_DOMAIN" ]]; then continue; fi
    if [[ "$name" == panel ]]; then domain="$PANEL_DOMAIN"; else domain="$API_DOMAIN"; fi
    envsubst '${PANEL_DOMAIN} ${API_DOMAIN} ${API_BIND_PORT} ${PANEL_BIND_PORT}' < "deploy/nginx/$name.conf.template" > "/etc/nginx/sites-available/$domain"
    ln -s "/etc/nginx/sites-available/$domain" "/etc/nginx/sites-enabled/$domain"
  done
  nginx -t
  systemctl reload nginx
  cert_domains=(-d "$PANEL_DOMAIN")
  if [[ "$API_DOMAIN" != "$PANEL_DOMAIN" ]]; then cert_domains+=(-d "$API_DOMAIN"); fi
  certbot --nginx --non-interactive --agree-tos --email "$ACME_EMAIL" "${cert_domains[@]}"
  echo "Done. Open https://$PANEL_DOMAIN. Standby processing is controlled by COMPOSE_PROFILES."
else
  echo "Panel containers are running. Ensure Vitrina .env has PANEL_ADDRESS=$PANEL_DOMAIN, then run 'docker compose up -d caddy' in the Vitrina directory to enable HTTPS routing."
fi
