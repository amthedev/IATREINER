from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "change-me-admin-token")
VOLUNTEER_INVITE_TOKEN = os.getenv("VOLUNTEER_INVITE_TOKEN", "change-me-invite-token")
STATE_PATH = Path(os.getenv("STATE_PATH", "data/state.json"))
ALLOWED_JOB_TYPES = {
    "hash_benchmark",
    "matrix_benchmark",
    "sleep",
    "generate_embeddings",
    "fine_tune_chunk",
    "evaluate_model",
    "train_lora",
}

app = FastAPI(title="ConsentCompute Relay", version="0.1.0")
state_lock = threading.Lock()


def now() -> float:
    return time.time()


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(10)}"


def empty_state() -> dict[str, Any]:
    return {"workers": {}, "jobs": {}}


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return empty_state()
    with STATE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_PATH.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
    tmp_path.replace(STATE_PATH)


STATE = load_state()


class RegisterRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    invite_token: str = Field(min_length=1, max_length=200)
    consent_text_accepted: bool
    device_info: dict[str, Any] = Field(default_factory=dict)


class RegisterResponse(BaseModel):
    worker_id: str
    worker_token: str


class HeartbeatRequest(BaseModel):
    worker_token: str
    status: Literal["idle", "working", "paused", "stopped"]
    cpu_limit_percent: int = Field(ge=5, le=100)
    allow_gpu: bool = False


class JobSubmitRequest(BaseModel):
    job_type: Literal[
        "hash_benchmark",
        "matrix_benchmark",
        "sleep",
        "generate_embeddings",
        "fine_tune_chunk",
        "evaluate_model",
        "train_lora",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)
    target_worker_id: str | None = None


class JobResultRequest(BaseModel):
    worker_token: str
    status: Literal["completed", "failed", "cancelled"]
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


def require_admin(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {ADMIN_TOKEN}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="admin token invalido")


def get_worker(state: dict[str, Any], worker_id: str, worker_token: str) -> dict[str, Any]:
    worker = state["workers"].get(worker_id)
    if not worker or not secrets.compare_digest(worker.get("worker_token", ""), worker_token):
        raise HTTPException(status_code=401, detail="worker token invalido")
    return worker


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/workers/register", response_model=RegisterResponse)
def register_worker(request: RegisterRequest) -> RegisterResponse:
    if not secrets.compare_digest(request.invite_token, VOLUNTEER_INVITE_TOKEN):
        raise HTTPException(status_code=403, detail="convite invalido")
    if not request.consent_text_accepted:
        raise HTTPException(status_code=400, detail="consentimento obrigatorio")

    worker_id = new_id("worker")
    worker_token = secrets.token_urlsafe(24)
    with state_lock:
        STATE["workers"][worker_id] = {
            "worker_id": worker_id,
            "worker_token": worker_token,
            "display_name": request.display_name,
            "device_info": request.device_info,
            "registered_at": now(),
            "last_seen_at": now(),
            "status": "idle",
            "cpu_limit_percent": 50,
            "allow_gpu": bool(request.device_info.get("allow_gpu", False)),
            "consent_text_accepted": True,
        }
        save_state(STATE)
    return RegisterResponse(worker_id=worker_id, worker_token=worker_token)


@app.post("/api/workers/{worker_id}/heartbeat")
def heartbeat(worker_id: str, request: HeartbeatRequest) -> dict[str, str]:
    with state_lock:
        worker = get_worker(STATE, worker_id, request.worker_token)
        worker["last_seen_at"] = now()
        worker["status"] = request.status
        worker["cpu_limit_percent"] = request.cpu_limit_percent
        worker["allow_gpu"] = request.allow_gpu
        save_state(STATE)
    return {"status": "ok"}


@app.get("/api/workers/{worker_id}/jobs/next")
def next_job(worker_id: str, worker_token: str) -> dict[str, Any]:
    with state_lock:
        get_worker(STATE, worker_id, worker_token)
        for job in STATE["jobs"].values():
            target = job.get("target_worker_id")
            requires_gpu = bool(job.get("payload", {}).get("require_gpu", False))
            worker_allows_gpu = bool(STATE["workers"][worker_id].get("allow_gpu", False))
            if (
                job["status"] == "pending"
                and (target is None or target == worker_id)
                and (not requires_gpu or worker_allows_gpu)
            ):
                job["status"] = "running"
                job["worker_id"] = worker_id
                job["started_at"] = now()
                save_state(STATE)
                return {"job": public_job(job)}
    return {"job": None}


@app.post("/api/workers/{worker_id}/jobs/{job_id}/result")
def submit_result(worker_id: str, job_id: str, request: JobResultRequest) -> dict[str, str]:
    with state_lock:
        get_worker(STATE, worker_id, request.worker_token)
        job = STATE["jobs"].get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job nao encontrado")
        if job.get("worker_id") != worker_id:
            raise HTTPException(status_code=403, detail="job pertence a outro worker")
        job["status"] = request.status
        job["finished_at"] = now()
        job["output"] = request.output
        job["error"] = request.error
        save_state(STATE)
    return {"status": "ok"}


@app.get("/api/admin/workers", dependencies=[Depends(require_admin)])
def admin_workers() -> dict[str, list[dict[str, Any]]]:
    with state_lock:
        workers = []
        for worker in STATE["workers"].values():
            visible = {k: v for k, v in worker.items() if k != "worker_token"}
            visible["online"] = now() - float(worker.get("last_seen_at", 0)) < 30
            workers.append(visible)
    return {"workers": workers}


@app.post("/api/admin/jobs", dependencies=[Depends(require_admin)])
def submit_job(request: JobSubmitRequest) -> dict[str, Any]:
    if request.job_type not in ALLOWED_JOB_TYPES:
        raise HTTPException(status_code=400, detail="tipo de job nao permitido")

    job_id = new_id("job")
    job = {
        "job_id": job_id,
        "job_type": request.job_type,
        "payload": sanitize_payload(request.job_type, request.payload),
        "target_worker_id": request.target_worker_id,
        "status": "pending",
        "created_at": now(),
        "worker_id": None,
        "output": None,
        "error": None,
    }
    with state_lock:
        STATE["jobs"][job_id] = job
        save_state(STATE)
    return {"job": public_job(job)}


@app.get("/api/admin/jobs", dependencies=[Depends(require_admin)])
def admin_jobs() -> dict[str, list[dict[str, Any]]]:
    with state_lock:
        jobs = [public_job(job) for job in STATE["jobs"].values()]
    jobs.sort(key=lambda item: item["created_at"], reverse=True)
    return {"jobs": jobs}


def sanitize_payload(job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if job_type == "hash_benchmark":
        seconds = int(payload.get("seconds", 5))
        return {"seconds": max(1, min(seconds, 60))}
    if job_type == "matrix_benchmark":
        size = int(payload.get("size", 90))
        iterations = int(payload.get("iterations", 2))
        return {"size": max(10, min(size, 180)), "iterations": max(1, min(iterations, 8))}
    if job_type == "sleep":
        seconds = int(payload.get("seconds", 2))
        return {"seconds": max(1, min(seconds, 30))}
    if job_type == "generate_embeddings":
        return sanitize_artifact_payload(
            payload,
            {
                "texts": "list",
                "input_url": "url",
                "output_url": "url",
                "dimensions": "int",
                "require_gpu": "bool",
                "batch_id": "str",
            },
            int_ranges={"dimensions": (8, 512)},
            max_inline_items=200,
        )
    if job_type == "fine_tune_chunk":
        return sanitize_artifact_payload(
            payload,
            {
                "examples": "list",
                "input_url": "url",
                "output_url": "url",
                "learning_rate": "float",
                "epochs": "int",
                "require_gpu": "bool",
                "batch_id": "str",
            },
            int_ranges={"epochs": (1, 20)},
            float_ranges={"learning_rate": (0.0001, 2.0)},
            max_inline_items=1000,
        )
    if job_type == "evaluate_model":
        return sanitize_artifact_payload(
            payload,
            {
                "model": "dict",
                "model_url": "url",
                "examples": "list",
                "input_url": "url",
                "output_url": "url",
                "require_gpu": "bool",
                "batch_id": "str",
            },
            max_inline_items=1000,
        )
    if job_type == "train_lora":
        clean = sanitize_artifact_payload(
            payload,
            {
                "base_model_url": "url",
                "dataset_url": "url",
                "output_url": "url",
                "adapter_name": "str",
                "max_steps": "int",
                "rank": "int",
                "require_gpu": "bool",
                "batch_id": "str",
            },
            int_ranges={"max_steps": (1, 500), "rank": (1, 64)},
        )
        clean["require_gpu"] = True
        return clean
    raise HTTPException(status_code=400, detail="tipo de job nao permitido")


def sanitize_artifact_payload(
    payload: dict[str, Any],
    schema: dict[str, str],
    int_ranges: dict[str, tuple[int, int]] | None = None,
    float_ranges: dict[str, tuple[float, float]] | None = None,
    max_inline_items: int = 200,
) -> dict[str, Any]:
    int_ranges = int_ranges or {}
    float_ranges = float_ranges or {}
    clean: dict[str, Any] = {}
    for key, kind in schema.items():
        if key not in payload or payload[key] is None:
            continue
        value = payload[key]
        if kind == "url":
            clean[key] = sanitize_url(str(value))
        elif kind == "list":
            if not isinstance(value, list):
                raise HTTPException(status_code=400, detail=f"{key} precisa ser lista")
            clean[key] = value[:max_inline_items]
        elif kind == "dict":
            if not isinstance(value, dict):
                raise HTTPException(status_code=400, detail=f"{key} precisa ser objeto")
            clean[key] = value
        elif kind == "int":
            low, high = int_ranges.get(key, (0, 10_000))
            clean[key] = max(low, min(int(value), high))
        elif kind == "float":
            low, high = float_ranges.get(key, (0.0, 1_000.0))
            clean[key] = max(low, min(float(value), high))
        elif kind == "bool":
            clean[key] = bool(value)
        elif kind == "str":
            clean[key] = str(value)[:120]
    return clean


def sanitize_url(value: str) -> str:
    if not value.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="URLs precisam usar http ou https")
    return value[:2000]


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "job_type": job["job_type"],
        "payload": job["payload"],
        "target_worker_id": job.get("target_worker_id"),
        "status": job["status"],
        "created_at": job["created_at"],
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "worker_id": job.get("worker_id"),
        "output": job.get("output"),
        "error": job.get("error"),
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
