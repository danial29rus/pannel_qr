#!/usr/bin/env bash
# Rotate only the panel password and signed sessions. PostgreSQL is untouched.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[[ -f .env.production ]] || { echo ".env.production not found" >&2; exit 1; }
chmod 600 .env.production
python3 - .env.production <<'PY'
import base64, hashlib, os, re, secrets, sys, getpass
path = sys.argv[1]
password = getpass.getpass("New panel password (hidden): ")
repeat = getpass.getpass("Repeat password: ")
if password != repeat: raise SystemExit("Passwords do not match")
if len(password) < 8: raise SystemExit("Password must contain at least 8 characters")
salt = os.urandom(16)
digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
hash_value = "scrypt$" + base64.urlsafe_b64encode(salt).rstrip(b"=").decode() + "$" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
text = open(path).read()
def put(name, value, quoted=False):
    global text
    quote = "'" if quoted else ""
    line = f"{name}={quote}{value}{quote}"
    text = re.sub(rf"^{re.escape(name)}=.*$", line, text, flags=re.M) if re.search(rf"^{re.escape(name)}=.*$", text, re.M) else text.rstrip()+"\n"+line+"\n"
put("PANEL_ADMIN_PASSWORD_HASH", hash_value, True)
put("PANEL_SESSION_SECRET", secrets.token_hex(32))
open(path, "w").write(text)
PY

docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate api
echo "Password and all existing panel sessions were reset."
