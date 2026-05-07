import logging
import os

import requests
from bi_platform_shared.http import HttpClientError, get_default_client
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .routing import resolve_target

logger = logging.getLogger(__name__)
UPSTREAM_TIMEOUT_SECONDS = int(os.getenv("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "360"))


class HealthView(View):
    def get(self, request):
        return JsonResponse({"success": True, "service": "api-gateway"})


@method_decorator(csrf_exempt, name="dispatch")
class ProxyView(View):
    http_method_names = ["get", "post", "put", "patch", "delete", "options"]

    def dispatch(self, request, *args, **kwargs):
        path = request.path
        target = resolve_target(path)

        if not target:
            return JsonResponse(
                {
                    "success": False,
                    "message": "No upstream service route found for this path.",
                },
                status=404,
            )

        query_string = request.META.get("QUERY_STRING", "")
        target_url = f"{target.base_url}{path}"
        if query_string:
            target_url = f"{target_url}?{query_string}"

        headers = {}
        for key, value in request.headers.items():
            lower = key.lower()
            if lower in {"host", "content-length", "connection"}:
                continue
            headers[key] = value

        try:
            upstream = get_default_client().request(
                method=request.method,
                url=target_url,
                data=request.body if request.body else None,
                headers=headers,
                timeout=(min(10.0, float(UPSTREAM_TIMEOUT_SECONDS)), float(UPSTREAM_TIMEOUT_SECONDS)),
                attach_internal_api_key=False,
                allow_redirects=False,
            )
        except HttpClientError as exc:
            logger.error(
                "Gateway upstream request failed path=%s target=%s error=%s",
                path,
                target.service,
                exc,
            )
            return JsonResponse(
                {
                    "success": False,
                    "message": f"Upstream service {target.service} unavailable.",
                },
                status=502,
            )
        except requests.RequestException as exc:
            logger.error(
                "Gateway upstream request failed path=%s target=%s error=%s",
                path,
                target.service,
                exc,
            )
            return JsonResponse(
                {
                    "success": False,
                    "message": f"Upstream service {target.service} unavailable.",
                },
                status=502,
            )

        response = HttpResponse(content=upstream.content, status=upstream.status_code)

        excluded_headers = {"content-encoding", "transfer-encoding", "connection"}
        for key, value in upstream.headers.items():
            if key.lower() in excluded_headers:
                continue
            response[key] = value

        return response
