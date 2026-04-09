# dashboard/services/memory_service.py
"""
Case Memory System — tenant-scoped, persistent, learning from past cases.

The memory system stores resolved case fingerprints so the system can:
  1. Find similar past cases when an operator opens a new one
  2. Show what decision was made and what the outcome was
  3. Suggest actions based on historical outcomes

Fingerprint shape:
{
  "fingerprint_id": str,
  "tenant_id":      str,
  "case_id":        str,
  "classification": str,
  "action":         str,
  "risk_level":     str,
  "risk_score":     float,
  "overdue_days":   int,
  "overdue_amount": float,
  "has_policy":     bool,
  "has_legal_action": bool,
  "outcome":        str | None,   # "resolved" | "escalated" | "overridden" | None
  "outcome_days":   int | None,   # days from creation to resolution
  "was_overridden": bool,
  "rule_id":        str,
  "created_at":     str,
}

Backend endpoints:
  POST /memory/fingerprints         → store a resolved case
  GET  /memory/similar?case_id=...  → find similar past cases
  GET  /memory/summary              → aggregate stats for improvement visibility
  POST /memory/outcome              → update outcome after resolution

Client-side fallback: if the backend doesn't support /memory endpoints,
similarity is computed locally from session state (best-effort for demo tenants).
"""
from __future__ import annotations

import logging
import math
from typing import Optional

import streamlit as st

from services.api_client import AuthError, NetworkError, get_client

logger = logging.getLogger(__name__)

_SIMILARITY_THRESHOLD = 0.65   # 0–1, cases above this score are "similar"
_MAX_SIMILAR_RESULTS  = 5


def _client():
    token = st.session_state.get("auth_token")
    cache = st.session_state.setdefault("api_cache", {})
    return get_client(token=token, session_cache=cache)


def _tenant_id() -> Optional[str]:
    return st.session_state.get("auth_user", {}).get("tenant_id")


class MemoryService:

    # ── Write ──────────────────────────────────────────────────────────────────

    def store_fingerprint(self, case: dict, decision: dict) -> Optional[str]:
        """
        POST /memory/fingerprints
        Called after evaluation or resolution. Non-critical — never raises.
        Returns fingerprint_id or None.
        """
        body = _build_fingerprint(case, decision)
        try:
            resp = _client().post("/memory/fingerprints", json=body)
            if resp.ok and isinstance(resp.data, dict):
                fp_id = resp.data.get("fingerprint_id")
                _append_session_memory(body)   # local cache for same-session similarity
                return fp_id
            logger.warning("Memory store failed: %s", resp.error)
        except Exception as exc:
            logger.warning("Memory store error: %s", exc)
        _append_session_memory(body)
        return None

    def update_outcome(
        self,
        case_id:    str,
        outcome:    str,
        outcome_days: Optional[int] = None,
    ) -> None:
        """
        POST /memory/outcome — update the outcome of a previously stored fingerprint.
        Non-critical — never raises.
        """
        try:
            _client().post("/memory/outcome", json={
                "case_id":      case_id,
                "outcome":      outcome,
                "outcome_days": outcome_days,
                "tenant_id":    _tenant_id(),
            })
        except Exception as exc:
            logger.warning("Memory outcome update error: %s", exc)

    # ── Read ───────────────────────────────────────────────────────────────────

    def get_similar(self, case: dict, limit: int = _MAX_SIMILAR_RESULTS) -> list[dict]:
        """
        GET /memory/similar?case_id=...&limit=N
        Returns list of similar past cases (fingerprints + similarity_score).
        Falls back to client-side similarity if endpoint is unavailable.
        """
        try:
            resp = _client().get(
                "/memory/similar",
                params={"case_id": case.get("id", ""), "limit": limit},
                ttl=120,
            )
            if resp.ok:
                items = resp.items or (resp.data if isinstance(resp.data, list) else [])
                if items:
                    return items[:limit]
        except Exception:
            pass

        # Client-side fallback: compare against session memory
        return _local_similar(case, limit)

    def get_memory_summary(self) -> tuple[Optional[dict], Optional[str]]:
        """
        GET /memory/summary
        Returns aggregate learning stats.
        Shape: {
          "total_fingerprints": int,
          "outcomes_recorded":  int,
          "most_common_action": str,
          "override_rate":      float,
          "avg_outcome_days":   float,
          "period_days":        int,
        }
        """
        try:
            resp = _client().get("/memory/summary", ttl=120)
        except AuthError as e:
            return None, str(e)
        except NetworkError as e:
            return None, f"Sin conexión: {e}"

        if not resp.ok:
            return None, resp.error or "Error al cargar memoria del sistema"

        return resp.data, None


# ── Fingerprint builder ───────────────────────────────────────────────────────

def _build_fingerprint(case: dict, decision: dict) -> dict:
    return {
        "tenant_id":       _tenant_id(),
        "case_id":         case.get("id", ""),
        "classification":  decision.get("classification", "OTRO"),
        "action":          decision.get("action", ""),
        "risk_level":      decision.get("risk_level", "BAJO"),
        "risk_score":      float(decision.get("risk_score", 0)),
        "overdue_days":    int(case.get("overdue_days", 0)),
        "overdue_amount":  float(case.get("overdue_amount", 0)),
        "has_policy":      bool(case.get("has_policy", False)),
        "has_legal_action": bool(case.get("has_legal_action", False)),
        "outcome":         None,
        "outcome_days":    None,
        "was_overridden":  bool(decision.get("is_overridden", False)),
        "rule_id":         decision.get("rule_id", ""),
        "created_at":      case.get("created_at", ""),
    }


# ── Session-local memory (same-session fallback) ──────────────────────────────

_SESSION_MEMORY_KEY = "_case_memory_fingerprints"


def _append_session_memory(fp: dict) -> None:
    mem: list = st.session_state.get(_SESSION_MEMORY_KEY) or []
    # Deduplicate by case_id
    mem = [m for m in mem if m.get("case_id") != fp.get("case_id")]
    mem.append(fp)
    # Cap at 200 entries
    st.session_state[_SESSION_MEMORY_KEY] = mem[-200:]


def _local_similar(case: dict, limit: int) -> list[dict]:
    """
    Client-side cosine-style similarity using 5 case dimensions.
    Used when backend /memory/similar is unavailable.
    """
    mem: list = st.session_state.get(_SESSION_MEMORY_KEY) or []
    if not mem:
        return []

    current_id = case.get("id", "")
    scored: list[tuple[float, dict]] = []

    for fp in mem:
        if fp.get("case_id") == current_id:
            continue
        score = _similarity_score(case, fp)
        if score >= _SIMILARITY_THRESHOLD:
            scored.append((score, {**fp, "similarity_score": round(score, 3)}))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:limit]]


def _similarity_score(case: dict, fp: dict) -> float:
    """
    Compute a 0–1 similarity score between a live case and a memory fingerprint.
    Weighted across 5 dimensions.
    """
    scores: list[tuple[float, float]] = []   # (value, weight)

    # 1. Risk level match (exact) — weight 0.25
    risk_match = 1.0 if case.get("risk_level") == fp.get("risk_level") else 0.0
    scores.append((risk_match, 0.25))

    # 2. Overdue days proximity — weight 0.20
    cur_days = float(case.get("overdue_days") or 0)
    fp_days  = float(fp.get("overdue_days") or 0)
    day_sim  = _numeric_similarity(cur_days, fp_days, scale=180)
    scores.append((day_sim, 0.20))

    # 3. Amount proximity — weight 0.20
    cur_amt = float(case.get("overdue_amount") or 0)
    fp_amt  = float(fp.get("overdue_amount") or 0)
    amt_sim = _numeric_similarity(cur_amt, fp_amt, scale=5_000_000)
    scores.append((amt_sim, 0.20))

    # 4. Has policy match — weight 0.15
    policy_match = 1.0 if bool(case.get("has_policy")) == bool(fp.get("has_policy")) else 0.0
    scores.append((policy_match, 0.15))

    # 5. Legal flag match — weight 0.20
    legal_match = 1.0 if bool(case.get("has_legal_action")) == bool(fp.get("has_legal_action")) else 0.0
    scores.append((legal_match, 0.20))

    total = sum(v * w for v, w in scores)
    total_weight = sum(w for _, w in scores)
    return total / total_weight if total_weight > 0 else 0.0


def _numeric_similarity(a: float, b: float, scale: float) -> float:
    """Gaussian similarity: 1.0 when identical, decays with distance."""
    if scale <= 0:
        return 1.0
    diff = abs(a - b) / scale
    return math.exp(-3 * diff * diff)
