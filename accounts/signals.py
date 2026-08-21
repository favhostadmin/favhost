from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in)
def flag_profile_modal_on_login(sender, request, user, **kwargs):
    """
    One-shot: show the "complete your profile" popup on the next page this
    user renders. Hooked into the signal (rather than each login view) so it
    fires for every login path — the password form, Google/Firebase sign-in,
    and any future one — without having to remember to wire each of them up.

    Set here rather than before `django.contrib.auth.login()` runs, because
    that call can flush or cycle the session, which would silently drop a
    flag written beforehand. The signal fires after that's all settled.
    """
    request.session['show_profile_complete_modal'] = True
