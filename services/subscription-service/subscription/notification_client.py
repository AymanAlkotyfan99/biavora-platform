"""Notification service client (subscription-service).

GAP-05 / CRIT-10: see ``voice-service.voice_reports.services.notification_client``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import requests

try:  # pragma: no cover
    from bi_platform_shared.http import HttpClientError, get_default_client
    _SHARED_CLIENT_AVAILABLE = True
except Exception:  # pragma: no cover
    HttpClientError = Exception  # type: ignore[assignment,misc]
    _SHARED_CLIENT_AVAILABLE = False

logger = logging.getLogger(__name__)


class NotificationClient:
    def __init__(self) -> None:
        self.base_url = os.getenv('NOTIFICATION_SERVICE_URL', 'http://notification-service:8010').rstrip('/')
        self.api_key = os.getenv('NOTIFICATION_SERVICE_API_KEY', '').strip()
        self.events_endpoint = f'{self.base_url}/notification/events/'

    def send_event(self, *, event_type: str, payload: Dict[str, Any], event_key: str = '') -> Dict[str, Any]:
        headers: Dict[str, str] = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['X-Internal-Api-Key'] = self.api_key

        request_body = {
            'event_type': event_type,
            'event_key': event_key,
            'payload': payload,
        }

        try:
            response = self._post(self.events_endpoint, json=request_body, headers=headers)
        except HttpClientError as exc:  # type: ignore[misc]
            logger.error(
                'Notification service request failed event_type=%s key=%s error=%s',
                event_type,
                event_key,
                exc,
            )
            return {'success': False, 'error': str(exc)}
        except requests.RequestException as exc:
            logger.error(
                'Notification service request failed event_type=%s key=%s error=%s',
                event_type,
                event_key,
                exc,
            )
            return {'success': False, 'error': str(exc)}

        if response.status_code != 200:
            logger.error(
                'Notification service returned non-200 event_type=%s key=%s status=%s body=%s',
                event_type,
                event_key,
                response.status_code,
                response.text[:500],
            )
            return {'success': False, 'error': f'http_{response.status_code}'}

        try:
            data: Dict[str, Any] = response.json()
        except ValueError:
            data = {'success': False}

        if not data.get('success'):
            return {'success': False, 'error': data.get('message', 'notification_event_failed')}

        return {'success': True, 'data': data}

    def _post(self, url: str, *, json: Any, headers: Dict[str, str]):
        if _SHARED_CLIENT_AVAILABLE:
            client = get_default_client()
            return client.post(
                url,
                json=json,
                headers=headers,
                timeout=(5.0, 15.0),
                attach_internal_api_key=False,
            )
        return requests.post(url, json=json, headers=headers, timeout=(5, 15))


_notification_client: Optional[NotificationClient] = None


def get_notification_client() -> NotificationClient:
    global _notification_client
    if _notification_client is None:
        _notification_client = NotificationClient()
    return _notification_client
