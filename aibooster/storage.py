"""Private storage for Photo Enhancer files.

On a real server this is the project's default storage — the private S3 bucket
(no public ACL, presigned access only). On a local checkout the default storage
is MEDIA_ROOT, which runtime DEBUG serves publicly at /media/, so we use a
separate directory outside MEDIA_ROOT instead. Either way, files are only ever
handed out through the session-checked views in views.py.
"""
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, default_storage


def get_storage():
    if getattr(settings, 'AWS_STORAGE_BUCKET_NAME', None):
        return default_storage
    return FileSystemStorage(location=str(settings.BASE_DIR / 'private_media'), base_url=None)


def new_key(job_id, kind, ext):
    """Unguessable key: the random token means a job id alone can't be used to derive it."""
    return f'aibooster/{job_id}/{kind}-{uuid.uuid4().hex}.{ext}'


def save_bytes(key, data):
    return get_storage().save(key, ContentFile(data))


def read_bytes(key):
    with get_storage().open(key, 'rb') as fh:
        return fh.read()
