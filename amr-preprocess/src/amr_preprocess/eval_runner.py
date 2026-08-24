from __future__ import annotations

import json
import time
from pathlib import Path

import yaml

from amr_preprocess.models import ProcessedDocument
from amr_preprocess.pipeline import process_path
from amr_preprocess.scorers import score_run


def run_eval(fixtures_dir: Path, config_path: Path) -> dict:
    fixtures_dir = Path(fixtures_dir)
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    thresholds = config.get("thresholds", {})
    cases = sorted(
        p for p in fixtures_dir.iterdir() if p.is_dir() and (p / "expected.json").exists()
    )
    if not cases:
        raise FileNotFoundError(f"no fixtures with expected.json under {fixtures_dir}")

    start = time.perf_counter()
    per_case = []
    for case in cases:
        expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))
        source = _case_source(case)
        artifacts = fixtures_dir / ".eval-runs"
        manifest, run_dir, docs = process_path(source, artifacts, render_pages=False)
        doc = _match_doc(docs, expected)
        scores = score_run(doc, expected)
        per_case.append(
            {
                "case": case.name,
                "run_id": manifest.run_id,
                "run_dir": str(run_dir),
                "scores": scores,
            }
        )
    latency_ms = int((time.perf_counter() - start) * 1000)

    names = sorted({n for case in per_case for n in case["scores"]})
    aggregated = []
    for name in names:
        vals = [c["scores"][name] for c in per_case]
        score = sum(vals) / len(vals)
        threshold = float(thresholds.get(name, 0.0))
        aggregated.append(
            {
                "name": name,
                "score": score,
                "threshold": threshold,
                "pass": score >= threshold,
            }
        )

    report = {
        "latency_ms": latency_ms,
        "cases": per_case,
        "scores": aggregated,
    }
    out = fixtures_dir / ".eval-runs" / "metrics.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _case_source(case: Path) -> Path:
    expected_path = case / "expected.json"
    expected = {}
    if expected_path.exists():
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
    filename = expected.get("filename")
    if filename and (case / filename).exists():
        return case / filename
    raw = case / "raw"
    if raw.is_dir():
        files = [p for p in raw.iterdir() if p.is_file()]
        if len(files) == 1:
            return files[0]
        return raw
    files = [p for p in case.iterdir() if p.is_file() and p.name != "expected.json"]
    if not files:
        raise FileNotFoundError(f"no source document in {case}")
    return files[0]


def _match_doc(docs: list[ProcessedDocument], expected: dict) -> ProcessedDocument:
    filename = expected.get("filename")
    if filename:
        for d in docs:
            if d.filename == filename:
                return d
    return docs[0]
