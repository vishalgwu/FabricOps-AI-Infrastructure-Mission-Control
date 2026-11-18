"""Release hygiene: the pinned lock file must stay consistent with what pyproject.toml declares."""
import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

BACKEND = Path(__file__).resolve().parents[1]


def _lock() -> dict[str, str]:
    pins = {}
    for line in (BACKEND / "requirements-lock.txt").read_text(encoding="utf-8").splitlines():
        m = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", line.strip())
        if m:
            pins[canonicalize_name(m.group(1))] = m.group(2)
    return pins


def _declared() -> list[Requirement]:
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    reqs = list(project["dependencies"])
    for extra in ("dev", "llm"):
        reqs += project["optional-dependencies"][extra]
    return [Requirement(r) for r in reqs]


def test_every_declared_dependency_is_pinned_in_the_lock_file():
    pins = _lock()
    missing = [r.name for r in _declared() if canonicalize_name(r.name) not in pins]
    assert missing == []


def test_every_pin_satisfies_the_range_declared_in_pyproject():
    pins = _lock()
    for r in _declared():
        version = pins[canonicalize_name(r.name)]
        assert r.specifier.contains(version, prereleases=True), f"{r.name}=={version} is outside '{r.specifier}'"


def test_the_lock_file_pins_exact_versions_only():
    lines = [ln for ln in (BACKEND / "requirements-lock.txt").read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.startswith("#")]
    assert len(lines) >= 25 and all("==" in ln for ln in lines)


def test_the_frontend_has_a_lock_file_and_it_is_committed():
    assert (BACKEND.parent / "frontend" / "package-lock.json").is_file()


def test_the_acceptance_review_names_only_tests_that_exist():
    doc = (BACKEND.parent / "docs" / "ACCEPTANCE_REVIEW.md").read_text(encoding="utf-8")
    all_tests = "\n".join(p.read_text(encoding="utf-8") for p in (BACKEND / "tests").glob("test_*.py"))
    files = re.findall(r"`(tests/test_[a-z_]+\.py)`", doc)
    assert files and all((BACKEND / f).is_file() for f in files)
    names = set(re.findall(r"`(?:tests/test_[a-z_]+\.py)?::(test_[A-Za-z0-9_]+)`", doc))
    assert len(names) >= 25
    missing = [n for n in names if f"def {n}(" not in all_tests]
    assert missing == []


def test_the_readme_test_counts_match_reality():
    """The README quotes how many tests there are. Keep it honest: count them."""
    import subprocess
    import sys

    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "--ignore=tests/test_release.py"],
                         cwd=BACKEND, capture_output=True, text=True).stdout
    collected = int(re.search(r"(\d+) tests? collected", out).group(1)) + _release_tests()
    readme = (BACKEND.parent / "README.md").read_text(encoding="utf-8")
    quoted = int(re.search(r"(\d+) backend tests", readme).group(1))
    assert quoted == collected, f"README says {quoted} backend tests, there are {collected}"


def _release_tests() -> int:
    return len(re.findall(r"^def test_", (BACKEND / "tests" / "test_release.py").read_text(encoding="utf-8"), re.M))


def test_every_relative_link_in_the_readme_and_docs_resolves():
    root = BACKEND.parent
    pages = [root / "README.md", *(root / "docs").rglob("*.md")]
    broken = []
    for page in pages:
        for target in re.findall(r"\]\((?!https?:|mailto:|#)([^)\s]+)\)", page.read_text(encoding="utf-8")):
            path = target.split("#")[0]
            if path and not (page.parent / path).resolve().exists():
                broken.append(f"{page.relative_to(root)} -> {target}")
    assert broken == []


def test_the_screenshots_referenced_by_the_readme_exist_and_are_real_images():
    root = BACKEND.parent
    for name in re.findall(r"\]\((docs/images/[^)]+\.png)\)", (root / "README.md").read_text(encoding="utf-8")):
        data = (root / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 10_000, name
