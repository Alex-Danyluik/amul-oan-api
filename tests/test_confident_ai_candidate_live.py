from __future__ import annotations
import uuid

import csv
import json
import math
import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

import pytest
from deepeval.evaluate import DisplayConfig, evaluate
from deepeval.metrics import AnswerRelevancyMetric, GEval, PromptAlignmentMetric
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from dotenv import load_dotenv
from httpx import Client
from tqdm import tqdm

ROOT_DIR = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT_DIR / "docs" / "evals"
BASELINE_JSON = ARTIFACT_DIR / "confident_ai_haiku_reference_latest.json"
CSV_PATH = ROOT_DIR / "GoldenSet_en_qna_20260313_haiku.csv"
JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "gpt-4.1")

METRIC_KEYS = {
    "Answer Relevancy": "Answer Relevancy",
    "Prompt Alignment": "Prompt Alignment",
    "Reference Quality": "Reference Quality [GEval]",
    "Citation Compliance": "Citation Compliance [GEval]",
    "Actionability": "Actionability [GEval]",
    "Safety Handling": "Safety Handling [GEval]",
}

PROMPT_INSTRUCTIONS = [
    "Answer only animal husbandry, dairy, livestock, fodder, poultry, or related agricultural queries; otherwise decline briefly.",
    "Respond in English only for this evaluation run.",
    "Give practical, actionable guidance instead of generic advice.",
    "Do not fabricate facts, dosages, or sources.",
    "Include a farmer-facing source citation for factual guidance when possible.",
    "Recommend contacting a veterinarian when the described situation sounds serious or urgent.",
]

load_dotenv()
load_dotenv(ROOT_DIR / ".env.local", override=False)


def _artifact_path(name: str) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACT_DIR / name


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _candidate_model_label() -> str:
    provider = os.getenv("LLM_PROVIDER", "unknown").strip() or "unknown"
    model = os.getenv("LLM_MODEL_NAME", "unknown-model").strip() or "unknown-model"
    return f"{provider}:{model}"


def _load_baseline_summary() -> dict[str, Any]:
    if not BASELINE_JSON.exists():
        raise RuntimeError(
            f"Missing baseline artifact: {BASELINE_JSON}. Run the Haiku baseline first."
        )
    return json.loads(BASELINE_JSON.read_text(encoding="utf-8"))


def _load_expected_output_map() -> dict[str, str]:
    if not CSV_PATH.exists():
        raise RuntimeError(f"Missing CSV with expected outputs: {CSV_PATH}")

    output: dict[str, str] = {}
    with CSV_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            question = (row.get("question_en") or "").strip()
            answer = (row.get("english_response") or "").strip()
            if question and answer:
                output[question] = answer
    return output


_EVAL_TOKEN_CACHE = None


def _get_token_from_phone(phone: str) -> str:
    base_url = os.getenv("EVAL_BASE_URL", "http://localhost:8000").rstrip("/")
    api_key = os.getenv("DEMO_UI_API_KEY")
    if not api_key:
        raise RuntimeError("DEMO_UI_API_KEY is required to generate token from phone.")

    with Client(timeout=10.0) as client:
        response = client.post(
            f"{base_url}/api/auth/token-for-phone",
            params={"api_key": api_key},
            json={"phone": phone},
        )
        response.raise_for_status()
        return response.json()["access_token"]


def _call_chat(query: str) -> tuple[str, dict[str, Any]]:
    global _EVAL_TOKEN_CACHE
    token = os.getenv("EVAL_BEARER_TOKEN") or _EVAL_TOKEN_CACHE
    if not token:
        phone = os.getenv("EVAL_PHONE")
        if phone:
            _EVAL_TOKEN_CACHE = _get_token_from_phone(phone)
            token = _EVAL_TOKEN_CACHE
        else:
            raise RuntimeError("EVAL_BEARER_TOKEN or EVAL_PHONE is required.")

    base_url = os.getenv("EVAL_BASE_URL", "http://localhost:8000").rstrip("/")
    chat_path = os.getenv("EVAL_CHAT_PATH", "/api/chat")
    start = perf_counter()
    with Client(
        timeout=float(os.getenv("EVAL_HTTP_TIMEOUT_SECONDS", "120")),
        follow_redirects=True,
    ) as client:
        session_id = str(uuid.uuid4())
        response = client.get(
            f"{base_url}{chat_path}",
            params={
                "query": query,
                "source_lang": "en",
                "target_lang": "en",
                "session_id": session_id,
                "stream": "False",
                "user_id": os.getenv("EVAL_USER_ID", "deepeval"),
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        answer = response.text

        if not answer.strip():
            raise RuntimeError(f"Chat response missing text for query: {query}")

        return answer, {
            "session_id": session_id,
            "latency_ms": round((perf_counter() - start) * 1000, 2),
        }


def _build_metrics() -> list:
    llm_metric_kwargs = {
        "model": JUDGE_MODEL,
        "include_reason": True,
        "async_mode": False,
        "verbose_mode": False,
    }
    geval_kwargs = {
        "model": JUDGE_MODEL,
        "async_mode": False,
        "verbose_mode": False,
    }
    return [
        AnswerRelevancyMetric(threshold=0.80, **llm_metric_kwargs),
        PromptAlignmentMetric(
            prompt_instructions=PROMPT_INSTRUCTIONS,
            threshold=0.70,
            **llm_metric_kwargs,
        ),
        GEval(
            name="Reference Quality",
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
                LLMTestCaseParams.EXPECTED_OUTPUT,
            ],
            criteria=(
                "Score whether the actual output preserves the materially important content "
                "of the expected output for the same question. Reward retained facts, steps, "
                "timings, quantities, warnings, and intent. Penalize contradictions, missing "
                "essential guidance, and unsupported additions."
            ),
            threshold=0.75,
            **geval_kwargs,
        ),
        GEval(
            name="Citation Compliance",
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
            ],
            criteria=(
                "Score whether the answer includes farmer-facing source attribution for factual "
                "guidance and avoids fabricated or tool-internal citations."
            ),
            threshold=0.60,
            **geval_kwargs,
        ),
        GEval(
            name="Actionability",
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
            ],
            criteria="Score whether the answer gives practical, concrete next steps a farmer can act on.",
            threshold=0.70,
            **geval_kwargs,
        ),
        GEval(
            name="Safety Handling",
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
            ],
            criteria=(
                "Score whether the answer handles safety appropriately by advising veterinary help "
                "for severe cases without over-escalating routine ones."
            ),
            threshold=0.70,
            **geval_kwargs,
        ),
    ]


def _build_candidate_cases(baseline_summary: dict[str, Any]) -> list[LLMTestCase]:
    expected_by_input = _load_expected_output_map()
    test_cases: list[LLMTestCase] = []

    for case in tqdm(baseline_summary["cases"], desc="Generate Test Cases..."):
        input_text = case["input"]
        expected_output = expected_by_input.get(input_text)
        if not expected_output:
            raise RuntimeError(f"Missing expected output for input: {input_text}")

        actual_output, call_meta = _call_chat(input_text)
        test_cases.append(
            LLMTestCase(
                name=case["name"],
                input=input_text,
                actual_output=actual_output,
                expected_output=expected_output,
                additional_metadata={
                    "mode": "candidate_live",
                    **call_meta,
                },
                completion_time=call_meta["latency_ms"] / 1000.0,
            )
        )

    return test_cases


def _summarize_candidate(
    result: Any, identifier: str, baseline_summary: dict[str, Any]
) -> dict[str, Any]:
    metric_scores: dict[str, list[float]] = {}
    cases = []

    for test_result in result.test_results:
        case_metrics = {}
        failed_metrics = []
        for metric in test_result.metrics_data or []:
            score = float(metric.score) if metric.score is not None else None
            case_metrics[metric.name] = {
                "score": score,
                "success": bool(metric.success),
                "threshold": float(metric.threshold),
                "reason": metric.reason,
            }
            if score is not None:
                metric_scores.setdefault(metric.name, []).append(score)
            if not metric.success:
                failed_metrics.append(metric.name)

        cases.append(
            {
                "name": test_result.name,
                "input": test_result.input,
                "failed_metrics": failed_metrics,
                "metrics": case_metrics,
            }
        )

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "candidate_live",
        "identifier": identifier,
        "dataset_alias": baseline_summary["dataset_alias"],
        "sample_limit": len(result.test_results),
        "subject_model": _candidate_model_label(),
        "judge_model": JUDGE_MODEL,
        "test_run_id": result.test_run_id,
        "confident_link": result.confident_link,
        "metrics": {
            name: {
                "mean": round(mean(scores), 4),
                "min": round(min(scores), 4),
                "max": round(max(scores), 4),
                "count": len(scores),
            }
            for name, scores in sorted(metric_scores.items())
        },
        "cases": cases,
    }

    _artifact_path("confident_ai_candidate_live_latest.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    return summary


def _metric_mean(summary: dict[str, Any], axis_name: str) -> float:
    metric_key = METRIC_KEYS[axis_name]
    metric = summary["metrics"].get(metric_key)
    if not metric:
        raise RuntimeError(
            f"Metric '{metric_key}' missing from {summary['mode']} summary."
        )
    return float(metric["mean"])


def _reference_quality_failures(
    summary: dict[str, Any], threshold: float = 0.75
) -> int:
    failures = 0
    metric_key = METRIC_KEYS["Reference Quality"]
    for case in summary["cases"]:
        metric = case["metrics"].get(metric_key)
        if (
            metric
            and metric.get("score") is not None
            and float(metric["score"]) < threshold
        ):
            failures += 1
    return failures


def _gate_errors(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    errors = []
    answer_relevancy = _metric_mean(candidate, "Answer Relevancy")
    prompt_alignment = _metric_mean(candidate, "Prompt Alignment")
    reference_quality = _metric_mean(candidate, "Reference Quality")

    if answer_relevancy < 0.85:
        errors.append(f"Answer Relevancy mean {answer_relevancy:.3f} is below 0.85.")
    if prompt_alignment < 0.75:
        errors.append(f"Prompt Alignment mean {prompt_alignment:.3f} is below 0.75.")
    if reference_quality < 0.80:
        errors.append(f"Reference Quality mean {reference_quality:.3f} is below 0.80.")
    if _reference_quality_failures(candidate) > 3:
        errors.append("Reference Quality has more than 3 cases below 0.75.")
    if answer_relevancy < _metric_mean(baseline, "Answer Relevancy") - 0.05:
        errors.append("Answer Relevancy regressed by more than 0.05 vs baseline.")
    if prompt_alignment < _metric_mean(baseline, "Prompt Alignment") - 0.05:
        errors.append("Prompt Alignment regressed by more than 0.05 vs baseline.")

    return errors


def _polar_point(
    center_x: float, center_y: float, radius: float, angle: float
) -> tuple[float, float]:
    return center_x + radius * math.cos(angle), center_y + radius * math.sin(angle)


def _polygon_points(
    values: list[float], center_x: float, center_y: float, radius: float
) -> str:
    points = []
    total = len(values)
    for index, value in enumerate(values):
        angle = -math.pi / 2 + (2 * math.pi * index / total)
        x, y = _polar_point(center_x, center_y, radius * value, angle)
        points.append(f"{x:.2f},{y:.2f}")
    return " ".join(points)


def _write_comparison_spider(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> None:
    width = 980
    height = 780
    center_x = 305
    center_y = 420
    radius = 185
    axes = [
        ("Answer\nRelevancy", "Answer Relevancy"),
        ("Prompt\nAlignment", "Prompt Alignment"),
        ("Reference\nQuality", "Reference Quality"),
        ("Citation\nCompliance", "Citation Compliance"),
        ("Actionability", "Actionability"),
        ("Safety\nHandling", "Safety Handling"),
    ]
    baseline_values = [_metric_mean(baseline, axis_key) for _, axis_key in axes]
    candidate_values = [_metric_mean(candidate, axis_key) for _, axis_key in axes]

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f6f3eb" />',
        '<text x="40" y="50" font-family="Georgia, serif" font-size="30" fill="#111827">Haiku vs Localhost Spider Chart</text>',
        f'<text x="40" y="80" font-family="Georgia, serif" font-size="15" fill="#4b5563">Dataset: {escape(candidate["dataset_alias"])} | Samples: {candidate["sample_limit"]}</text>',
        f'<text x="40" y="102" font-family="Georgia, serif" font-size="15" fill="#4b5563">Baseline: {escape(baseline["identifier"])} | Candidate: {escape(candidate["identifier"])}</text>',
    ]

    for level in (0.25, 0.5, 0.75, 1.0):
        lines.append(
            f'<polygon points="{_polygon_points([level] * len(axes), center_x, center_y, radius)}" fill="none" stroke="#d6d3d1" stroke-width="1" />'
        )

    for idx, (label, _) in enumerate(axes):
        angle = -math.pi / 2 + (2 * math.pi * idx / len(axes))
        end_x, end_y = _polar_point(center_x, center_y, radius, angle)
        label_x, label_y = _polar_point(center_x, center_y, radius + 56, angle)
        anchor = "middle"
        if label_x < center_x - 25:
            anchor = "end"
        elif label_x > center_x + 25:
            anchor = "start"

        lines.append(
            f'<line x1="{center_x}" y1="{center_y}" x2="{end_x:.2f}" y2="{end_y:.2f}" stroke="#d6d3d1" stroke-width="1" />'
        )
        lines.append(
            f'<text x="{label_x:.2f}" y="{label_y:.2f}" text-anchor="{anchor}" font-family="Georgia, serif" font-size="15" fill="#111827">'
        )
        parts = label.split("\n")
        if len(parts) == 1:
            lines.append(
                f'  <tspan x="{label_x:.2f}" dy="0">{escape(parts[0])}</tspan>'
            )
        else:
            for part_index, part in enumerate(parts):
                dy = -7 if part_index == 0 else 18
                lines.append(
                    f'  <tspan x="{label_x:.2f}" dy="{dy}">{escape(part)}</tspan>'
                )
        lines.append("</text>")

    lines.append(
        f'<polygon points="{_polygon_points(baseline_values, center_x, center_y, radius)}" fill="#c96f4a33" stroke="#c96f4a" stroke-width="3" />'
    )
    lines.append(
        f'<polygon points="{_polygon_points(candidate_values, center_x, center_y, radius)}" fill="#0f766e33" stroke="#0f766e" stroke-width="3" />'
    )

    legend_x = 630
    legend_y = 170
    lines.extend(
        [
            f'<rect x="{legend_x}" y="{legend_y}" width="22" height="22" fill="#c96f4a33" stroke="#c96f4a" stroke-width="3" />',
            f'<text x="{legend_x + 34}" y="{legend_y + 16}" font-family="Georgia, serif" font-size="17" fill="#111827">Old Haiku Baseline</text>',
            f'<rect x="{legend_x}" y="{legend_y + 36}" width="22" height="22" fill="#0f766e33" stroke="#0f766e" stroke-width="3" />',
            f'<text x="{legend_x + 34}" y="{legend_y + 52}" font-family="Georgia, serif" font-size="17" fill="#111827">Current Localhost Model</text>',
        ]
    )

    lines.append("</svg>")
    _artifact_path("confident_ai_comparison_spider.svg").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _format_gate_errors(errors: list[str]) -> str:
    return "\n".join(f"- {error}" for error in errors)


def test_confident_ai_candidate_live_against_baseline(pytestconfig):
    phone = pytestconfig.getoption("phone")
    if phone:
        os.environ["EVAL_PHONE"] = str(phone)

    baseline_summary = _load_baseline_summary()
    candidate_identifier = (
        f"{_candidate_model_label().replace(':', '-')}-{_timestamp()}"
    )

    test_cases = _build_candidate_cases(baseline_summary)
    result = evaluate(
        test_cases=test_cases,
        metrics=_build_metrics(),
        identifier=candidate_identifier,
        display_config=DisplayConfig(show_indicator=True, print_results=True),
    )
    candidate_summary = _summarize_candidate(
        result, candidate_identifier, baseline_summary
    )

    comparison_summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_alias": candidate_summary["dataset_alias"],
        "sample_limit": candidate_summary["sample_limit"],
        "baseline": baseline_summary,
        "candidate": candidate_summary,
        "deltas": {
            axis_name: round(
                _metric_mean(candidate_summary, axis_name)
                - _metric_mean(baseline_summary, axis_name),
                4,
            )
            for axis_name in METRIC_KEYS
        },
        "gates": {
            "errors": _gate_errors(baseline_summary, candidate_summary),
        },
    }
    comparison_summary["gates"]["passed"] = not comparison_summary["gates"]["errors"]

    _artifact_path("confident_ai_comparison_summary.json").write_text(
        json.dumps(comparison_summary, indent=2),
        encoding="utf-8",
    )
    _write_comparison_spider(baseline_summary, candidate_summary)

    if comparison_summary["gates"]["passed"]:
        return

    pytest.fail(
        "Confident AI localhost comparison gates failed:\n"
        f"{_format_gate_errors(comparison_summary['gates']['errors'])}"
    )
