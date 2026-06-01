from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q

UserModel = get_user_model()

class EmailOrUsernameBackend(ModelBackend):
    """
    This is a custom authentication backend.
    It allows users to log in with either their username or their email address.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            # Try to fetch the user by looking up the username or email field
            user = UserModel.objects.get(Q(username__iexact=username) | Q(email__iexact=username))
        except UserModel.DoesNotExist:
            # Run the default password hasher once to reduce the timing
            # difference between a user not existing and a user existing
            # with an incorrect password.
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:
            return None # Don't authenticate if multiple users match

        if user.check_password(password) and self.user_can_authenticate(user):
            return user