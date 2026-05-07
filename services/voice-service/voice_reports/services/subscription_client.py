"""
Subscription service client.

Enforces workspace voice limits before processing uploads.
"""

import logging

import requests
from django.conf import settings

try:  # pragma: no cover
    from bi_platform_shared.http import HttpClientError, get_default_client
    _SHARED_CLIENT_AVAILABLE = True
except Exception:  # pragma: no cover
    HttpClientError = Exception  # type: ignore[assignment,misc]
    _SHARED_CLIENT_AVAILABLE = False

logger = logging.getLogger(__name__)


class SubscriptionClient:
    def __init__(self):
        self.base_url = getattr(settings, 'SUBSCRIPTION_SERVICE_URL', 'http://subscription-service:8008').rstrip('/')
        self.check_access_endpoint = f'{self.base_url}/check-access/'

    def check_access(self, workspace_id, authorization_header=None, consume=True):
        headers = {}
        if authorization_header:
            headers['Authorization'] = authorization_header

        params = {
            'workspace_id': workspace_id,
            'consume': str(bool(consume)).lower(),
        }

        try:
            if _SHARED_CLIENT_AVAILABLE:
                response = get_default_client().get(
                    self.check_access_endpoint,
                    params=params,
                    headers=headers,
                    timeout=(5.0, 15.0),
                    attach_internal_api_key=False,
                )
            else:
                response = requests.get(
                    self.check_access_endpoint,
                    params=params,
                    headers=headers,
                    timeout=(5, 15),
                )
        except HttpClientError as exc:  # type: ignore[misc]
            logger.error('Subscription check access failed workspace=%s error=%s', workspace_id, exc)
            return {
                'success': False,
                'error': f'subscription_service_unavailable: {exc}',
            }
        except requests.RequestException as exc:
            logger.error('Subscription check access failed workspace=%s error=%s', workspace_id, exc)
            return {
                'success': False,
                'error': f'subscription_service_unavailable: {exc}',
            }

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if response.status_code != 200:
            return {
                'success': False,
                'error': payload.get('message') or payload.get('error') or f'http_{response.status_code}',
            }

        if not payload.get('success'):
            return {
                'success': False,
                'error': payload.get('message') or payload.get('error') or 'subscription_check_failed',
            }

        return {
            'success': True,
            'allowed': bool(payload.get('allowed')),
            'remaining_requests': int(payload.get('remaining_requests', 0)),
            'limit': int(payload.get('limit', 0)),
            'used_requests': int(payload.get('used_requests', 0)),
            'is_subscribed': bool(payload.get('is_subscribed', False)),
            'message': payload.get('message', ''),
        }


_subscription_client = None


def get_subscription_client():
    global _subscription_client
    if _subscription_client is None:
        _subscription_client = SubscriptionClient()
    return _subscription_client
