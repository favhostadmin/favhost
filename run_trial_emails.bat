@echo off
REM ============================================================
REM  Daily job: send the "your trial ends in 7 days" email to
REM  eligible trial users. Safe to run every day — each user is
REM  emailed only once (guarded by trial_ending_email_sent).
REM  Scheduled via Windows Task Scheduler (see setup steps).
REM ============================================================

cd /d "D:\Internship\favhost"
if not exist "logs" mkdir "logs"

"D:\Internship\favhost\venv\Scripts\python.exe" manage.py send_trial_ending_emails >> "logs\trial_emails.log" 2>&1
