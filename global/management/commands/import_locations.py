import openpyxl
from django.core.management.base import BaseCommand
from ...models import Country, State

class Command(BaseCommand):
    help = 'Imports countries and states data from an Excel file'

    FILE_PATH = 'countries_and_states.xlsx'

    def handle(self, *args, **options):
        file_path = self.FILE_PATH

        try:
            # Load the workbook and select the active sheet
            wb = openpyxl.load_workbook(file_path)
            sheet = wb.active

            # Extract header and find column indices
            header = [cell.value for cell in sheet[1]]
            try:
                idx_country_name = header.index('country_name')
                idx_country_code = header.index('country_code')
                idx_country_short = header.index('country_short')
                idx_state_name = header.index('state_name')
                idx_state_code = header.index('state_code')
            except ValueError as e:
                self.stdout.write(self.style.ERROR(f"Error: Missing required column in Excel sheet: {e}"))
                return

            records_processed = 0
            for row in sheet.iter_rows(min_row=2, values_only=True):
                # Skip empty rows
                if not any(row):
                    continue

                c_name = row[idx_country_name]
                c_code = row[idx_country_code]
                c_short = row[idx_country_short]
                s_name = row[idx_state_name]
                s_code = row[idx_state_code]

                # Get or create Country based on the name
                country, _ = Country.objects.get_or_create(
                    name=c_name,
                    defaults={
                        'code': str(c_code) if c_code is not None else '',
                        'short': str(c_short) if c_short is not None else ''
                    }
                )

                # Get or create State associated with the Country
                if s_name:
                    State.objects.get_or_create(
                        country=country,
                        name=s_name,
                        defaults={'code': str(s_code) if s_code is not None else ''}
                    )
                
                records_processed += 1

            self.stdout.write(self.style.SUCCESS(f"Successfully imported data from {records_processed} rows."))

        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f"Error: File not found at path '{file_path}'"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"An unexpected error occurred: {e}"))
