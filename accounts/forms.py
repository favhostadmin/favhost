from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError


class BlockAwareAuthenticationForm(AuthenticationForm):
    """Distinguishes a control-panel block from a generic inactive account,
    so the login view can show a branded "you've been blocked" popup instead
    of Django's default message."""

    def confirm_login_allowed(self, user):
        if not user.is_active:
            raise ValidationError('This account has been blocked.', code='blocked')
        super().confirm_login_allowed(user)
