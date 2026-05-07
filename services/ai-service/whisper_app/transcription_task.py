from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, Literal, Optional, TypedDict
from uuid import uuid4

import whisper

# Phase 12 / CRIT-19: imports for the legacy non-Dagster pipeline have been
# removed. The Dagster pipeline pulls these dependencies through its own
# asset modules.

try:
    import redis
    from redis.exceptions import RedisError
except ImportError:
    redis = None  # type: ignore[assignment]

    class RedisError(Exception):
        """Fallback RedisError when redis-py is not installed."""


ErrorType = Literal["system", "concurrency", "input", "model", "infra", "unknown"]
ActionType = Literal["retry", "wait", "stop"]


class TranscriptionResult(TypedDict):
    status: Literal["success", "failed"]
    text: str
    error_type: str
    action_taken: ActionType
    retry_count: int


class TranscriptionError(Exception):
    """Base exception for transcription step failures."""


class SystemResourceError(TranscriptionError):
    """Resource exhaustion (OOM/CPU pressure/temporary exhaustion)."""


class ConcurrencyError(TranscriptionError):
    """Queue, lock, or contention related error."""


class InputValidationError(TranscriptionError):
    """Input file quality/shape/format issue."""


class ModelError(TranscriptionError):
    """Model loading/inference/runtime issue."""


class ModelTimeoutError(ModelError):
    """Whisper inference timed out."""


class InfrastructureError(TranscriptionError):
    """Runtime infrastructure dependency issue."""


@dataclass(frozen=True)
class Decision:
    action: ActionType
    should_retry: bool
    wait_seconds: float = 0.0
    reload_model: bool = False


@dataclass(frozen=True)
class PipelineConfig:
    whisper_model_name: str
    whisper_cache_dir: str
    whisper_task: str
    redis_url: str
    queue_key: str
    lock_key: str
    result_prefix: str
    dedupe_prefix: str
    heartbeat_prefix: str
    enqueued_prefix: str
    queue_wait_timeout_seconds: int
    queue_poll_interval_seconds: float
    stale_job_seconds: int
    lock_ttl_seconds: int
    lock_renew_interval_seconds: int
    result_ttl_seconds: int
    inference_timeout_seconds: int
    base_backoff_seconds: float
    max_backoff_seconds: float
    max_system_retries: int
    max_model_retries: int
    max_concurrency_retries: int
    max_unknown_retries: int
    max_audio_file_size_mb: int

    @classmethod
    def from_env(cls) -> "PipelineConfig":
        return cls(
            whisper_model_name=os.getenv("WHISPER_MODEL_NAME", "large-v3"),
            whisper_cache_dir=os.getenv("WHISPER_CACHE_DIR", os.path.expanduser("~/.cache/whisper")),
            whisper_task=os.getenv("WHISPER_TASK", "transcribe"),
            redis_url=os.getenv("TRANSCRIPTION_REDIS_URL", os.getenv("REDIS_URL", "redis://localhost:6379/0")),
            queue_key=os.getenv("TRANSCRIPTION_QUEUE_KEY", "whisper:transcription:queue"),
            lock_key=os.getenv("TRANSCRIPTION_LOCK_KEY", "whisper:transcription:lock"),
            result_prefix=os.getenv("TRANSCRIPTION_RESULT_PREFIX", "whisper:transcription:result"),
            dedupe_prefix=os.getenv("TRANSCRIPTION_DEDUPE_PREFIX", "whisper:transcription:dedupe"),
            heartbeat_prefix=os.getenv("TRANSCRIPTION_HEARTBEAT_PREFIX", "whisper:transcription:heartbeat"),
            enqueued_prefix=os.getenv("TRANSCRIPTION_ENQUEUED_PREFIX", "whisper:transcription:enqueued"),
            queue_wait_timeout_seconds=_env_int("TRANSCRIPTION_QUEUE_WAIT_TIMEOUT_SECONDS", 900),
            queue_poll_interval_seconds=_env_float("TRANSCRIPTION_QUEUE_POLL_INTERVAL_SECONDS", 1.0),
            stale_job_seconds=_env_int("TRANSCRIPTION_STALE_JOB_SECONDS", 300),
            lock_ttl_seconds=_env_int("TRANSCRIPTION_LOCK_TTL_SECONDS", 180),
            lock_renew_interval_seconds=_env_int("TRANSCRIPTION_LOCK_RENEW_INTERVAL_SECONDS", 30),
            result_ttl_seconds=_env_int("TRANSCRIPTION_RESULT_TTL_SECONDS", 3600),
            inference_timeout_seconds=_env_int("TRANSCRIPTION_INFERENCE_TIMEOUT_SECONDS", 300),
            base_backoff_seconds=_env_float("TRANSCRIPTION_BACKOFF_BASE_SECONDS", 1.5),
            max_backoff_seconds=_env_float("TRANSCRIPTION_BACKOFF_MAX_SECONDS", 60.0),
            max_system_retries=_env_int("TRANSCRIPTION_MAX_SYSTEM_RETRIES", 4),
            max_model_retries=_env_int("TRANSCRIPTION_MAX_MODEL_RETRIES", 3),
            max_concurrency_retries=_env_int("TRANSCRIPTION_MAX_CONCURRENCY_RETRIES", 6),
            max_unknown_retries=_env_int("TRANSCRIPTION_MAX_UNKNOWN_RETRIES", 2),
            max_audio_file_size_mb=_env_int("TRANSCRIPTION_MAX_AUDIO_FILE_SIZE_MB", 500),
        )


@dataclass(frozen=True)
class TranscriptionRequest:
    audio_path: str
    request_id: str
    language: Optional[str] = None
    initial_prompt: Optional[str] = None


@dataclass
class LockLease:
    job_id: str
    token: str
    stop_event: threading.Event
    renew_thread: threading.Thread


# CRIT-11: single source of truth for the supported extension set lives in
# ``bi_platform_shared.audio.validation``. Both voice-service (gateway) and
# ai-service (Whisper inference) import from there so the gateway can never
# accept a file that the inner service silently rejects.
from bi_platform_shared.audio.validation import (
    SUPPORTED_AUDIO_EXTENSIONS as _SUPPORTED_AUDIO_EXTENSIONS,
)

_SYSTEM_HINTS = (
    "out of memory",
    "oom",
    "cuda out of memory",
    "cannot allocate memory",
    "resource temporarily unavailable",
    "resource exhausted",
    "cpu saturation",
    "cpu overloaded",
)

_CONCURRENCY_HINTS = (
    "model busy",
    "resource contention",
    "simultaneous request",
    "lock not acquired",
    "queue wait timeout",
)

_INPUT_HINTS = (
    "empty file",
    "unsupported format",
    "corrupt",
    "corrupted",
    "invalid data found when processing input",
    "could not decode",
    "audio file is empty",
)

_MODEL_HINTS = (
    "model not loaded",
    "inference timeout",
    "model crashed",
    "runtime crash",
    "decoder error",
    "failed to transcribe",
)

_INFRA_HINTS = (
    "ffmpeg",
    "file not found",
    "no such file or directory",
    "permission denied",
    "access is denied",
    "redis unavailable",
)

_ENQUEUE_SCRIPT = """
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2]) then
    redis.call('SET', KEYS[2], ARGV[3], 'EX', ARGV[2])
    redis.call('RPUSH', KEYS[3], ARGV[1])
    return 1
end
return 0
"""

_POP_HEAD_IF_MATCH_SCRIPT = """
if redis.call('LINDEX', KEYS[1], 0) == ARGV[1] then
    redis.call('LPOP', KEYS[1])
    return 1
end
return 0
"""

_RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

_RENEW_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_logger() -> logging.Logger:
    return logging.getLogger(__name__)


def _log_event(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    payload = {"timestamp": _utc_now(), **fields}
    logger.log(level, "%s | %s", message, json.dumps(payload, sort_keys=True, default=str))


def _build_request_id(audio_path: str) -> str:
    normalized_path = os.path.abspath(audio_path)
    try:
        stat = os.stat(normalized_path)
        source = f"{normalized_path}:{stat.st_size}:{int(stat.st_mtime)}"
    except OSError:
        source = normalized_path
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _exponential_backoff(retry_count: int, config: PipelineConfig) -> float:
    delay = config.base_backoff_seconds * (2 ** retry_count)
    return min(delay, config.max_backoff_seconds)


def classify_error(exception: BaseException) -> ErrorType:
    """
    Classify transcription errors for policy-based handling.
    """
    message = str(exception).lower()
    if isinstance(exception, (InfrastructureError, FileNotFoundError, PermissionError, RedisError)):
        return "infra"
    if isinstance(exception, InputValidationError):
        return "input"
    if isinstance(exception, (SystemResourceError, MemoryError)):
        return "system"
    if isinstance(exception, ConcurrencyError):
        return "concurrency"

    if any(hint in message for hint in _SYSTEM_HINTS):
        return "system"
    if any(hint in message for hint in _CONCURRENCY_HINTS):
        return "concurrency"
    if any(hint in message for hint in _INPUT_HINTS):
        return "input"
    if any(hint in message for hint in _MODEL_HINTS):
        return "model"
    if any(hint in message for hint in _INFRA_HINTS):
        return "infra"
    if isinstance(exception, (ModelError, ModelTimeoutError)):
        return "model"
    return "unknown"


def _decide_action(error_type: ErrorType, retry_count: int, config: PipelineConfig) -> Decision:
    if error_type == "input":
        return Decision(action="stop", should_retry=False)

    if error_type == "infra":
        return Decision(action="stop", should_retry=False)

    if error_type == "system":
        if retry_count < config.max_system_retries:
            return Decision(action="wait", should_retry=True, wait_seconds=_exponential_backoff(retry_count, config))
        return Decision(action="stop", should_retry=False)

    if error_type == "concurrency":
        if retry_count < config.max_concurrency_retries:
            return Decision(action="wait", should_retry=True, wait_seconds=_exponential_backoff(retry_count, config))
        return Decision(action="stop", should_retry=False)

    if error_type == "model":
        if retry_count < config.max_model_retries:
            return Decision(
                action="retry",
                should_retry=True,
                wait_seconds=_exponential_backoff(retry_count, config),
                reload_model=True,
            )
        return Decision(action="stop", should_retry=False)

    if retry_count < config.max_unknown_retries:
        return Decision(action="retry", should_retry=True, wait_seconds=_exponential_backoff(retry_count, config))
    return Decision(action="stop", should_retry=False)


def _validate_input(audio_path: str, config: PipelineConfig) -> None:
    if not audio_path or not audio_path.strip():
        raise InputValidationError("Empty file path.")

    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if not os.path.isfile(audio_path):
        raise InputValidationError(f"Input must be a file: {audio_path}")

    if not os.access(audio_path, os.R_OK):
        raise PermissionError(f"Permission denied when reading audio file: {audio_path}")

    file_size = os.path.getsize(audio_path)
    if file_size <= 0:
        raise InputValidationError("Audio file is empty.")

    max_size_bytes = config.max_audio_file_size_mb * 1024 * 1024
    if file_size > max_size_bytes:
        raise InputValidationError(
            f"Audio file size exceeds {config.max_audio_file_size_mb}MB limit."
        )

    extension = os.path.splitext(audio_path)[1].lower()
    if extension and extension not in _SUPPORTED_AUDIO_EXTENSIONS:
        raise InputValidationError(f"Unsupported audio format: {extension}")

    _validate_audio_stream_readability(audio_path)


def _validate_audio_stream_readability(audio_path: str) -> None:
    ffprobe_bin = shutil.which("ffprobe")
    if ffprobe_bin is None:
        raise InfrastructureError("ffprobe is missing from PATH.")

    command = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "json",
        audio_path,
    ]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    except subprocess.TimeoutExpired as exc:
        raise InputValidationError("Audio validation failed: ffprobe timed out while reading the file.") from exc
    except OSError as exc:
        raise InfrastructureError(f"ffprobe execution failed: {exc}") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        short_detail = detail.splitlines()[0][:240] if detail else "unknown ffprobe error"
        raise InputValidationError(f"Audio validation failed: ffprobe could not decode the file ({short_detail}).")

    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise InfrastructureError("Audio validation failed: ffprobe returned invalid JSON output.") from exc

    streams = payload.get("streams", []) if isinstance(payload, dict) else []
    has_audio_stream = any(
        isinstance(stream, dict) and str(stream.get("codec_type", "")).strip().lower() == "audio"
        for stream in streams
    )
    if not has_audio_stream:
        raise InputValidationError("Audio validation failed: file does not contain a readable audio stream.")


def _validate_infrastructure() -> None:
    if shutil.which("ffmpeg") is None:
        raise InfrastructureError("ffmpeg is missing from PATH.")


class WhisperModelManager:
    # Process-wide singleton model instance (lazy loaded, thread-safe).
    _shared_model: ClassVar[Any] = None
    _shared_model_name: ClassVar[Optional[str]] = None
    _shared_model_lock: ClassVar[threading.Lock] = threading.Lock()
    # Phase 13 / GAP-07: serialize Whisper inference — the openai-whisper
    # runtime is not safe for concurrent ``transcribe`` on one model.
    _inference_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, config: PipelineConfig, logger: logging.Logger) -> None:
        self._config = config
        self._logger = logger

    def _load_model(self) -> Any:
        started = time.perf_counter()
        try:
            model = whisper.load_model(
                self._config.whisper_model_name,
                download_root=self._config.whisper_cache_dir,
            )
        except Exception as exc:  # noqa: BLE001
            lowered = str(exc).lower()
            if any(hint in lowered for hint in _SYSTEM_HINTS):
                raise SystemResourceError(str(exc)) from exc
            raise ModelError(f"Model not loaded: {exc}") from exc

        _log_event(
            self._logger,
            logging.INFO,
            "Whisper model loaded",
            model=self._config.whisper_model_name,
            load_seconds=round(time.perf_counter() - started, 3),
        )
        return model

    def get_model(self) -> Any:
        model = self.__class__._shared_model
        model_name = self.__class__._shared_model_name
        if model is not None and model_name == self._config.whisper_model_name:
            return model

        # Critical section: only one thread may initialize/replace the singleton.
        with self.__class__._shared_model_lock:
            model = self.__class__._shared_model
            model_name = self.__class__._shared_model_name
            if model is None or model_name != self._config.whisper_model_name:
                model = self._load_model()
                self.__class__._shared_model = model
                self.__class__._shared_model_name = self._config.whisper_model_name
            return model

    def reload_model(self) -> None:
        with self.__class__._shared_model_lock:
            self.__class__._shared_model = None
            self.__class__._shared_model_name = None
            model = self._load_model()
            self.__class__._shared_model = model
            self.__class__._shared_model_name = self._config.whisper_model_name

    def transcribe(self, request: TranscriptionRequest) -> str:
        model = self.get_model()

        kwargs: Dict[str, Any] = {
            "task": self._config.whisper_task,
            "verbose": False,
        }
        if request.language:
            kwargs["language"] = request.language
        if request.initial_prompt:
            kwargs["initial_prompt"] = request.initial_prompt

        started = time.perf_counter()
        try:
            with self.__class__._inference_lock:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(model.transcribe, request.audio_path, **kwargs)
                    result = future.result(timeout=self._config.inference_timeout_seconds)
        except FutureTimeoutError as exc:
            raise ModelTimeoutError(
                f"Inference timeout after {self._config.inference_timeout_seconds}s."
            ) from exc
        except RuntimeError as exc:
            lowered = str(exc).lower()
            if any(hint in lowered for hint in _SYSTEM_HINTS):
                raise SystemResourceError(str(exc)) from exc
            raise ModelError(f"Model runtime crash: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ModelError(f"Failed to transcribe: {exc}") from exc

        text = str(result.get("text", "")).strip()
        _log_event(
            self._logger,
            logging.INFO,
            "Whisper transcription finished",
            request_id=request.request_id,
            inference_seconds=round(time.perf_counter() - started, 3),
            output_chars=len(text),
        )
        return text


class RedisTranscriptionQueue:
    def __init__(self, config: PipelineConfig, logger: logging.Logger) -> None:
        if redis is None:
            raise InfrastructureError("redis package is not installed.")

        self._config = config
        self._logger = logger

        try:
            self._client = redis.Redis.from_url(
                self._config.redis_url,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
                health_check_interval=30,
            )
            self._client.ping()
        except Exception as exc:  # noqa: BLE001
            raise InfrastructureError(f"Redis unavailable: {exc}") from exc

    def _result_key(self, job_id: str) -> str:
        return f"{self._config.result_prefix}:{job_id}"

    def _dedupe_key(self, job_id: str) -> str:
        return f"{self._config.dedupe_prefix}:{job_id}"

    def _heartbeat_key(self, job_id: str) -> str:
        return f"{self._config.heartbeat_prefix}:{job_id}"

    def _enqueued_key(self, job_id: str) -> str:
        return f"{self._config.enqueued_prefix}:{job_id}"

    def enqueue_once(self, job_id: str) -> bool:
        """
        Atomically enqueue only once using Redis SET NX + queue push.
        """
        try:
            inserted = self._client.eval(
                _ENQUEUE_SCRIPT,
                3,
                self._dedupe_key(job_id),
                self._enqueued_key(job_id),
                self._config.queue_key,
                job_id,
                str(self._config.result_ttl_seconds),
                str(time.time()),
            )
            return bool(inserted)
        except RedisError as exc:
            raise InfrastructureError(f"Redis enqueue failed: {exc}") from exc

    def wait_for_result(self, job_id: str, timeout_seconds: int) -> Optional[TranscriptionResult]:
        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            cached = self.get_cached_success_result(job_id)
            if cached is not None:
                return cached
            time.sleep(self._config.queue_poll_interval_seconds)
        return None

    def get_cached_success_result(self, job_id: str) -> Optional[TranscriptionResult]:
        """
        Idempotency gate:
        - Return cached result only for successful executions.
        - Failed outcomes are not cached to allow retry on later calls.
        """
        result_key = self._result_key(job_id)
        try:
            payload = self._client.get(result_key)
        except RedisError as exc:
            raise InfrastructureError(f"Redis read for idempotency failed: {exc}") from exc

        if not payload:
            return None

        try:
            parsed: Dict[str, Any] = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            _log_event(
                self._logger,
                logging.WARNING,
                "Invalid cached transcription payload; evicting key",
                job_id=job_id,
            )
            self._evict_cached_result_key(result_key=result_key, job_id=job_id)
            return None

        status = str(parsed.get("status", "")).lower()
        if status == "success":
            action_raw = str(parsed.get("action_taken", "stop"))
            action_taken: ActionType = "stop"
            if action_raw in ("retry", "wait", "stop"):
                action_taken = action_raw
            return {
                "status": "success",
                "text": str(parsed.get("text", "")),
                "error_type": str(parsed.get("error_type", "none")),
                "action_taken": action_taken,
                "retry_count": int(parsed.get("retry_count", 0)),
            }

        # Enforce "cache success only": purge stale failed payloads from older runs.
        self._evict_cached_result_key(result_key=result_key, job_id=job_id)
        return None

    def _evict_cached_result_key(self, result_key: str, job_id: str) -> None:
        try:
            self._client.delete(result_key)
        except RedisError as exc:
            _log_event(
                self._logger,
                logging.WARNING,
                "Failed to evict cached result key",
                job_id=job_id,
                error=str(exc),
            )

    def _recover_stale_head(self, head_job_id: str) -> None:
        if not head_job_id:
            return

        try:
            has_lock = bool(self._client.exists(self._config.lock_key))
            has_heartbeat = bool(self._client.exists(self._heartbeat_key(head_job_id)))
            if has_lock or has_heartbeat:
                return

            enqueued_at_raw = self._client.get(self._enqueued_key(head_job_id))
            enqueued_at = float(enqueued_at_raw) if enqueued_at_raw else 0.0
            age = time.time() - enqueued_at if enqueued_at > 0 else self._config.stale_job_seconds + 1
            if age < self._config.stale_job_seconds:
                return

            popped = self._client.eval(
                _POP_HEAD_IF_MATCH_SCRIPT,
                1,
                self._config.queue_key,
                head_job_id,
            )
            if popped:
                self._cleanup_job_keys(head_job_id)
                _log_event(
                    self._logger,
                    logging.WARNING,
                    "Recovered stale queued job",
                    stale_job_id=head_job_id,
                    age_seconds=round(age, 3),
                )
        except RedisError as exc:
            raise InfrastructureError(f"Stale recovery failed: {exc}") from exc

    def wait_for_turn(self, job_id: str, timeout_seconds: int) -> LockLease:
        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            try:
                head = self._client.lindex(self._config.queue_key, 0)
            except RedisError as exc:
                raise InfrastructureError(f"Queue read failed: {exc}") from exc

            if head is None:
                # Queue head disappeared unexpectedly; enforce retry behavior.
                raise ConcurrencyError("Queue wait timeout: no queued jobs found.")

            if head != job_id:
                self._recover_stale_head(head)
                time.sleep(self._config.queue_poll_interval_seconds)
                continue

            token = uuid4().hex
            try:
                acquired = bool(
                    self._client.set(
                        self._config.lock_key,
                        token,
                        nx=True,
                        ex=self._config.lock_ttl_seconds,
                    )
                )
            except RedisError as exc:
                raise InfrastructureError(f"Lock acquisition failed: {exc}") from exc

            if not acquired:
                time.sleep(self._config.queue_poll_interval_seconds)
                continue

            return self._start_lock_heartbeat(job_id, token)

        raise ConcurrencyError("Queue wait timeout while waiting for worker availability.")

    def _start_lock_heartbeat(self, job_id: str, token: str) -> LockLease:
        stop_event = threading.Event()
        heartbeat_key = self._heartbeat_key(job_id)
        self._client.set(heartbeat_key, "1", ex=self._config.lock_ttl_seconds)

        def _renew() -> None:
            while not stop_event.wait(self._config.lock_renew_interval_seconds):
                try:
                    renewed = self._client.eval(
                        _RENEW_LOCK_SCRIPT,
                        1,
                        self._config.lock_key,
                        token,
                        str(self._config.lock_ttl_seconds),
                    )
                    if int(renewed) != 1:
                        _log_event(
                            self._logger,
                            logging.ERROR,
                            "Lock renewal lost ownership",
                            job_id=job_id,
                        )
                        return
                    self._client.set(heartbeat_key, "1", ex=self._config.lock_ttl_seconds)
                except RedisError as exc:
                    _log_event(
                        self._logger,
                        logging.ERROR,
                        "Lock renewal failed",
                        job_id=job_id,
                        error=str(exc),
                    )

        renew_thread = threading.Thread(target=_renew, name=f"transcription-lock-renew-{job_id[:8]}", daemon=True)
        renew_thread.start()
        return LockLease(job_id=job_id, token=token, stop_event=stop_event, renew_thread=renew_thread)

    def complete_job(self, lease: LockLease) -> None:
        lease.stop_event.set()
        lease.renew_thread.join(timeout=2)

        try:
            self._client.eval(
                _POP_HEAD_IF_MATCH_SCRIPT,
                1,
                self._config.queue_key,
                lease.job_id,
            )
            self._cleanup_job_keys(lease.job_id)
            self._client.eval(_RELEASE_LOCK_SCRIPT, 1, self._config.lock_key, lease.token)
        except RedisError as exc:
            raise InfrastructureError(f"Failed to complete job cleanup: {exc}") from exc

    def abandon_job(self, job_id: str) -> None:
        """
        Best-effort cleanup for a queued job that never reached lock ownership.
        """
        try:
            self._client.lrem(self._config.queue_key, 0, job_id)
            self._cleanup_job_keys(job_id)
        except RedisError as exc:
            raise InfrastructureError(f"Failed to abandon queued job: {exc}") from exc

    def _cleanup_job_keys(self, job_id: str) -> None:
        self._client.delete(
            self._dedupe_key(job_id),
            self._heartbeat_key(job_id),
            self._enqueued_key(job_id),
        )

    def store_result(self, job_id: str, result: TranscriptionResult) -> None:
        payload = json.dumps(result)
        try:
            self._client.set(self._result_key(job_id), payload, ex=self._config.result_ttl_seconds)
        except RedisError as exc:
            raise InfrastructureError(f"Failed to store result in Redis: {exc}") from exc


def _build_success_result(text: str, retry_count: int) -> TranscriptionResult:
    return {
        "status": "success",
        "text": text,
        "error_type": "none",
        "action_taken": "stop",
        "retry_count": retry_count,
    }


def _build_failed_result(error_type: ErrorType, action_taken: ActionType, retry_count: int) -> TranscriptionResult:
    return {
        "status": "failed",
        "text": "",
        "error_type": error_type,
        "action_taken": action_taken,
        "retry_count": retry_count,
    }


class TranscriptionService:
    """
    Service layer owns execution semantics (retry, queueing, locking, idempotency).
    The orchestration layer should only coordinate this service.
    """

    def __init__(self, config: PipelineConfig, logger: logging.Logger) -> None:
        self._config = config
        self._logger = logger

    def execute(self, request: TranscriptionRequest) -> TranscriptionResult:
        return _execute_transcription(request, self._config, self._logger)


def _execute_transcription(request: TranscriptionRequest, config: PipelineConfig, logger: logging.Logger) -> TranscriptionResult:
    retry_count = 0
    try:
        queue = RedisTranscriptionQueue(config, logger)
    except Exception as exc:  # noqa: BLE001
        error_type = classify_error(exc)
        decision = _decide_action(error_type, retry_count, config)
        _log_event(
            logger,
            logging.ERROR,
            "Failed to initialize Redis queue for transcription",
            request_id=request.request_id,
            error_type=error_type,
            action_taken=decision.action,
            retry_count=retry_count,
            exception_type=type(exc).__name__,
            error=str(exc),
        )
        return _build_failed_result(error_type=error_type, action_taken=decision.action, retry_count=retry_count)

    model_manager = WhisperModelManager(config, logger)

    while True:
        lease: Optional[LockLease] = None
        is_owner = False
        try:
            # Idempotency short-circuit: same request_id returns same successful result with no reprocessing.
            cached = queue.get_cached_success_result(request.request_id)
            if cached is not None:
                _log_event(
                    logger,
                    logging.INFO,
                    "Idempotency cache hit; returning cached transcription",
                    request_id=request.request_id,
                    retry_count=retry_count,
                )
                return cached

            _validate_infrastructure()
            _validate_input(request.audio_path, config)

            is_owner = queue.enqueue_once(request.request_id)
            if not is_owner:
                cached = queue.wait_for_result(request.request_id, config.queue_wait_timeout_seconds)
                if cached is not None:
                    return cached
                raise ConcurrencyError("Model busy: duplicate request still in progress.")

            lease = queue.wait_for_turn(request.request_id, config.queue_wait_timeout_seconds)
            text = model_manager.transcribe(request)
            result = _build_success_result(text=text, retry_count=retry_count)
            queue.store_result(request.request_id, result)
            queue.complete_job(lease)
            lease = None

            _log_event(
                logger,
                logging.INFO,
                "Transcription succeeded",
                request_id=request.request_id,
                retry_count=retry_count,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            error_type = classify_error(exc)
            decision = _decide_action(error_type, retry_count, config)

            _log_event(
                logger,
                logging.ERROR,
                "Transcription attempt failed",
                request_id=request.request_id,
                error_type=error_type,
                action_taken=decision.action,
                retry_count=retry_count,
                exception_type=type(exc).__name__,
                error=str(exc),
            )

            if lease is not None:
                try:
                    queue.complete_job(lease)
                except Exception as cleanup_exc:  # noqa: BLE001
                    _log_event(
                        logger,
                        logging.ERROR,
                        "Failed to cleanup lock lease after error",
                        request_id=request.request_id,
                        error=str(cleanup_exc),
                    )
                finally:
                    lease = None
            elif is_owner:
                try:
                    queue.abandon_job(request.request_id)
                except Exception as cleanup_exc:  # noqa: BLE001
                    _log_event(
                        logger,
                        logging.ERROR,
                        "Failed to abandon queued job after error",
                        request_id=request.request_id,
                        error=str(cleanup_exc),
                    )

            if decision.reload_model:
                try:
                    model_manager.reload_model()
                    _log_event(logger, logging.INFO, "Whisper model reloaded after model error", request_id=request.request_id)
                except Exception as reload_exc:  # noqa: BLE001
                    _log_event(
                        logger,
                        logging.ERROR,
                        "Whisper model reload failed",
                        request_id=request.request_id,
                        error=str(reload_exc),
                    )

            if decision.should_retry:
                retry_count += 1
                if decision.wait_seconds > 0:
                    time.sleep(decision.wait_seconds)
                continue

            result = _build_failed_result(
                error_type=error_type,
                action_taken=decision.action,
                retry_count=retry_count,
            )
            # Cache only successful outputs to preserve idempotent retries after failure.
            _log_event(
                logger,
                logging.INFO,
                "Returning failed result without caching",
                request_id=request.request_id,
                error_type=error_type,
                retry_count=retry_count,
            )
            return result


def _attach_fn_compat(func):
    """
    Keep compatibility for existing call sites/tests that use Prefect's `.fn`.
    """
    setattr(func, "fn", func)
    return func


@_attach_fn_compat
def transcribe_audio_task(
    audio_path: str,
    request_id: Optional[str] = None,
    language: Optional[str] = None,
    initial_prompt: Optional[str] = None,
) -> TranscriptionResult:
    """
    Runtime transcription step: voice-to-text transcription using local Whisper model.
    """
    logger = _get_logger()
    config = PipelineConfig.from_env()
    effective_request_id = request_id or _build_request_id(audio_path)

    request = TranscriptionRequest(
        audio_path=audio_path,
        request_id=effective_request_id,
        language=language,
        initial_prompt=initial_prompt,
    )

    _log_event(
        logger,
        logging.INFO,
        "Starting transcription task",
        request_id=effective_request_id,
        audio_path=audio_path,
        model=config.whisper_model_name,
    )

    # Orchestrator coordinates only. Retry/queue/lock behavior is owned by the service layer.
    service = TranscriptionService(config=config, logger=logger)
    return service.execute(request)


def whisper_transcription_flow(
    audio_path: str,
    request_id: Optional[str] = None,
    language: Optional[str] = None,
    initial_prompt: Optional[str] = None,
) -> TranscriptionResult:
    """
    Dagster orchestration entrypoint for transcription only.
    """
    try:
        from dagster_pipeline.jobs import run_transcription_pipeline

        return run_transcription_pipeline(
            audio_path=audio_path,
            request_id=request_id,
            language=language,
            initial_prompt=initial_prompt,
        )
    except Exception as exc:  # noqa: BLE001
        logger = _get_logger()
        _log_event(
            logger,
            logging.ERROR,
            "Dagster transcription orchestration failed; using direct fallback",
            error=str(exc),
            audio_path=audio_path,
        )
        return transcribe_audio_task(
            audio_path=audio_path,
            request_id=request_id,
            language=language,
            initial_prompt=initial_prompt,
        )


# Phase 12 / CRIT-19: ``_run_legacy_whisper_transcription_preprocess_intent``
# was the non-Dagster fallback. It has been removed in favour of a single
# Dagster orchestration path. The stub below is intentionally left so any
# stale call site fails fast with a clear error instead of silently
# re-introducing the legacy code path.
def _run_legacy_whisper_transcription_preprocess_intent(
    *,
    audio_path: str,
    request_id: Optional[str],
    language: Optional[str],
    initial_prompt: Optional[str],
    user_id: Optional[str],
) -> dict[str, Any]:
    raise RuntimeError(
        "Legacy non-Dagster pipeline has been removed (Phase 12 / CRIT-19). "
        "Use whisper_transcription_preprocess_intent_flow which routes through "
        "the Dagster pipeline."
    )


def whisper_transcription_preprocess_intent_flow(
    audio_path: str,
    request_id: Optional[str] = None,
    language: Optional[str] = None,
    initial_prompt: Optional[str] = None,
    user_id: Optional[str] = None,
    manager_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    source_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    report_id: Optional[str] = None,
    table_name: Optional[str] = None,
) -> dict[str, Any]:
    """
    Dagster orchestration entrypoint for:
    transcription -> preprocessing_low -> intent_classification
    -> preprocessing_high -> intent_extraction -> routing/execution/downstream.

    Phase 12 / CRIT-19: the legacy non-Dagster fallback has been removed.
    There is exactly one pipeline; if it fails the request fails fast with
    a structured ``dagster_orchestration`` error rather than silently
    routing through a code path that no longer receives maintenance.
    """

    try:
        from dagster_pipeline.jobs import run_full_ai_pipeline

        return run_full_ai_pipeline(
            audio_path=audio_path,
            request_id=request_id,
            language=language,
            initial_prompt=initial_prompt,
            user_id=user_id,
            manager_id=manager_id,
            dataset_id=dataset_id,
            source_id=source_id,
            workspace_id=workspace_id,
            report_id=report_id,
            table_name=table_name,
        )
    except Exception as exc:  # noqa: BLE001
        logger = _get_logger()
        _log_event(
            logger,
            logging.ERROR,
            "Dagster full pipeline orchestration failed",
            error=str(exc),
            audio_path=audio_path,
        )
        return {
            "status": "failed",
            "stage": "dagster_orchestration",
            "message": "Dagster full pipeline orchestration failed.",
            "error_type": "system",
            "action_taken": "stop",
            "final_route": "stop",
            "final_user_message": "AI orchestration failed before analytical routing.",
            "debug_metadata": {"error": str(exc)},
        }


def full_audio_transcription(audio_bytes: bytes) -> str:
    """
    Backward-compatible helper that runs only the transcription step.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
        tmp_file.write(audio_bytes)
        tmp_audio_path = tmp_file.name

    try:
        result = whisper_transcription_flow(audio_path=tmp_audio_path)
        if result["status"] != "success":
            raise RuntimeError(
                f"Transcription failed: error_type={result['error_type']} "
                f"action_taken={result['action_taken']} "
                f"retry_count={result['retry_count']}"
            )
        return result["text"]
    finally:
        if os.path.exists(tmp_audio_path):
            os.remove(tmp_audio_path)
