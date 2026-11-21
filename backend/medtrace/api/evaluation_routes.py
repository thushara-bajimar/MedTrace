"""Evaluation and review-time study endpoints."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..db import connection, new_id, now_iso, one, rows, transaction
from ..security import User, current_user, require_admin, require_patient

router = APIRouter(prefix="/api", tags=["evaluation"])


class SessionStartIn(BaseModel):
    patient_id: str = Field(max_length=64)
    mode: Literal["baseline_raw_documents", "medtrace"]


class SessionFinishIn(BaseModel):
    answers: dict = Field(default_factory=dict)
    corrections_made: int = 0


@router.post("/evaluation/run")
def run_eval(_: User = Depends(require_admin)):
    from ..evaluation.runner import run_evaluation

    return run_evaluation()


@router.get("/evaluation/latest")
def latest(_: User = Depends(current_user)):
    with connection() as conn:
        r = one(conn, "SELECT * FROM evaluation_runs ORDER BY created_at DESC LIMIT 1", json_fields=("metrics_json",))
    if r is None:
        raise HTTPException(404, "No evaluation has been run yet. Run: python -m medtrace.evaluation.runner")
    return r


@router.get("/evaluation/runs")
def runs(_: User = Depends(current_user)):
    with connection() as conn:
        return rows(conn, "SELECT id, created_at, dataset_version, extractor_version, duration_ms FROM evaluation_runs ORDER BY created_at DESC")


def _metric(path: list[str]):
    r = latest()
    m = r["metrics_json"]
    for p in path:
        m = m.get(p, {})
    return m


@router.get("/evaluation/extraction")
def extraction(_: User = Depends(current_user)):
    return _metric(["extraction"])


@router.get("/evaluation/precision-recall")
def precision_recall(_: User = Depends(current_user)):
    ex = _metric(["extraction"])
    return {k: {m: v.get(m) for m in ("precision", "recall", "f1", "tp", "fp", "fn")} for k, v in ex.get("entity", {}).items()}


@router.get("/evaluation/f1")
def f1(_: User = Depends(current_user)):
    ex = _metric(["extraction"])
    return {"micro_f1": ex.get("micro", {}).get("f1"), "per_type": {k: v.get("f1") for k, v in ex.get("entity", {}).items()}}


@router.get("/evaluation/review-time")
def review_time(_: User = Depends(current_user)):
    return {"automated_proxy": _metric(["review_time"]), "sessions": list_sessions(_)}


@router.get("/evaluation/comparison")
def comparison(_: User = Depends(current_user)):
    return _metric(["review_time"])


# ---------------------------------------------------------------- human review-time sessions
TASKS = [
    "List every medication documented, with strength and documented status.",
    "List every allergy statement, including explicit negatives.",
    "State the most recent documented laboratory test date.",
    "Identify any conflicting statements across documents.",
]


@router.get("/review-sessions/tasks")
def tasks(_: User = Depends(current_user)):
    return {"tasks": TASKS}


@router.post("/review-sessions", status_code=201)
def start_session(body: SessionStartIn, user: User = Depends(current_user)):
    with transaction() as conn:
        require_patient(conn, user, body.patient_id)
        sid = new_id("rvs")
        conn.execute("INSERT INTO review_sessions (id, user_id, patient_id, mode, participant_kind, started_at, tasks_total) VALUES (?,?,?,?, 'human', ?, ?)",
                     (sid, user.id, body.patient_id, body.mode, now_iso(), len(TASKS)))
    return {"id": sid, "tasks": TASKS, "mode": body.mode}


@router.post("/review-sessions/{sid}/finish")
def finish_session(sid: str, body: SessionFinishIn, user: User = Depends(current_user)):
    from datetime import datetime

    from ..evaluation.runner import score_review_answers

    with transaction() as conn:
        s = one(conn, "SELECT * FROM review_sessions WHERE id=? AND user_id=?", (sid, user.id))
        if s is None:
            raise HTTPException(404, "Session not found.")
        if s["finished_at"]:
            raise HTTPException(409, "Session already finished.")
        dur = (datetime.fromisoformat(now_iso()) - datetime.fromisoformat(s["started_at"])).total_seconds()
        score = score_review_answers(conn, s["patient_id"], body.answers)
        conn.execute("""UPDATE review_sessions SET finished_at=?, duration_seconds=?, tasks_correct=?, missed_findings=?, corrections_made=?, answers_json=?
                        WHERE id=?""", (now_iso(), dur, score["correct"], score["missed"], body.corrections_made, json.dumps(body.answers), sid))
    return {"id": sid, "duration_seconds": dur, **score}


@router.get("/review-sessions")
def list_sessions(user: User = Depends(current_user)):
    with connection() as conn:
        return rows(conn, "SELECT id, patient_id, mode, participant_kind, started_at, finished_at, duration_seconds, tasks_total, tasks_correct, missed_findings, corrections_made FROM review_sessions ORDER BY started_at DESC")
