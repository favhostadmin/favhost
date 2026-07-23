# Intentionally empty.
#
# This module previously held the impersonation ("Login as host") context
# processor. Impersonation was removed from the owner console because it is
# invasive (entering a host's private session) and redundant — the console
# already surfaces all of a host's data read-only. Kept as a placeholder so no
# stale import path lingers; not referenced by settings.
