"""Signed, guest-facing links to property documents.

Check-in / check-out instruction emails link to the host's documents. Those links
cannot point at ``document.url`` directly: on a real server media lives in a
*private* S3 bucket, so ``.url`` is a presigned link that expires after
``AWS_QUERYSTRING_EXPIRE`` (1 hour). The email is generated at the property's
local midnight, so by the time the guest opens it the link would already be dead.

Instead the email carries a permanent signed token; resolving it (see
``property.views.open_document``) mints a fresh presigned URL at *click* time.
Lives in its own module so ``booking.tasks`` can sign a token without importing
``property.views``.
"""
from django.core.signing import TimestampSigner

DOCUMENT_LINK_SALT = 'property.document.open'
DOCUMENT_LINK_MAX_AGE = 180 * 24 * 60 * 60  # 180 days — comfortably outlives a stay


def _signer():
    return TimestampSigner(salt=DOCUMENT_LINK_SALT)


def sign_document_token(document_id):
    """Opaque token identifying a PropertyDocument in a guest-facing URL."""
    return _signer().sign(str(document_id))


def unsign_document_token(token):
    """Return the document id in `token`, or raise BadSignature/SignatureExpired."""
    return _signer().unsign(token, max_age=DOCUMENT_LINK_MAX_AGE)
