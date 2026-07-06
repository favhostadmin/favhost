#!/usr/bin/env python
"""
Standalone script to import countries_and_states.xlsx into the
shared.CountryAndState model.

Usage:
    python import_countries_states.py
"""
import os
import sys

import django

if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bookaid.settings')
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    django.setup()

    from django.core.management import call_command
    call_command('import_countries_states')
