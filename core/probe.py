"""Reaching a provider over HTTP: model lists, chat probes, health checks."""
from __future__ import annotations

from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request
from urllib.request import urlopen
import json
import time

from .auth import provider_api_key, resolve_api_key_value
from .catalog import fetch_models_url, metadata_from_remote

HTTP_USER_AGENT = "piswitch/1.0"


def fetch_remote_models(
    base_url: str,
    api_key: str,
    *,
    timeout: float = 20,
    opener=None,
    environ: dict[str, str] | None = None,
) -> list[dict]:
    url = fetch_models_url(base_url)
    parsed_url = urlsplit(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("base URL must be a valid http:// or https:// URL")

    request = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": HTTP_USER_AGENT,
    })
    token = resolve_api_key_value(api_key, environ)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with (opener or urlopen)(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise ValueError(f"authentication failed (HTTP {exc.code})") from exc
        raise ValueError(f"model endpoint returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise ValueError(f"cannot connect to model endpoint: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ValueError("model endpoint request timed out") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("model endpoint did not return valid JSON") from exc

    records = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(records, list) and isinstance(payload, dict):
        records = payload.get("models")
    if not isinstance(records, list):
        raise ValueError("model endpoint response does not contain a model list")

    models = []
    seen = set()
    for record in records:
        if isinstance(record, str):
            model_id, name = record, record
        elif isinstance(record, dict):
            model_id = record.get("id") or record.get("name")
            name = record.get("name") or model_id
        else:
            continue
        if isinstance(model_id, str) and model_id.strip() and model_id not in seen:
            entry = {"id": model_id, "name": name if isinstance(name, str) else model_id}
            # Carry real metadata through when the gateway reported any, so importing a
            # model does not have to fall back to placeholder numbers. Omitted when empty
            # to keep the common {id, name} shape unchanged.
            meta = metadata_from_remote(record) if isinstance(record, dict) else {}
            if meta:
                entry["meta"] = meta
            models.append(entry)
            seen.add(model_id)
    return models


ANTHROPIC_VERSION = "2023-06-01"


PROBE_PROMPT = "hi"


# api types whose chat endpoint piswitch can reach with only baseUrl + a bearer-ish key.
# vertex / bedrock / azure need service-account JSON, SigV4 signing, or a deployment name —
# none of which the provider form collects, so they keep the /v1/models probe instead.
CHAT_PROBE_APIS = (
    "openai-completions",
    "openai-responses",
    "anthropic-messages",
    "google-generative-ai",
)


def supports_chat_probe(api: str) -> bool:
    return api in CHAT_PROBE_APIS


def _v1_root(base: str) -> str:
    """Normalise a stored baseUrl to its `/v1` root.

    baseUrl is saved with or without the `/v1` suffix (fetch_models_url tolerates both),
    so endpoint composition has to tolerate both too.
    """
    root = (base or "").rstrip("/")
    if root.endswith("/models"):
        root = root[: -len("/models")]
    root = root.rstrip("/")
    if not root.endswith("/v1"):
        root += "/v1"
    return root


def build_chat_probe(api: str, base_url: str, model_id: str, token: str) -> tuple[str, dict, dict]:
    """Compose the (url, headers, body) of a minimal real completion request."""
    if not supports_chat_probe(api):
        raise ValueError(f'"{api}" 不支持对话探测，仅能测试模型列表接口')
    if not (isinstance(model_id, str) and model_id.strip()):
        raise ValueError("chat probe requires a model id")
    model_id = model_id.strip()
    headers = {"Accept": "application/json", "Content-Type": "application/json",
               "User-Agent": HTTP_USER_AGENT}

    if api == "anthropic-messages":
        headers["anthropic-version"] = ANTHROPIC_VERSION
        if token:
            headers["x-api-key"] = token
        return (f"{_v1_root(base_url)}/messages", headers, {
            "model": model_id,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": PROBE_PROMPT}],
        })

    if api == "google-generative-ai":
        # Key travels as a header, not ?key=, so it cannot leak through URL logging.
        if token:
            headers["x-goog-api-key"] = token
        root = (base_url or "").rstrip("/")
        for suffix in ("/v1beta", "/v1"):
            if root.endswith(suffix):
                root = root[: -len(suffix)]
                break
        return (f"{root.rstrip('/')}/v1beta/models/{model_id}:generateContent", headers, {
            "contents": [{"parts": [{"text": PROBE_PROMPT}]}],
            "generationConfig": {"maxOutputTokens": 1},
        })

    if token:
        headers["Authorization"] = f"Bearer {token}"
    if api == "openai-responses":
        return (f"{_v1_root(base_url)}/responses", headers, {
            "model": model_id,
            "input": PROBE_PROMPT,
            # OpenAI rejects max_output_tokens below 16, so 1 is not an option here.
            "max_output_tokens": 16,
        })
    return (f"{_v1_root(base_url)}/chat/completions", headers, {
        "model": model_id,
        "messages": [{"role": "user", "content": PROBE_PROMPT}],
        "max_tokens": 1,
        "stream": False,
    })


def probe_chat(
    base_url: str,
    api: str,
    model_id: str,
    api_key: str,
    *,
    timeout: float = 20,
    opener=None,
    environ: dict[str, str] | None = None,
) -> str:
    """Send one minimal real completion. Returns a short detail; raises ValueError.

    `/v1/models` frequently succeeds against a proxy that then rejects real completions —
    that gap is the reason backfill_proxy_compat exists. Only an actual completion closes it.
    """
    token = resolve_api_key_value(api_key, environ)
    url, headers, body = build_chat_probe(api, base_url, model_id, token)
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base URL must be a valid http:// or https:// URL")

    request = Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with (opener or urlopen)(request, timeout=timeout) as response:
            response.read()
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise ValueError(f"authentication failed (HTTP {exc.code})") from exc
        # The error body names the rejected parameter; without it a 400 is undiagnosable.
        raise ValueError(f"HTTP {exc.code}: {_error_snippet(exc)}") from exc
    except URLError as exc:
        raise ValueError(f"cannot connect to chat endpoint: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ValueError("chat request timed out") from exc
    return f"{api} 对话正常"


def _error_snippet(exc: HTTPError, limit: int = 200) -> str:
    """The upstream error message, trimmed. Best-effort: never raises."""
    try:
        raw = exc.read().decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001 - a body we cannot read must not mask the HTTP error
        return exc.reason or ""
    if not raw:
        return exc.reason or ""
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return raw[:limit]
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"][:limit]
        if isinstance(error, str):
            return error[:limit]
        if isinstance(parsed.get("message"), str):
            return parsed["message"][:limit]
    return raw[:limit]


def probe_provider(
    provider: str,
    cfg: dict,
    auth: dict,
    *,
    deep: bool = False,
    timeout: float = 10,
    opener=None,
    environ: dict[str, str] | None = None,
) -> dict:
    """Health-check one provider. Never raises — returns ok/detail/latency_ms.

    Shallow (default) hits `/v1/models`, which is free. `deep=True` sends a real
    completion, which costs tokens, so the GUI keeps that behind its own button.
    Reads only: this function writes nothing and takes no backup.
    """
    cfg = cfg if isinstance(cfg, dict) else {}
    base_url = cfg.get("baseUrl") if isinstance(cfg.get("baseUrl"), str) else ""
    api = cfg.get("api") if isinstance(cfg.get("api"), str) else ""
    api_key = provider_api_key(provider, cfg, auth)
    started = time.perf_counter()

    def done(ok: bool, detail: str) -> dict:
        return {
            "provider": provider,
            "ok": ok,
            "detail": detail,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    if not base_url:
        return done(False, "未配置 Base URL")
    try:
        if deep:
            if not supports_chat_probe(api):
                return done(False, f"{api or '未知 API 类型'} 不支持对话探测")
            models = cfg.get("models")
            first = next(
                (m["id"] for m in models if isinstance(m, dict)
                 and isinstance(m.get("id"), str) and m["id"]),
                None,
            ) if isinstance(models, list) else None
            if not first:
                return done(False, "没有可用于探测的模型")
            detail = probe_chat(base_url, api, first, api_key,
                                timeout=timeout, opener=opener, environ=environ)
            return done(True, detail)
        found = fetch_remote_models(base_url, api_key, timeout=timeout,
                                    opener=opener, environ=environ)
        return done(True, f"{len(found)} 个模型")
    except ValueError as exc:
        return done(False, str(exc))
    except OSError as exc:
        return done(False, str(exc))
