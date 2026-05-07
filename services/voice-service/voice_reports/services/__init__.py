"""Active voice-service helpers.

Per CRIT-04 the local SQLGuard was removed from voice-service: SQL safety
is enforced exclusively inside query-service via ``/query/validate/``.

Per CRIT-12 ``small_whisper_client`` was renamed to ``ai_service_client``
and ``SmallWhisperClient`` was renamed to ``AIServiceClient``. The previous
module is gone — every import has been migrated.
"""

from .ai_service_client import AIServiceClient, get_ai_service_client
from .subscription_client import SubscriptionClient, get_subscription_client

__all__ = [
    "AIServiceClient",
    "get_ai_service_client",
    "SubscriptionClient",
    "get_subscription_client",
]
