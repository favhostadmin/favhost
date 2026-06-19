#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "${PROJECT_ROOT}"

if [[ -f "requirements.txt" ]]; then
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
fi
# python manage.py makemigrations --noinput
python manage.py migrate --noinput

exec python manage.py runserver 0.0.0.0:8000
