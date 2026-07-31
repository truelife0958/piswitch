"""Model metadata and catalog helpers. No I/O."""
from __future__ import annotations

from typing import Any

from .store import merge_openai_proxy_compat

def provider_model_map(store: dict, custom: dict) -> dict:
    result: dict[str, list[dict]] = {}
    for prov, info in store.items():
        if not isinstance(info, dict):
            continue
        models = info.get("models", [])
        for m in models if isinstance(models, list) else []:
            if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"]:
                result.setdefault(prov, []).append(
                    {"id": m.get("id"), "name": m.get("name") or m.get("id"), "source": "builtin"})
    providers = custom.get("providers", {})
    for prov, cfg in providers.items() if isinstance(providers, dict) else []:
        if not isinstance(cfg, dict):
            continue
        models = cfg.get("models", [])
        for m in models if isinstance(models, list) else []:
            if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"]:
                result.setdefault(prov, []).append(
                    {"id": m.get("id"), "name": m.get("name") or m.get("id"), "source": "custom"})
    for prov in result:
        result[prov].sort(key=lambda x: (x["source"], x["id"] or ""))
    return result


def model_supports_reasoning(store: dict, custom: dict, provider: str, model_id) -> bool:
    if not provider or not model_id:
        return False
    builtin = store.get(provider, {})
    builtin_models = builtin.get("models", []) if isinstance(builtin, dict) else []
    for m in builtin_models if isinstance(builtin_models, list) else []:
        if isinstance(m, dict) and m.get("id") == model_id:
            return bool(m.get("reasoning"))
    providers = custom.get("providers", {})
    cfg = providers.get(provider, {}) if isinstance(providers, dict) else {}
    custom_models = cfg.get("models", []) if isinstance(cfg, dict) else []
    for m in custom_models if isinstance(custom_models, list) else []:
        if isinstance(m, dict) and m.get("id") == model_id:
            return bool(m.get("reasoning"))
    return False


# Starting points for the provider form. These are conveniences, not authority: the
# endpoints are recorded from documentation and providers do move them, so the form stays
# fully editable and 测试连接 is the thing that actually confirms one works.
#
# `keyEnv` seeds the API-key field with a $ENV_VAR reference rather than a literal, so a
# key never lands in models.json and the env indicator tells you at once if it is unset.
PROVIDER_TEMPLATES = (
    {"id": "openai", "label": "OpenAI", "baseUrl": "https://api.openai.com/v1",
     "api": "openai-completions", "keyEnv": "OPENAI_API_KEY"},
    {"id": "anthropic", "label": "Anthropic", "baseUrl": "https://api.anthropic.com",
     "api": "anthropic-messages", "keyEnv": "ANTHROPIC_API_KEY"},
    {"id": "gemini", "label": "Google Gemini",
     "baseUrl": "https://generativelanguage.googleapis.com",
     "api": "google-generative-ai", "keyEnv": "GEMINI_API_KEY"},
    {"id": "deepseek", "label": "DeepSeek", "baseUrl": "https://api.deepseek.com/v1",
     "api": "openai-completions", "keyEnv": "DEEPSEEK_API_KEY"},
    {"id": "openrouter", "label": "OpenRouter", "baseUrl": "https://openrouter.ai/api/v1",
     "api": "openai-completions", "keyEnv": "OPENROUTER_API_KEY"},
    {"id": "siliconflow", "label": "SiliconFlow 硅基流动",
     "baseUrl": "https://api.siliconflow.cn/v1",
     "api": "openai-completions", "keyEnv": "SILICONFLOW_API_KEY"},
    {"id": "moonshot", "label": "Moonshot 月之暗面", "baseUrl": "https://api.moonshot.cn/v1",
     "api": "openai-completions", "keyEnv": "MOONSHOT_API_KEY"},
    {"id": "zhipu", "label": "智谱 GLM", "baseUrl": "https://open.bigmodel.cn/api/paas/v4",
     "api": "openai-completions", "keyEnv": "ZHIPU_API_KEY"},
    {"id": "dashscope", "label": "阿里云百炼 DashScope",
     "baseUrl": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "api": "openai-completions", "keyEnv": "DASHSCOPE_API_KEY"},
    {"id": "groq", "label": "Groq", "baseUrl": "https://api.groq.com/openai/v1",
     "api": "openai-completions", "keyEnv": "GROQ_API_KEY"},
    {"id": "together", "label": "Together AI", "baseUrl": "https://api.together.xyz/v1",
     "api": "openai-completions", "keyEnv": "TOGETHER_API_KEY"},
    {"id": "ollama", "label": "Ollama (本地)", "baseUrl": "http://localhost:11434/v1",
     "api": "openai-completions", "keyEnv": ""},
)


def template_by_id(template_id: str) -> dict | None:
    return next((t for t in PROVIDER_TEMPLATES if t["id"] == template_id), None)


def unique_provider_id(base: str, taken) -> str:
    """`base` if free, else base-2, base-3, ...

    A template id often collides with a builtin pi already ships (deepseek is the common
    case), and saving over a builtin is refused — so suggest a free id instead of handing
    the user a form that cannot be saved.
    """
    base = (base or "provider").strip() or "provider"
    taken = set(taken or ())
    if base not in taken:
        return base
    for n in range(2, 1000):
        candidate = f"{base}-{n}"
        if candidate not in taken:
            return candidate
    return base


def template_form_values(template: dict, taken=None) -> dict:
    """Form field values for a template, with a provider id that is free to use."""
    if not isinstance(template, dict):
        raise ValueError("invalid template")
    key_env = template.get("keyEnv") or ""
    return {
        "provider": unique_provider_id(template.get("id", ""), taken),
        "name": template.get("label") or template.get("id", ""),
        "baseUrl": template.get("baseUrl", ""),
        "api": template.get("api") or API_TYPES[0],
        "apiKey": f"${key_env}" if key_env else "",
    }


# The `api` values pi accepts on a provider. supports_chat_probe keys off these.
API_TYPES = (
    "openai-completions",
    "openai-responses",
    "anthropic-messages",
    "google-generative-ai",
    "mistral-conversations",
    "google-vertex",
    "azure-openai-responses",
    "openai-codex-responses",
    "bedrock-converse-stream",
)
DEFAULT_INPUT_TYPES = ["text", "image"]


MODEL_METADATA_KEYS = ("contextWindow", "maxTokens", "reasoning", "input", "cost")


def parse_model_ids(text: str) -> list[str]:
    out: list[str] = []
    for part in (text or "").split(","):
        s = part.strip()
        if s and s not in out:
            out.append(s)
    return out


def build_custom_provider_cfg(preset: dict) -> dict:
    ids = parse_model_ids(preset.get("model", "")) or ([preset["model"]] if preset.get("model") else [])
    models = [{
        "id": i, "name": i, "reasoning": bool(preset.get("reasoning", False)),
        "input": list(DEFAULT_INPUT_TYPES),
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 128000, "maxTokens": 16384,
    } for i in ids]
    config = {
        "name": preset.get("name") or preset["provider"],
        "baseUrl": preset.get("baseUrl", ""),
        "api": preset.get("api", "openai-completions"),
        "apiKey": preset.get("apiKey", ""),
        "models": models,
    }
    if config["api"] == "openai-completions":
        config["compat"] = merge_openai_proxy_compat(preset.get("compat"))
    return config


def fetch_models_url(base: str) -> str:
    b = (base or "").rstrip("/")
    if b.endswith("/models"):
        return b
    if b.endswith("/v1"):
        return b + "/models"
    return b + "/v1/models"


def format_context_window(value: Any) -> str:
    """Render a contextWindow compactly for the model list: 128000 -> '128K'.

    Returns '-' for missing or nonsensical values rather than inventing a number, so a
    provider whose metadata piswitch never learned reads as unknown instead of as zero.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return "-"
    value = int(value)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1000:
        return f"{value // 1000}K"
    return str(value)


def builtin_model_metadata(model_id: str, store: dict) -> dict:
    """Metadata for `model_id` if any builtin provider ships that exact id.

    Third-party gateways resell the same models pi already describes in
    models-store.json, so the honest numbers are often already on disk.
    """
    if not (isinstance(model_id, str) and model_id) or not isinstance(store, dict):
        return {}
    for info in store.values():
        if not isinstance(info, dict):
            continue
        models = info.get("models")
        if not isinstance(models, list):
            continue
        for model in models:
            if isinstance(model, dict) and model.get("id") == model_id:
                return {key: model[key] for key in MODEL_METADATA_KEYS if key in model}
    return {}


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if value > 0 else None


def _price_per_million(value: Any) -> float | None:
    """OpenRouter quotes price per token as a string; pi's cost is per million tokens."""
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return round(value * 1_000_000, 6)


def metadata_from_remote(record: Any) -> dict:
    """Pull whatever real metadata a /v1/models record carries.

    Gateways disagree on field names: OpenRouter uses context_length plus a pricing
    block quoted per token, others use context_window / max_context_length. Anything
    absent is simply left out, so callers can fall back rather than record a guess.
    """
    if not isinstance(record, dict):
        return {}
    meta: dict[str, Any] = {}
    for key in ("context_length", "context_window", "max_context_length", "contextWindow"):
        window = _positive_int(record.get(key))
        if window:
            meta["contextWindow"] = window
            break
    for key in ("max_completion_tokens", "max_output_tokens", "max_tokens", "maxTokens"):
        limit = _positive_int(record.get(key))
        if limit:
            meta["maxTokens"] = limit
            break
    top = record.get("top_provider")
    if "maxTokens" not in meta and isinstance(top, dict):
        limit = _positive_int(top.get("max_completion_tokens"))
        if limit:
            meta["maxTokens"] = limit
    if "contextWindow" not in meta and isinstance(top, dict):
        window = _positive_int(top.get("context_length"))
        if window:
            meta["contextWindow"] = window

    pricing = record.get("pricing")
    if isinstance(pricing, dict):
        cost = {}
        for source, target in (
            ("prompt", "input"), ("completion", "output"),
            ("input_cache_read", "cacheRead"), ("input_cache_write", "cacheWrite"),
        ):
            price = _price_per_million(pricing.get(source))
            if price is not None:
                cost[target] = price
        if cost:
            meta["cost"] = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, **cost}

    for key in ("reasoning", "supports_reasoning"):
        if isinstance(record.get(key), bool):
            meta["reasoning"] = record[key]
            break
    return meta


def infer_model_metadata(model_id: str, *, store: dict | None = None, remote: Any = None) -> dict:
    """Best available metadata for a model: the builtin store first, then the gateway.

    Builtin wins because pi authored it; the gateway's own numbers fill the gaps. Returns
    {} when neither knows anything, which callers should treat as "leave it unknown".
    """
    meta = dict(metadata_from_remote(remote))
    meta.update(builtin_model_metadata(model_id, store or {}))
    return meta


def parse_model_edits(raw: dict, *, existing: dict | None = None) -> dict:
    """Validate model-editor form input into a changes dict for update_provider_model.

    A blank numeric field means "unknown", so it is dropped rather than coerced to 0 —
    clearing the context window must not assert that the window *is* zero. Prices are
    given per million tokens, matching how pi's cost block reads.
    """
    if not isinstance(raw, dict):
        raise ValueError("invalid form input")
    changes: dict[str, Any] = {}

    name = str(raw.get("name", "")).strip()
    if name:
        changes["name"] = name

    for field, key, label in (
        ("contextWindow", "contextWindow", "上下文窗口"),
        ("maxTokens", "maxTokens", "最大输出 tokens"),
    ):
        text = str(raw.get(field, "")).strip()
        if not text:
            continue
        try:
            value = int(text)
        except ValueError:
            raise ValueError(f"{label}必须是整数") from None
        if value <= 0:
            raise ValueError(f"{label}必须大于 0")
        changes[key] = value

    if "reasoning" in raw:
        changes["reasoning"] = bool(raw["reasoning"])

    base_cost = existing.get("cost") if isinstance(existing, dict) else None
    cost = dict(base_cost) if isinstance(base_cost, dict) else {}
    touched = False
    for field, key, label in (
        ("costInput", "input", "输入价格"),
        ("costOutput", "output", "输出价格"),
        ("costCacheRead", "cacheRead", "缓存读取价格"),
        ("costCacheWrite", "cacheWrite", "缓存写入价格"),
    ):
        if field not in raw:
            continue
        text = str(raw.get(field, "")).strip()
        if not text:
            continue
        try:
            value = float(text)
        except ValueError:
            raise ValueError(f"{label}必须是数字") from None
        if value < 0:
            raise ValueError(f"{label}不能为负")
        cost[key] = value
        touched = True
    if touched:
        changes["cost"] = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, **cost}
    return changes


def _provider_model(model_id: str, meta: dict | None = None) -> dict:
    """A new model entry. `meta` overrides the fallback values field by field.

    The fallbacks are guesses, not facts — see infer_model_metadata for where real
    values come from. They exist only so a model added by hand is still well-formed.
    """
    model = {
        "id": model_id,
        "name": model_id,
        "reasoning": False,
        "input": list(DEFAULT_INPUT_TYPES),
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 128000,
        "maxTokens": 16384,
    }
    if isinstance(meta, dict):
        for key in MODEL_METADATA_KEYS:
            if key in meta and meta[key] is not None:
                model[key] = meta[key]
        if isinstance(meta.get("name"), str) and meta["name"].strip():
            model["name"] = meta["name"]
    return model
