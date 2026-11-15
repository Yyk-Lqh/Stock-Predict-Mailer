"""Compatible public mail API backed by the shared MailCore implementation."""
from ..mail_core import MailCore


class MailService(MailCore):
    """Preserve the existing constructor and queue API during staged migration."""
