"""Pure explainable eligibility and ranking; hard constraints precede scores."""

from __future__ import annotations

from storage.storage_policy import GIB


def storage_pressure(root: dict, policy: dict, reserved: int = 0) -> str:
    if not root.get("available"):
        return "offline"
    free = int(root.get("free_bytes", 0)) - reserved
    total = int(root.get("total_bytes", 0))
    percent = 100 * (total - free) / total if total else 100
    if free <= 0:
        return "emergency"
    if free < policy["reserve_gib"] * GIB or percent >= policy["critical_percent"]:
        return "critical"
    if percent >= policy["warning_percent"]:
        return "warning"
    return "normal"


def score_target(root: dict, policy: dict, *, media_type: str, size: int,
                 reserved: int = 0, affinity: bool = False, busy: int = 0,
                 overflow: bool = False) -> dict:
    reasons = []
    total = int(root.get("total_bytes", 0))
    free_after = int(root.get("free_bytes", 0)) - reserved - size
    percent_after = 100 * (total - free_after) / total if total else 100
    blocked = (
        (not root.get("available"), "Speicherort offline"),
        (not root.get("writable", False), "Speicherort nicht beschreibbar"),
        (root.get("location_mode") != "media" or policy["role"] == "monitor", "Nur überwachen"),
        (media_type not in policy["media_types"], "Medienart nicht freigegeben"),
        (free_after < policy["reserve_gib"] * GIB, "Mindestreserve unterschritten"),
        (percent_after >= policy["critical_percent"], "Kritische Auslastung"),
    )
    reason = next((reason for condition, reason in blocked if condition), "")
    if reason:
        return {"root": root["key"], "eligible": False, "score": None,
                "reasons": [reason], "free_after_bytes": free_after}
    score = 45 + max(0, 25 * (100 - percent_after) / 100) - min(20, busy * 5)
    reasons.append("Genügend freie Sicherheitsreserve")
    if policy["role"] == "primary":
        score += 20
        reasons.append("Bevorzugter Primärspeicher")
    elif policy["role"] == "overflow":
        score += 25 if overflow else -10
        reasons.append("Ausweichspeicher nötig" if overflow else "Ausweichspeicher bleibt Reserve")
    elif policy["role"] == "archive":
        score -= 25
        reasons.append("Archiv bleibt bevorzugt für ältere Inhalte")
    if percent_after > policy["target_percent"]:
        score -= 30
        reasons.append("Oberhalb der Zielauslastung")
    else:
        reasons.append("Unterhalb der Zielauslastung")
    if affinity:
        score += 40
        reasons.append("Serie liegt bereits auf diesem Volume")
    if reserved:
        reasons.append("Geplante Downloads und Verschiebungen berücksichtigt")
    if busy:
        reasons.append("Laufende Speicherjobs berücksichtigt")
    return {"root": root["key"], "eligible": True, "score": round(score, 2),
            "reasons": reasons, "free_after_bytes": free_after,
            "expected_percent": round(percent_after, 2)}
