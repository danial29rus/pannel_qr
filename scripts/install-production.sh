#!/usr/bin/env bash
# One-host production installer. Run as root from the project directory only
# after panel/api DNS records point to this server.
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo bash scripts/install-production.sh" >&2
  exit 1
fi

if [[ ! -f .env.production ]]; then
  cp .env.production.example .env.production
  echo "Created .env.production from template. Fill PostgreSQL/API secrets, then run this script again." >&2
  exit 1
fi

chmod 600 .env.production
required=(POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD ADMIN_TOKEN OPERATOR_TOKEN VIEWER_TOKEN PANEL_DOMAIN API_DOMAIN ACME_EMAIL)
set -a; source ./.env.production; set +a
for name in "${required[@]}"; do
  value="${!name:-}"
  if [[ -z "$value" || "$value" == *REPLACE_WITH* || "$value" == *replace-with* ]]; then
    echo "Set a real value for $name in .env.production before installation." >&2
    exit 1
  fi
done

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

for port in "${API_BIND_PORT:-18180}" "${PANEL_BIND_PORT:-15174}"; do
  if ss -ltn "sport = :$port" | grep -q LISTEN; then
    echo "Local port $port is already occupied; choose another value in .env.production." >&2
    exit 1
  fi
done

docker compose --env-file .env.production -f docker-compose.prod.yml config >/dev/null
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build

install -m 644 deploy/nginx/panel.workkit-studio.ru.conf /etc/nginx/sites-available/panel.workkit-studio.ru
install -m 644 deploy/nginx/api.workkit-studio.ru.conf /etc/nginx/sites-available/api.workkit-studio.ru
ln -sfn /etc/nginx/sites-available/panel.workkit-studio.ru /etc/nginx/sites-enabled/panel.workkit-studio.ru
ln -sfn /etc/nginx/sites-available/api.workkit-studio.ru /etc/nginx/sites-enabled/api.workkit-studio.ru
nginx -t
systemctl reload nginx

certbot --nginx -d "$PANEL_DOMAIN" -d "$API_DOMAIN"
echo "Done. Open https://$PANEL_DOMAIN and sign in with PANEL_ADMIN_USERNAME."
