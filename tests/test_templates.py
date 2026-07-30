"""Tests for the provider template library (④).

Templates are conveniences, not authority — the endpoints came from documentation and
providers move them. What these tests guard is that every template is *structurally*
usable: a valid api type, a real URL, and an id that will not collide with a builtin.
"""
import pytest

import core


def test_every_template_is_structurally_complete():
    assert core.PROVIDER_TEMPLATES, "template list must not be empty"
    for tpl in core.PROVIDER_TEMPLATES:
        for field in ("id", "label", "baseUrl", "api"):
            assert isinstance(tpl.get(field), str) and tpl[field].strip(), f"{tpl} missing {field}"
        assert "keyEnv" in tpl, f"{tpl['id']} must state keyEnv (empty string if none)"


def test_template_api_types_are_ones_pi_accepts():
    """A template offering an api pi does not accept would produce an unusable provider."""
    for tpl in core.PROVIDER_TEMPLATES:
        assert tpl["api"] in core.API_TYPES, f"{tpl['id']}: unknown api {tpl['api']}"


def test_template_urls_parse_and_use_a_real_scheme():
    from urllib.parse import urlsplit
    for tpl in core.PROVIDER_TEMPLATES:
        parsed = urlsplit(tpl["baseUrl"])
        assert parsed.scheme in {"http", "https"}, f"{tpl['id']}: {tpl['baseUrl']}"
        assert parsed.netloc, f"{tpl['id']}: no host in {tpl['baseUrl']}"
        assert not tpl["baseUrl"].endswith("/"), f"{tpl['id']}: trailing slash"


def test_only_local_templates_may_use_plain_http():
    """Anything remote must be https; localhost is the one legitimate exception."""
    for tpl in core.PROVIDER_TEMPLATES:
        if tpl["baseUrl"].startswith("http://"):
            assert "localhost" in tpl["baseUrl"] or "127.0.0.1" in tpl["baseUrl"], tpl["id"]


def test_template_ids_and_labels_are_unique():
    ids = [t["id"] for t in core.PROVIDER_TEMPLATES]
    labels = [t["label"] for t in core.PROVIDER_TEMPLATES]
    assert len(ids) == len(set(ids))
    assert len(labels) == len(set(labels))


def test_template_ids_are_valid_provider_ids():
    """save_custom_provider rejects whitespace and '/', so templates must not contain them."""
    for tpl in core.PROVIDER_TEMPLATES:
        assert not any(ch.isspace() for ch in tpl["id"]), tpl["id"]
        assert "/" not in tpl["id"], tpl["id"]


def test_template_by_id_lookup():
    assert core.template_by_id("deepseek")["label"] == "DeepSeek"
    assert core.template_by_id("nope") is None
    assert core.template_by_id("") is None


# --- unique_provider_id ----------------------------------------------------

def test_unique_provider_id_returns_base_when_free():
    assert core.unique_provider_id("deepseek", set()) == "deepseek"
    assert core.unique_provider_id("deepseek", None) == "deepseek"


def test_unique_provider_id_avoids_collisions():
    """deepseek ships as a pi builtin, and saving over a builtin is refused."""
    assert core.unique_provider_id("deepseek", {"deepseek"}) == "deepseek-2"
    assert core.unique_provider_id("deepseek", {"deepseek", "deepseek-2"}) == "deepseek-3"


def test_unique_provider_id_handles_empty_input():
    assert core.unique_provider_id("", set()) == "provider"
    assert core.unique_provider_id("   ", set()) == "provider"
    assert core.unique_provider_id(None, set()) == "provider"


# --- template_form_values --------------------------------------------------

def test_template_form_values_seeds_an_env_reference_not_a_literal_key():
    """Seeding $VAR keeps secrets out of models.json and lights up the ⑥ indicator."""
    values = core.template_form_values(core.template_by_id("openrouter"))
    assert values["provider"] == "openrouter"
    assert values["name"] == "OpenRouter"
    assert values["baseUrl"] == "https://openrouter.ai/api/v1"
    assert values["api"] == "openai-completions"
    assert values["apiKey"] == "$OPENROUTER_API_KEY"
    assert core.api_key_status(values["apiKey"], environ={})[0] == "env_missing"


def test_template_form_values_leaves_key_blank_when_none_is_needed():
    values = core.template_form_values(core.template_by_id("ollama"))
    assert values["apiKey"] == ""
    assert core.api_key_status(values["apiKey"])[0] == "empty"


def test_template_form_values_sidesteps_a_taken_id():
    values = core.template_form_values(core.template_by_id("deepseek"), taken={"deepseek"})
    assert values["provider"] == "deepseek-2"


def test_template_form_values_rejects_junk():
    with pytest.raises(ValueError):
        core.template_form_values("not a template")


def test_every_template_survives_a_real_save(pi_env):
    """The end-to-end contract: each template's values must pass save_custom_provider's
    validation, so no template can hand the user a form that refuses to save."""
    taken = set(core.load_custom()["providers"]) | set(core.load_models_store())
    for index, tpl in enumerate(core.PROVIDER_TEMPLATES):
        values = core.template_form_values(tpl, taken=taken)
        cfg = core.save_custom_provider(
            values["provider"], values["name"], values["baseUrl"], values["api"],
            values["apiKey"], ts=f"20260730-2000{index:02d}",
        )
        assert cfg["baseUrl"] == values["baseUrl"].rstrip("/")
        taken.add(values["provider"])
    saved = core.load_custom()["providers"]
    assert len(saved) >= len(core.PROVIDER_TEMPLATES)
