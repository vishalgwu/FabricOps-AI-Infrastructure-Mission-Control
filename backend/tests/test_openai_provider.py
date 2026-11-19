"""The OpenAI adapter, tested against a fake client (no network, no key). Whether the live service accepts
the request is checked by `python -m evals.live --check`, which needs a real key."""
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings, get_settings
from app.core.logging import redact, register_secrets
from app.llm.demo import _answer
from app.llm.factory import create_provider
from app.llm.investigator import Investigator
from app.llm.openai_provider import SCHEMA_NAME, OpenAIProvider
from app.llm.provider import PermanentProviderError, ProviderRefusal, ProviderRequest, TransientProviderError
from app.main import create_app
from evals import live

BACKEND = Path(__file__).resolve().parents[1]
REQ = ProviderRequest(system="the rules", user="the evidence", json_schema={"type": "object"}, max_tokens=500)
HTTPX_REQUEST = httpx.Request("POST", "https://api.openai.example/v1/chat/completions")


class FakeCompletions:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.kwargs = response, exc, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.response


def completion(content='{"a": 1}', finish="stop", refusal=None, model="gpt-4.1-2025-04-14"):
    return SimpleNamespace(
        model=model, usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7), _request_id="req_abc",
        choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=content, refusal=refusal))])


def client(**kw):
    completions = FakeCompletions(**kw)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def provider(settings=None, **kw):
    fake, completions = client(**kw)
    return OpenAIProvider(settings or Settings(llm_provider="openai"), client=fake), completions


def status_error(cls, code, body=None):
    return cls("boom", response=httpx.Response(code, request=HTTPX_REQUEST, json={"error": {"message": "x"}}), body=body)


# ---------------------------------------------------------------- request and response

def test_the_request_uses_a_strict_json_schema_and_the_run_time_cap():
    p, c = provider(response=completion())
    out = p.generate_investigation(ProviderRequest(system="s", user="u", json_schema={"type": "object"}, max_tokens=500,
                                                   timeout_seconds=7.5))
    kw = c.kwargs
    assert kw["model"] == "gpt-4.1" and kw["max_completion_tokens"] == 500 and kw["timeout"] == 7.5
    assert kw["messages"] == [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert kw["response_format"] == {"type": "json_schema",
                                     "json_schema": {"name": SCHEMA_NAME, "strict": True, "schema": {"type": "object"}}}
    assert "temperature" not in kw and "tools" not in kw and "reasoning_effort" not in kw  # no tools, no loop
    assert out.text == '{"a": 1}' and out.model_id == "gpt-4.1-2025-04-14" and out.request_id == "req_abc"
    assert out.usage == {"input_tokens": 11, "output_tokens": 7}


def test_the_configured_timeout_is_a_ceiling():
    p, c = provider(Settings(llm_provider="openai", llm_timeout_seconds=30.0), response=completion())
    p.generate_investigation(ProviderRequest(system="s", user="u", json_schema={}, max_tokens=1, timeout_seconds=999.0))
    assert c.kwargs["timeout"] == 30.0
    p.generate_investigation(ProviderRequest(system="s", user="u", json_schema={}, max_tokens=1))
    assert c.kwargs["timeout"] == 30.0


@pytest.mark.parametrize("model,effort,expected", [
    ("gpt-4.1", "high", None), ("gpt-4o", "high", None),                    # non-reasoning models reject the parameter
    ("gpt-5.4-mini", "medium", "medium"), ("gpt-5.5", "xhigh", "high"), ("o3", "max", "high"), ("o4-mini", "low", "low"),
    ("gpt-5", "bogus", None),
])
def test_reasoning_effort_is_only_sent_to_reasoning_models(model, effort, expected):
    p, c = provider(Settings(llm_provider="openai", llm_model=model, llm_effort=effort), response=completion())
    p.generate_investigation(REQ)
    assert c.kwargs["model"] == model
    assert c.kwargs.get("reasoning_effort") == expected


def test_a_refusal_is_a_refusal_not_an_answer():
    p, _ = provider(response=completion(content=None, refusal="I can't help with that."))
    with pytest.raises(ProviderRefusal, match="can't help"):
        p.generate_investigation(REQ)
    p, _ = provider(response=completion(content="", finish="content_filter"))
    with pytest.raises(ProviderRefusal, match="content filter"):
        p.generate_investigation(REQ)


def test_truncated_and_empty_output_are_permanent_failures():
    p, _ = provider(response=completion(content="{", finish="length"))
    with pytest.raises(PermanentProviderError, match="max_completion_tokens"):
        p.generate_investigation(REQ)
    p, _ = provider(response=completion(content=None))
    with pytest.raises(PermanentProviderError, match="no content"):
        p.generate_investigation(REQ)


# ---------------------------------------------------------------- errors

def test_authentication_failure_says_which_key_to_check():
    p, _ = provider(exc=status_error(openai.AuthenticationError, 401))
    with pytest.raises(PermanentProviderError, match="OPENAI_API_KEY"):
        p.generate_investigation(REQ)


def test_rate_limits_are_retried_but_running_out_of_credit_is_not():
    p, _ = provider(exc=status_error(openai.RateLimitError, 429, body={"code": "rate_limit_exceeded"}))
    with pytest.raises(TransientProviderError):
        p.generate_investigation(REQ)
    p, _ = provider(exc=status_error(openai.RateLimitError, 429, body={"code": "insufficient_quota"}))
    with pytest.raises(PermanentProviderError, match="quota"):
        p.generate_investigation(REQ)


def test_network_problems_and_server_errors_are_transient_client_errors_are_not():
    for exc in (openai.APIConnectionError(request=HTTPX_REQUEST), openai.APITimeoutError(request=HTTPX_REQUEST),
                status_error(openai.InternalServerError, 500)):
        p, _ = provider(exc=exc)
        with pytest.raises(TransientProviderError):
            p.generate_investigation(REQ)
    for exc in (status_error(openai.BadRequestError, 400), status_error(openai.NotFoundError, 404)):
        p, _ = provider(exc=exc)
        with pytest.raises(PermanentProviderError):
            p.generate_investigation(REQ)


def test_unrelated_programming_errors_are_not_disguised():
    p, _ = provider(exc=TypeError("a bug"))
    with pytest.raises(TypeError):
        p.generate_investigation(REQ)


def test_a_missing_key_is_a_clear_configuration_error(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # so no stray .env is picked up
    with pytest.raises(PermanentProviderError, match="OPENAI_API_KEY"):
        OpenAIProvider(Settings(llm_provider="openai"))


def test_a_missing_key_ends_the_run_as_provider_not_configured_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    from tests.test_security_hardening import _investigator_package

    out = Investigator(provider_factory=lambda: create_provider(Settings(llm_provider="openai"))).investigate(_investigator_package())
    assert out.status.value == "FAILED" and out.error_code == "provider_not_configured"
    assert "OPENAI_API_KEY" in out.errors[0]


# ---------------------------------------------------------------- settings and the .env file

def test_a_backend_env_file_with_openai_settings_is_enough(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("FABRICOPS_LLM_PROVIDER=openai\nOPENAI_API_KEY=sk-proj-FakeKeyForTheTest0123456789\n", encoding="utf-8")
    s = Settings(_env_file=env)
    assert s.llm_provider == "openai" and s.api_key_for("openai") == "sk-proj-FakeKeyForTheTest0123456789"
    assert s.resolved_model("openai") == "gpt-4.1"
    assert create_provider(s).name == "openai"  # builds the real client; no request is made


def test_the_model_can_be_overridden_in_the_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FABRICOPS_LLM_PROVIDER=openai\nFABRICOPS_LLM_MODEL=gpt-5.4-mini\nOPENAI_API_KEY=sk-fake-0123456789\n", encoding="utf-8")
    s = Settings(_env_file=env)
    assert s.resolved_model("openai") == "gpt-5.4-mini"


def test_the_real_environment_variable_works_too(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fromenv-0123456789")
    assert Settings().api_key_for("openai") == "sk-fromenv-0123456789"


def test_each_provider_uses_its_own_key_unless_one_generic_key_is_set(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    s = Settings(OPENAI_API_KEY="sk-openai-0123456789", ANTHROPIC_API_KEY="sk-ant-anthropic-0123456789")
    assert s.api_key_for("openai") == "sk-openai-0123456789"        # never the other vendor's key
    assert s.api_key_for("anthropic") == "sk-ant-anthropic-0123456789"
    generic = Settings(llm_api_key=SecretStr("generic-key-0123456789"), OPENAI_API_KEY="sk-openai-0123456789")
    assert generic.api_key_for("openai") == "generic-key-0123456789"
    assert Settings().api_key_for("openai") is None  # nothing set: the SDK may still look in its own environment


def test_anthropic_defaults_are_unchanged():
    s = Settings()
    assert s.llm_provider == "anthropic" and s.resolved_model("anthropic") == "claude-opus-5-5"


def test_every_key_is_registered_for_log_redaction():
    s = Settings(llm_api_key=SecretStr("generic-secret-credential-1"), OPENAI_API_KEY="sk-proj-AAAA1111BBBB2222",
                 ANTHROPIC_API_KEY="sk-ant-CCCC3333DDDD4444")
    assert set(s.all_secret_values()) == {"generic-secret-credential-1", "sk-proj-AAAA1111BBBB2222", "sk-ant-CCCC3333DDDD4444"}
    register_secrets(s.all_secret_values())
    for secret in s.all_secret_values():
        assert secret not in redact(f"the provider said {secret} is bad")


@pytest.mark.parametrize("text,secret", [
    ("OPENAI_API_KEY=sk-proj-Xy12Ab34Cd56Ef78Gh90 loaded", "Xy12Ab34Cd56Ef78Gh90"),
    ("headers {'Authorization': 'Bearer sk-svcacct-Zz99Yy88Xx77Ww66'}", "Zz99Yy88Xx77Ww66"),
    ("Incorrect API key provided: sk-abcdefghijklmnop1234", "abcdefghijklmnop1234"),
])
def test_openai_style_keys_are_redacted_from_logs(text, secret):
    assert secret not in redact(text)


def test_the_key_never_appears_in_settings_output():
    s = Settings(OPENAI_API_KEY="sk-proj-NeverShowThis0123456789")
    assert "NeverShowThis" not in repr(s) and "NeverShowThis" not in str(s.model_dump())


# ---------------------------------------------------------------- the whole pipeline with an OpenAI-shaped client

def test_a_full_investigation_through_the_openai_adapter(tmp_path):
    def create(**kwargs):
        package = json.loads(kwargs["messages"][1]["content"].split("<evidence_package>\n", 1)[1].rsplit("\n</evidence_package>", 1)[0])
        return completion(content=json.dumps(_answer(package)), model="gpt-4.1-2025-04-14")

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    app = create_app(str(tmp_path / "o.db"), provider=OpenAIProvider(Settings(llm_provider="openai"), client=fake))
    c = TestClient(app)
    info = next(s for s in c.get("/api/scenarios").json() if s["scenario_type"] == "inference_slowdown")
    inc = c.post("/api/incidents", json={"title": info["title"], "description": info["description"],
                                         "scenario_type": "inference_slowdown", "severity": "high",
                                         "affected_hosts": ["gpu-h07"]}).json()
    run_id = c.post(f"/api/incidents/{inc['id']}/runs").json()["id"]
    run = c.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "WAITING_APPROVAL" and run["model_id"] == "gpt-4.1-2025-04-14"
    events = c.get(f"/api/runs/{run_id}/events").json()["events"]
    invest = next(json.loads(e["detail"]) for e in events if e["event_type"] == "stage_completed"
                  and json.loads(e["detail"])["stage"] == "investigate")
    assert invest["provider"] == "openai" and invest["usage"] == {"input_tokens": 11, "output_tokens": 7}


def test_the_openai_sdk_is_only_imported_by_its_adapter():
    for f in (BACKEND / "app").rglob("*.py"):
        if f.name != "openai_provider.py":
            text = f.read_text(encoding="utf-8")
            assert "import openai" not in text and "from openai" not in text, f


# ---------------------------------------------------------------- the live check helper (still no network)

def test_live_check_reports_a_working_key_and_model():
    fake = SimpleNamespace(models=SimpleNamespace(retrieve=lambda model: SimpleNamespace(id=model)))
    ok, msg = live.check_access(Settings(llm_provider="openai", OPENAI_API_KEY="sk-fake-0123456789"), client=fake)
    assert ok and "gpt-4.1" in msg and "sk-fake" not in msg


@pytest.mark.parametrize("error_name,expected", [
    ("AuthenticationError", "rejected the API key"), ("NotFoundError", "cannot use the model"),
    ("PermissionDeniedError", "cannot use the model"), ("APIConnectionError", "could not reach"),
])
def test_live_check_explains_each_kind_of_failure_without_the_key(error_name, expected):
    def boom(model):
        raise type(error_name, (Exception,), {})("secret sk-fake-0123456789 detail")

    fake = SimpleNamespace(models=SimpleNamespace(retrieve=boom))
    ok, msg = live.check_access(Settings(llm_provider="openai", OPENAI_API_KEY="sk-fake-0123456789"), client=fake)
    assert not ok and expected in msg and "sk-fake" not in msg


def test_live_check_refuses_to_pretend_the_demo_or_mock_models_are_real():
    for provider_name in ("demo", "mock"):
        ok, msg = live.check_access(Settings(llm_provider=provider_name))
        assert not ok and "openai or anthropic" in msg


def test_live_credentials_follow_the_selected_provider(monkeypatch):
    monkeypatch.setattr(live, "get_settings", lambda: Settings(llm_provider="openai", OPENAI_API_KEY="sk-fake-0123456789"))
    assert live.have_credentials() is True
    monkeypatch.setattr(live, "get_settings", lambda: Settings(llm_provider="openai", ANTHROPIC_API_KEY="sk-ant-fake-0123456789"))
    assert live.have_credentials() is False  # an Anthropic key does not count when OpenAI is selected
    monkeypatch.setattr(live, "get_settings", lambda: Settings(llm_provider="demo", OPENAI_API_KEY="sk-fake-0123456789"))
    assert live.have_credentials() is False


def test_live_main_check_mode_stops_after_the_free_check(monkeypatch, capsys):
    monkeypatch.setattr(live, "get_settings", lambda: Settings(llm_provider="openai", OPENAI_API_KEY="sk-fake-0123456789"))
    monkeypatch.setattr(live, "check_access", lambda settings=None, client=None: (True, "openai: the key works and model 'gpt-4.1' is available."))
    monkeypatch.setattr(live, "run_live", lambda *a, **k: pytest.fail("--check must not make the billed requests"))
    assert live.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "the key works" in out and "sk-fake" not in out
    monkeypatch.setattr(live, "check_access", lambda settings=None, client=None: (False, "openai rejected the API key."))
    assert live.main(["--check"]) == 1
    assert live.main([]) == 1  # a failed check also stops a full run


def test_get_settings_cache_is_not_polluted_by_these_tests():
    get_settings.cache_clear()
    assert get_settings().llm_provider in ("anthropic", "openai", "demo", "mock")
