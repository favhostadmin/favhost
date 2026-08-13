#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "${PROJECT_ROOT}"

if [[ -f "requirements.txt" ]]; then
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
fi
# python manage.py makemigrations --noinput
# python manage.py collectstatic --noinput

python manage.py migrate --noinput

# Guarantee the /console/ owner account exists on every boot. Idempotent, and
# it never touches an existing password, so it is safe to run on production.
python manage.py create_platform_admin

exec python manage.py runserver 0.0.0.0:8000
