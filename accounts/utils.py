from .models import CoHost


def get_visible_user_ids(user):
    """Return list of user IDs whose data this user can access.

    A user can see:
    1. Their own data
    2. Data belonging to any host who has added them as a co-host
    3. Data belonging to any co-host they have added (as a host)
    """
    if not user or not user.is_authenticated:
        return []
    ids = {user.id}
    # Hosts who added this user as co-host (co-host sees host's data)
    host_ids = CoHost.objects.filter(co_host=user).values_list('host_id', flat=True)
    ids.update(host_ids)
    # Co-hosts that this user added as host (host sees co-host's data)
    cohost_ids = CoHost.objects.filter(host=user).values_list('co_host_id', flat=True)
    ids.update(cohost_ids)
    return list(ids)


def get_effective_user(user):
    """Return the user that should be used as the 'owner' for all operations.

    If the current user is a co-host, returns the host user instead.
    All data creation (properties, tasks, etc.) will be attributed to this user.
    """
    if not user or not user.is_authenticated:
        return user
    host = CoHost.objects.filter(co_host=user).select_related('host').first()
    if host:
        return host.host
    return user
