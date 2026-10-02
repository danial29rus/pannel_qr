#!/usr/bin/env sh
# Run locally or directly on the staging server; it prints secrets but does not
# write files, preventing accidental replacement of a working production env.
set -eu

# Hex avoids reserved URL characters in DATABASE_URL and is safe in .env files.
random() { openssl rand -hex 32; }
password_hash() {
  python3 -c 'import base64, hashlib, os, getpass; p=getpass.getpass("Panel password: ").encode(); s=os.urandom(16); d=hashlib.scrypt(p,salt=s,n=2**14,r=8,p=1); print("scrypt$"+base64.urlsafe_b64encode(s).rstrip(b"=").decode()+"$"+base64.urlsafe_b64encode(d).rstrip(b"=").decode())'
}

printf 'POSTGRES_PASSWORD=%s\n' "$(random)"
printf 'ADMIN_TOKEN=%s\n' "$(random)"
printf 'OPERATOR_TOKEN=%s\n' "$(random)"
printf 'VIEWER_TOKEN=%s\n' "$(random)"
printf 'PANEL_SESSION_SECRET=%s\n' "$(random)"
printf "PANEL_ADMIN_PASSWORD_HASH='%s'\n" "$(password_hash)"
