from __future__ import annotations

import math
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Experiment, ExperimentResult


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _z_test(p1: float, p2: float, n1: int, n2: int) -> float:
    if n1 == 0 or n2 == 0:
        return 1.0
    pooled = ((p1 * n1) + (p2 * n2)) / (n1 + n2)
    if pooled in (0, 1):
        return 1.0
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = (p1 - p2) / se
    p_value = 2 * (1 - _normal_cdf(abs(z)))
    return p_value


def evaluate_if_ready(db: Session, experiment_id: uuid.UUID) -> dict[str, Any] | None:
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        return None

    results = (
        db.execute(
            select(ExperimentResult)
            .where(ExperimentResult.experiment_id == experiment_id)
            .order_by(ExperimentResult.window_start.asc())
        )
        .scalars()
        .all()
    )
    if not results:
        return None

    variants = {}
    for result in results:
        res_variants = result.results_json.get("variants", {})
        for name, payload in res_variants.items():
            totals = payload.get("totals", {})
            variants.setdefault(name, {"clicks": 0, "conversions": 0, "spend": Decimal("0")})
            variants[name]["clicks"] += int(totals.get("clicks", 0))
            variants[name]["conversions"] += int(totals.get("conversions", 0))
            variants[name]["spend"] += _to_decimal(totals.get("spend", 0))

    if len(variants) != 2:
        analysis = {
            "ready": False,
            "primary_metric": experiment.primary_metric,
            "decision": "inconclusive",
            "winner": None,
            "confidence": float(experiment.confidence),
            "notes": ["not_supported_multi_variant"],
        }
        results[-1].analysis_json = analysis
        db.commit()
        return analysis

    names = sorted(variants.keys())
    a, b = names[0], names[1]

    total_conversions = variants[a]["conversions"] + variants[b]["conversions"]
    per_variant_floor = max(1, experiment.min_sample_conversions // 4)
    ready = total_conversions >= experiment.min_sample_conversions and all(
        variants[name]["conversions"] >= per_variant_floor for name in names
    )

    variant_stats = {
        name: {
            "clicks": stats["clicks"],
            "conversions": stats["conversions"],
            "spend": float(stats["spend"]),
        }
        for name, stats in variants.items()
    }

    analysis = {
        "ready": ready,
        "primary_metric": experiment.primary_metric,
        "variant_stats": variant_stats,
        "winner": None,
        "decision": "continue",
        "confidence": float(experiment.confidence),
        "notes": [],
    }

    if not ready:
        results[-1].analysis_json = analysis
        db.commit()
        return analysis

    if experiment.primary_metric != "cvr":
        analysis["decision"] = "inconclusive"
        analysis["notes"].append("metric_not_supported_v1")
        results[-1].analysis_json = analysis
        db.commit()
        return analysis

    p1 = variants[a]["conversions"] / max(1, variants[a]["clicks"])
    p2 = variants[b]["conversions"] / max(1, variants[b]["clicks"])
    p_value = _z_test(p1, p2, variants[a]["clicks"], variants[b]["clicks"])
    effect_size = p2 - p1

    analysis.update(
        {
            "effect_size": effect_size,
            "p_value": p_value,
        }
    )

    alpha = 1 - float(experiment.confidence)
    if p_value <= alpha:
        winner = b if p2 > p1 else a
        analysis["winner"] = winner
        analysis["decision"] = "declare_winner"
        experiment.status = "completed"
    else:
        analysis["decision"] = "inconclusive"

    results[-1].analysis_json = analysis
    db.commit()
    return analysis
