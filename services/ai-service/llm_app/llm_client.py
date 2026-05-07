import os
import time

from openai import APIError, APITimeoutError, AuthenticationError, OpenAI, RateLimitError


OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-3n-e4b-it:free")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "http://localhost")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "BI Voice Agent")
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

client = OpenAI(
    base_url=OPENROUTER_BASE_URL,
    api_key=OPENROUTER_API_KEY,
    default_headers={
        "HTTP-Referer": OPENROUTER_SITE_URL,
        "X-Title": OPENROUTER_APP_NAME,
    },
)


def get_openrouter_diagnostics() -> dict[str, str | bool]:
    key = str(OPENROUTER_API_KEY or "").strip()
    return {
        "provider": "openrouter",
        "model": OPENROUTER_MODEL,
        "base_url": OPENROUTER_BASE_URL,
        "openrouter_key_present": bool(key),
        "openrouter_key_prefix": key[:6] if key else "",
    }


def call_llm(prompt: str, *, model: str | None = None, max_tokens: int = 500) -> str:
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY is not configured")

    delay_seconds = 1.0
    last_error: Exception | None = None

    for attempt in range(LLM_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=(model or OPENROUTER_MODEL),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("LLM returned an empty response")
            return content
        except AuthenticationError as exc:
            raise ValueError(
                f"OpenRouter key loaded but rejected by API | provider=openrouter model={(model or OPENROUTER_MODEL)} "
                f"base_url={OPENROUTER_BASE_URL} error={exc}"
            ) from exc
        except RateLimitError as exc:
            last_error = exc
            if attempt >= LLM_MAX_RETRIES:
                break
            time.sleep(delay_seconds)
            delay_seconds *= 2
        except APITimeoutError as exc:
            last_error = exc
            if attempt >= LLM_MAX_RETRIES:
                break
            time.sleep(delay_seconds)
            delay_seconds *= 2
        except APIError as exc:
            last_error = exc
            if attempt >= LLM_MAX_RETRIES:
                break
            time.sleep(delay_seconds)
            delay_seconds *= 2
        except Exception as exc:
            raise RuntimeError(f"LLM service error: {exc}") from exc

    if isinstance(last_error, RateLimitError):
        raise RuntimeError(f"LLM rate limit exceeded after retries: {last_error}") from last_error
    if isinstance(last_error, APITimeoutError):
        raise RuntimeError(f"LLM timeout after retries: {last_error}") from last_error
    if isinstance(last_error, APIError):
        raise RuntimeError(f"LLM API error after retries: {last_error}") from last_error
    raise RuntimeError("LLM call failed after retries")
