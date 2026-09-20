"""Local, bounded decision primitives backed by a small Ollama model.

Royal Reflex is intentionally not an agent: it turns validated, closed model
tokens into Choice, Score and Noul results and exposes no action capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from integrations.ollama_client import OllamaClient, OllamaError


class ReflexError(RuntimeError):
    pass


@dataclass(frozen=True)
class Choice:
    choice: str
    confidence: float
    probabilities: None = None  # Ollama's local API does not expose logprobs.


@dataclass(frozen=True)
class Score:
    level: int
    normalized: float
    confidence: float


@dataclass(frozen=True)
class Noul:
    noul: float


class RoyalReflex:
    """Parses a deliberately tiny line protocol, never arbitrary model JSON."""
    VERSION = "reflex-v1"
    ANGLES = {"taste", "adjacent", "surprise"}

    def __init__(self, client: OllamaClient): self.client = client

    @staticmethod
    def _confidence(level: int) -> float:
        # A transparent separation proxy, not a probability or correctness claim.
        return round(0.5 + 0.5 * abs(level - 2) / 2, 2)

    def evaluate(self, state: dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        if not questions: return {}
        lines = self.client.decide(state, questions)
        answers: dict[str, Any] = {}
        for line in lines.splitlines():
            parts = [part.strip() for part in line.split("|")]
            if len(parts) != 4: continue
            key, raw_score, raw_angle, raw_noul = parts
            question = questions.get(key)
            if not question or question.get("type") != "reflex": continue
            try:
                level, noul = int(raw_score), float(raw_noul)
            except ValueError:
                continue
            if level not in range(5) or raw_angle not in self.ANGLES or not 0 <= noul <= 1:
                continue
            answers[key] = {
                "choice": Choice(raw_angle, self._confidence(level)).__dict__,
                "score": Score(level, round(level / 4 * 100, 2), self._confidence(level)).__dict__,
                "noul": Noul(noul).__dict__,
            }
        if not answers: raise ReflexError("Royal Reflex hat keine gültigen Entscheidungen erhalten.")
        return answers
