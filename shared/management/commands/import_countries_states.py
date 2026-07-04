import openpyxl
from django.core.management.base import BaseCommand

from shared.models import CountryAndState


class Command(BaseCommand):
    help = 'Imports country/state data from countries_and_states.xlsx into shared.CountryAndState'

    FILE_PATH = 'countries_and_states.xlsx'

    def handle(self, *args, **options):
        try:
            wb = openpyxl.load_workbook(self.FILE_PATH, read_only=True)
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f"Error: File not found at path '{self.FILE_PATH}'"))
            return

        sheet = wb.active
        rows = sheet.iter_rows(values_only=True)
        header = next(rows)

        try:
            idx_country_name = header.index('country_name')
            idx_country_code = header.index('country_code')
            idx_country_short = header.index('country_short')
            idx_state_name = header.index('state_name')
            idx_state_code = header.index('state_code')
        except ValueError as e:
            self.stdout.write(self.style.ERROR(f"Error: Missing required column in Excel sheet: {e}"))
            return

        entries = []
        for row in rows:
            if not any(row):
                continue
            entries.append(CountryAndState(
                country_name=row[idx_country_name] or '',
                country_code=row[idx_country_code],
                country_short=row[idx_country_short],
                state_name=row[idx_state_name],
                state_code=row[idx_state_code],
            ))

        CountryAndState.objects.all().delete()
        CountryAndState.objects.bulk_create(entries, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(f"Successfully imported {len(entries)} rows."))
