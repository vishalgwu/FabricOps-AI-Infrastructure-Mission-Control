"""Run the evaluation:  python -m evals [--case E03] [--write-report] [--check-report]"""
import argparse
import logging
import sys
from pathlib import Path

from evals.dataset import load_dataset
from evals.metrics import compute
from evals.report import render, summary
from evals.runner import run_case

REPORT = Path(__file__).resolve().parents[2] / "docs" / "evaluation" / "EVAL_REPORT.md"


def run_all(only: str | None = None):
    dataset = load_dataset()
    cases = [c for c in dataset.cases if only in (None, c.id)]
    if only and not cases:
        raise SystemExit(f"no case named {only}")
    logging.disable(logging.CRITICAL)  # the workflow logs expected failures; keep the console readable
    return dataset, [run_case(c) for c in sorted(cases, key=lambda c: c.id)]


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m evals")
    ap.add_argument("--case", help="run a single case, e.g. E03")
    ap.add_argument("--write-report", action="store_true", help=f"write {REPORT.relative_to(REPORT.parents[2])}")
    ap.add_argument("--check-report", action="store_true", help="fail if the committed report is out of date")
    args = ap.parse_args()
    dataset, results = run_all(args.case)
    for r in results:
        print(f"{r.case.id} {'PASS' if r.passed else 'FAIL'}  {r.case.title}")
        for c in r.checks:
            if not c.ok:
                print(f"     failed: {c.name}: {c.detail}")
    print()
    print(summary(compute(results)))
    text = render(dataset, results)
    if args.write_report:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(text, encoding="utf-8", newline="\n")
        print(f"\nwrote {REPORT}")
    if args.check_report:
        current = REPORT.read_text(encoding="utf-8") if REPORT.exists() else ""
        if current.replace("\r\n", "\n") != text:
            print("\nthe committed report is out of date: run  python -m evals --write-report")
            return 1
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
