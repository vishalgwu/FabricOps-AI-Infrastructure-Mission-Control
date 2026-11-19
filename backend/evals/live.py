"""OPTIONAL live smoke test against the real model:  python -m evals.live [--check]

Separately configured: it uses whichever provider backend/.env selects (FABRICOPS_LLM_PROVIDER=openai or
anthropic) and that provider's key (OPENAI_API_KEY or ANTHROPIC_API_KEY, or FABRICOPS_LLM_API_KEY). It makes
real (billed) requests and is never run by the tests. `--check` first makes one free request that only asks
whether the key works and the model is available to it. It runs each built-in scenario once through the normal
workflow, then records the outcome, latency and token usage, and writes a review sheet for the
manual claim-support check (docs/evaluation/CLAIM_SUPPORT_RUBRIC.md).

Output goes to backend/evals/live_runs/ (git-ignored). Nothing here says anything about accuracy
until a person has filled in the review sheet.
"""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.domain.fixture_loader import load_all_fixtures
from app.main import create_app

OUT = Path(__file__).resolve().parent / "live_runs"


def have_credentials() -> bool:
    import os

    settings = get_settings()
    if settings.llm_provider not in ("openai", "anthropic"):
        return False  # "demo" and "mock" are not real models
    return bool(settings.api_key_for(settings.llm_provider)
                or (settings.llm_provider == "anthropic" and os.environ.get("ANTHROPIC_AUTH_TOKEN")))


def check_access(settings=None, client: Any = None) -> tuple[bool, str]:
    """One free request: does the key work, and can it use the configured model? Never prints the key."""
    settings = settings or get_settings()
    provider = settings.llm_provider
    if provider not in ("openai", "anthropic"):
        return False, f"FABRICOPS_LLM_PROVIDER is '{provider}'; set it to openai or anthropic in backend/.env to test a real model."
    model = settings.resolved_model(provider)
    try:
        if client is None:
            if provider == "openai":
                import openai

                client = openai.OpenAI(api_key=settings.api_key_for("openai"), max_retries=0, timeout=30)
            else:
                import anthropic

                client = anthropic.Anthropic(api_key=settings.api_key_for("anthropic"), max_retries=0, timeout=30)
        client.models.retrieve(model)
    except Exception as exc:  # noqa: BLE001 - classify by name so neither SDK has to be imported here
        kind = type(exc).__name__
        if kind == "AuthenticationError":
            return False, f"{provider} rejected the API key. Check the key in backend/.env."
        if kind in ("NotFoundError", "PermissionDeniedError"):
            return False, (f"the key works but cannot use the model '{model}'. Set FABRICOPS_LLM_MODEL in backend/.env "
                           "to a model your account can use.")
        if kind == "OpenAIError" or "credentials" in str(exc).lower() or "api_key" in str(exc).lower():
            return False, f"no API key was found for {provider}. Put it in backend/.env (see .env.example)."
        return False, f"could not reach {provider} ({kind}). Check your network and try again."
    return True, f"{provider}: the key works and model '{model}' is available."


def run_live(provider: Any = None, out_dir: Path = OUT) -> list[dict]:
    """Run each scenario once. `provider` is for testing the plumbing; leave it None for the real model."""
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        client = TestClient(create_app(str(Path(tmp) / "live.db"), provider=provider))
        for fx in sorted(load_all_fixtures().values(), key=lambda f: f.scenario_id):
            inc = client.post("/api/incidents", json={
                "title": fx.incident.title, "description": fx.incident.description,
                "scenario_type": fx.incident.scenario_type.value, "severity": fx.incident.severity.value,
                "affected_hosts": fx.incident.affected_hosts}).json()
            run_id = client.post(f"/api/incidents/{inc['id']}/runs").json()["id"]
            run = client.get(f"/api/runs/{run_id}").json()
            events = client.get(f"/api/runs/{run_id}/events").json()["events"]
            done = [json.loads(e["detail"]) for e in events if e["event_type"] == "stage_completed" and e["detail"]]
            invest = next((d for d in done if d.get("stage") == "investigate"), {})
            report = client.get(f"/api/runs/{run_id}/report")
            results.append({
                "scenario": fx.scenario_id, "run_id": run_id, "status": run["status"], "error_code": run["error_code"],
                "model_id": run["model_id"], "prompt_version": run["prompt_version"], "latency_ms": invest.get("latency_ms"),
                "usage": invest.get("usage"), "attempts": invest.get("attempts"),
                "report": report.json() if report.status_code == 200 else None,
            })
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out_dir / f"{stamp}-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (out_dir / f"{stamp}-review-sheet.md").write_text(review_sheet(results), encoding="utf-8")
    return results


def review_sheet(results: list[dict]) -> str:
    lines = ["# Claim-support review sheet", "",
             "Fill in the rating for every claim, using docs/evaluation/CLAIM_SUPPORT_RUBRIC.md. "
             "Ratings: S = supported, P = partly supported, U = unsupported, N = not checkable.", ""]
    for r in results:
        lines += [f"## {r['scenario']} ({r['run_id']}), status {r['status']}", ""]
        rep = r["report"]
        if not rep or rep["insufficient_evidence"]:
            lines += ["No claims to rate (abstention, failure or no report).", ""]
            continue
        lines += ["| # | Kind | Claim | Cited evidence IDs | Rating | Notes |", "|---|---|---|---|---|---|"]
        n = 0
        for o in rep["observations"]:
            n += 1
            lines.append(f"| {n} | observation | {o['text']} | {', '.join(o['evidence_ids'])} |  |  |")
        for h in rep["hypotheses"]:
            n += 1
            lines.append(f"| {n} | hypothesis | {h['statement']} | {', '.join(h['supporting_evidence_ids'])} |  |  |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m evals.live")
    parser.add_argument("--check", action="store_true", help="only verify the key and model (a free request), then stop")
    args = parser.parse_args(argv)
    settings = get_settings()
    if not have_credentials():
        print(f"No API credentials are configured for provider '{settings.llm_provider}', so the live smoke test was skipped.\n"
              "Put the key in backend/.env (for OpenAI: FABRICOPS_LLM_PROVIDER=openai and OPENAI_API_KEY=...; "
              "see .env.example). It makes real, billed requests.")
        return 0
    ok, message = check_access(settings)
    print(message)
    if args.check:
        return 0 if ok else 1
    if not ok:
        return 1
    print(f"Running the three scenarios once each with provider={settings.llm_provider} "
          f"model={settings.resolved_model(settings.llm_provider)} (real, billed requests)...")
    results = run_live()
    for r in results:
        print(f"{r['scenario']}: {r['status']} {r['error_code'] or ''} model={r['model_id']} "
              f"latency_ms={r['latency_ms']} usage={r['usage']}")
    print(f"\nResults and a review sheet were written to {OUT}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
