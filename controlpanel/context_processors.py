"""Template context for the owner console.

(This module previously held the impersonation context processor, which was
removed in 2026-07 — the console shows all host data read-only instead.)
"""
from .access import console_role, allowed_sections, is_console_owner


def console_identity(request):
    """Expose the viewer's console role and section grants to every template.

    ``base.html`` needs both: the sidebar badge says "Owner" or "Co-admin", and
    each nav link is hidden unless the viewer holds that section. A base
    template used by every page can't be fed from individual views.

    Hiding a link is presentation only — ``section_required`` on each view is
    what actually stops access.

    Returns an empty dict outside ``/console/`` so the host-facing site never
    pays for the queries.
    """
    if not request.path.startswith('/console'):
        return {}
    return {
        'console_role': console_role(request.user),
        'is_console_owner': is_console_owner(request.user),
        'allowed_sections': allowed_sections(request.user),
    }
