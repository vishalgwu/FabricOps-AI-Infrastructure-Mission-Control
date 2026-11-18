"""Loads and validates runtime scenario fixtures. Never reads data/evals/ (the answer key)."""
import json
from pathlib import Path

from app.schemas.fixtures import ScenarioFixture

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "data" / "fixtures"


def load_fixture(path: Path) -> ScenarioFixture:
    with path.open(encoding="utf-8") as f:
        return ScenarioFixture.model_validate(json.load(f))


def load_all_fixtures(directory: Path = FIXTURE_DIR) -> dict[str, ScenarioFixture]:
    fixtures = [load_fixture(p) for p in sorted(directory.glob("*.json"))]
    return {fx.scenario_id: fx for fx in fixtures}
