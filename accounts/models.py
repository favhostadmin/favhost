from django.db import models
from django.contrib.auth.models import BaseUserManager, AbstractBaseUser
from django.utils import timezone
from django.urls import reverse
import uuid
import pytz
from django.utils.crypto import get_random_string


class MyUserManager(BaseUserManager):
    def create_user(self, username, email, password=None):
        if not username:
            raise ValueError('Users must have an username')
        if not email:
            raise ValueError('Users must have an email address')
        user = self.model(
            username=username,
            email=self.normalize_email(email),
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, password):
        user = self.create_user(username, email, password)
        user.is_admin = True
        user.is_staff = True
        user.is_superuser = True
        user.save(using=self._db)
        return user

# Create your models here.
class MyUser(AbstractBaseUser):
    username   = models.CharField(max_length=255, unique=True)
    email      = models.EmailField(max_length=255, unique=True, null=True, blank=True)
    first_name = models.CharField(max_length=255, null=True, blank=True, help_text="Only for Admin")
    last_name  = models.CharField(max_length=255, null=True, blank=True, help_text="Only for Admin")
    phone      = models.CharField(max_length=255, null=True, blank=True)
    # message    = models.TextField(null=True, blank=True)

    # Address
    country = models.CharField(max_length=100, null=True, blank=True)
    state = models.CharField(max_length=100, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    street_address = models.CharField(max_length=200, null=True, blank=True)
    zip = models.CharField(max_length=20, null=True, blank=True)

    # Currency
    currency = models.CharField(max_length=10, default='USD', help_text="Preferred currency for transactions")

    # Profile Picture
    profile_picture = models.ImageField(upload_to='profile_pictures/', null=True, blank=True)

    # Unique identifier for public host profile URLs
    public_uuid = models.UUIDField(default=uuid.uuid4, null=True, editable=True)
    short_code = models.CharField(max_length=20, unique=True, null=True, blank=True, help_text="Unique alphanumeric code for public URLs")

    # Social urls
    instagram_url = models.URLField(max_length=1000, null=True, blank=True)
    facebook_url = models.URLField(max_length=1000, null=True, blank=True)
    youtube_url = models.URLField(max_length=1000, null=True, blank=True)
    whatsapp_number = models.CharField(max_length=20, null=True, blank=True)

    # About me section
    about_me = models.TextField(null=True, blank=True)


    is_active  = models.BooleanField(default=True)
    is_admin   = models.BooleanField(default=False, help_text="Designates whether the user can log into this admin panel and perform all types of actions.")
    is_staff   = models.BooleanField(default=False, help_text="Designates whether the user can log into this admin panel.")
    created_by = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='created_by_user')
    updated_by = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='updated_by_user')
    timezone = models.CharField(max_length=63, default='America/New_York', help_text="User's timezone for date/time calculations")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # === NEW FIELDS ADDED BELOW (custom additions beyond original HR code) ===
    linkedin_url = models.URLField(max_length=1000, null=True, blank=True)
    twitter_url = models.URLField(max_length=1000, null=True, blank=True)
    language = models.CharField(max_length=100, default='English', null=True, blank=True)
    is_subscription_free = models.BooleanField(default=False, help_text="If enabled, user gets free access without requiring subscription payment")
    # Set True after the one-time "trial ending in 7 days" email is sent,
    # so a trial user only ever receives that reminder once.
    trial_ending_email_sent = models.BooleanField(default=False)
    # Free-trial length (days) captured at signup from PlatformSetting, so that
    # changing the platform-wide trial length later only affects NEW accounts.
    trial_days = models.PositiveIntegerField(default=90, help_text="This account's free-trial length in days (set at signup).")

    objects = MyUserManager()

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']

    def __str__(self):
        return str(self.username)

    def save(self, *args, **kwargs):
        # Generate a unique public_uuid if it's missing or already taken by another user
        if not self.public_uuid or MyUser.objects.filter(public_uuid=self.public_uuid).exclude(pk=self.pk).exists():
            while True:
                temp_uuid = uuid.uuid4()
                if not MyUser.objects.filter(public_uuid=temp_uuid).exists():
                    self.public_uuid = temp_uuid
                    break

        # Generate a unique alphanumeric short_code if missing
        if not self.short_code:
            while True:
                code = get_random_string(length=12)
                if not MyUser.objects.filter(short_code=code).exists():
                    self.short_code = code
                    break

        # On first save (new signup), capture the current platform-wide trial
        # length so later changes to the setting don't affect this account.
        if self._state.adding:
            try:
                from billing.models import PlatformSetting
                self.trial_days = PlatformSetting.load().free_trial_days
            except Exception:
                pass  # keep the field default (90) if settings aren't ready

        super().save(*args, **kwargs)

    def get_local_date(self):
        """Get today's date in the user's local timezone"""
        try:
            tz = pytz.timezone(self.timezone)
            return timezone.now().astimezone(tz).date()
        except:
            # Fallback to UTC if timezone is invalid
            return timezone.now().date()

    def has_perm(self, perm, obj=None):
        return True
    
    def has_module_perms(self, app_label):
        return True

    def get_all_permissions(self, obj=None):
        return []
    
    def get_timezone(self):
        """Return user's timezone object"""
        try:
            return pytz.timezone(self.timezone)
        except (pytz.exceptions.UnknownTimeZoneError, AttributeError):
            return pytz.timezone('America/New_York')
    
    def get_local_now(self):
        """Return current date/time in user's timezone"""
        user_tz = self.get_timezone()
        return timezone.now().astimezone(user_tz)
    
    def get_local_date(self):
        """Return today's date in user's timezone"""
        return self.get_local_now().date()

    def is_profile_complete(self):
        """Check if user profile is complete"""
        required_fields = [self.first_name, self.last_name, self.email, self.phone, self.country, self.state]
        return all(field is not None and field != '' for field in required_fields)

    def get_full_name(self):
        """Return user's full name"""
        return f"{self.first_name} {self.last_name}".strip()
    
    def get_short_name(self):
        """Return user's short name"""
        return self.first_name

    
    def get_full_address(self):
        """Return user's full address as a single string"""
        parts = [self.street_address, self.city, self.state, self.country, self.zip]
        return ', '.join(part for part in parts if part)

    def get_public_profile_url(self):
        """Return the public profile URL path using the short_code"""
        if self.short_code:
            return reverse('public_profile', kwargs={'short_code': self.short_code})
        return None

    @property
    def profile_picture_url(self):
        """Safely return profile picture URL, or None if file missing."""
        try:
            if self.profile_picture and self.profile_picture.name:
                return self.profile_picture.url
        except (ValueError, FileNotFoundError):
            pass
        return None


class CoHost(models.Model):
    host = models.ForeignKey(MyUser, on_delete=models.CASCADE, related_name='host_cohosts')
    co_host = models.ForeignKey(MyUser, on_delete=models.CASCADE, related_name='co_host_relationships')
    display_password = models.CharField(max_length=255, null=True, blank=True, help_text="Plain text password for UI display only")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('host', 'co_host')

    def __str__(self):
        return f"{self.co_host.get_full_name() or self.co_host.email} (co-host of {self.host.get_full_name() or self.host.email})"


class UserDocument(models.Model):
    DOCUMENT_TYPES = [
        ('govt_id', 'Government ID'),
        ('permission', 'Local Authority Permission'),
    ]
    user = models.ForeignKey(MyUser, on_delete=models.CASCADE, related_name='documents')
    document = models.FileField(upload_to='user_documents/')
    doc_type = models.CharField(max_length=50, choices=DOCUMENT_TYPES)
    name = models.CharField(max_length=255, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.get_doc_type_display()} - {self.name or self.document.name}"

