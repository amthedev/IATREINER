from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


DEFAULT_SERVER_URL = "https://ia-treiner.squareweb.app"
VOLUNTEER_INVITE_TOKEN = "Urw9guyr50YyrvAoKL7ySnmacI0yuTWSC6g-6b6_D9U"
ADMIN_TOKEN = "IHybFWKOukrIoNex4j9q0Va12yUqLSQEbUu6QNNjuac"
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "data/iatreiner.sqlite3"))
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
db_lock = threading.Lock()


def now() -> float:
    return time.time()


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(10)}"


def db_connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with db_lock, db_connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS workers (
                worker_id TEXT PRIMARY KEY,
                worker_token TEXT NOT NULL,
                display_name TEXT NOT NULL,
                device_info TEXT NOT NULL,
                registered_at REAL NOT NULL,
                last_seen_at REAL NOT NULL,
                status TEXT NOT NULL,
                cpu_limit_percent INTEGER NOT NULL,
                allow_gpu INTEGER NOT NULL,
                consent_text_accepted INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                target_worker_id TEXT,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL,
                worker_id TEXT,
                output TEXT,
                error TEXT
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at)")
        connection.commit()


init_db()


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


def row_to_worker(row: sqlite3.Row) -> dict[str, Any]:
    worker = dict(row)
    worker["device_info"] = json.loads(worker["device_info"])
    worker["allow_gpu"] = bool(worker["allow_gpu"])
    worker["consent_text_accepted"] = bool(worker["consent_text_accepted"])
    return worker


def row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    job = dict(row)
    job["payload"] = json.loads(job["payload"])
    job["output"] = json.loads(job["output"]) if job.get("output") else None
    return job


def get_worker(connection: sqlite3.Connection, worker_id: str, worker_token: str) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM workers WHERE worker_id = ?", (worker_id,)).fetchone()
    worker = row_to_worker(row) if row else None
    if not worker or not secrets.compare_digest(worker.get("worker_token", ""), worker_token):
        raise HTTPException(status_code=401, detail="worker token invalido")
    return worker


def save_job_result(
    connection: sqlite3.Connection,
    job_id: str,
    status: str,
    output: dict[str, Any],
    error_message: str | None,
) -> None:
    connection.execute(
        """
        UPDATE jobs
        SET status = ?, finished_at = ?, output = ?, error = ?
        WHERE job_id = ?
        """,
        (status, now(), json.dumps(output), error_message, job_id),
    )


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "IATREINER", "status": "online", "health": "/health"}


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
    registered_at = now()
    with db_lock, db_connect() as connection:
        connection.execute(
            """
            INSERT INTO workers (
                worker_id, worker_token, display_name, device_info, registered_at,
                last_seen_at, status, cpu_limit_percent, allow_gpu, consent_text_accepted
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                worker_id,
                worker_token,
                request.display_name,
                json.dumps(request.device_info),
                registered_at,
                registered_at,
                "idle",
                50,
                int(bool(request.device_info.get("allow_gpu", False))),
                1,
            ),
        )
        connection.commit()
    return RegisterResponse(worker_id=worker_id, worker_token=worker_token)


@app.post("/api/workers/{worker_id}/heartbeat")
def heartbeat(worker_id: str, request: HeartbeatRequest) -> dict[str, str]:
    with db_lock, db_connect() as connection:
        get_worker(connection, worker_id, request.worker_token)
        connection.execute(
            """
            UPDATE workers
            SET last_seen_at = ?, status = ?, cpu_limit_percent = ?, allow_gpu = ?
            WHERE worker_id = ?
            """,
            (now(), request.status, request.cpu_limit_percent, int(request.allow_gpu), worker_id),
        )
        connection.commit()
    return {"status": "ok"}


@app.get("/api/workers/{worker_id}/jobs/next")
def next_job(worker_id: str, worker_token: str) -> dict[str, Any]:
    with db_lock, db_connect() as connection:
        worker = get_worker(connection, worker_id, worker_token)
        rows = connection.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY created_at ASC",
            ("pending",),
        ).fetchall()
        for row in rows:
            job = row_to_job(row)
            target = job.get("target_worker_id")
            requires_gpu = bool(job.get("payload", {}).get("require_gpu", False))
            worker_allows_gpu = bool(worker.get("allow_gpu", False))
            if (
                job["status"] == "pending"
                and (target is None or target == worker_id)
                and (not requires_gpu or worker_allows_gpu)
            ):
                started_at = now()
                connection.execute(
                    "UPDATE jobs SET status = ?, worker_id = ?, started_at = ? WHERE job_id = ?",
                    ("running", worker_id, started_at, job["job_id"]),
                )
                connection.commit()
                job["status"] = "running"
                job["worker_id"] = worker_id
                job["started_at"] = started_at
                return {"job": public_job(job)}
    return {"job": None}


@app.post("/api/workers/{worker_id}/jobs/{job_id}/result")
def submit_result(worker_id: str, job_id: str, request: JobResultRequest) -> dict[str, str]:
    with db_lock, db_connect() as connection:
        get_worker(connection, worker_id, request.worker_token)
        row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="job nao encontrado")
        job = row_to_job(row)
        if job.get("worker_id") != worker_id:
            raise HTTPException(status_code=403, detail="job pertence a outro worker")
        save_job_result(connection, job_id, request.status, request.output, request.error)
        connection.commit()
    return {"status": "ok"}


@app.get("/api/admin/workers", dependencies=[Depends(require_admin)])
def admin_workers() -> dict[str, list[dict[str, Any]]]:
    with db_lock, db_connect() as connection:
        workers = []
        for row in connection.execute("SELECT * FROM workers ORDER BY registered_at DESC").fetchall():
            worker = row_to_worker(row)
            visible = {k: v for k, v in worker.items() if k != "worker_token"}
            visible["online"] = now() - float(worker.get("last_seen_at", 0)) < 30
            workers.append(visible)
    return {"workers": workers}


@app.post("/api/admin/jobs", dependencies=[Depends(require_admin)])
def submit_job(request: JobSubmitRequest) -> dict[str, Any]:
    if request.job_type not in ALLOWED_JOB_TYPES:
        raise HTTPException(status_code=400, detail="tipo de job nao permitido")

    job_id = new_id("job")
    payload = sanitize_payload(request.job_type, request.payload)
    job = {
        "job_id": job_id,
        "job_type": request.job_type,
        "payload": payload,
        "target_worker_id": request.target_worker_id,
        "status": "pending",
        "created_at": now(),
        "worker_id": None,
        "output": None,
        "error": None,
    }
    with db_lock, db_connect() as connection:
        connection.execute(
            """
            INSERT INTO jobs (
                job_id, job_type, payload, target_worker_id, status, created_at,
                started_at, finished_at, worker_id, output, error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                request.job_type,
                json.dumps(payload),
                request.target_worker_id,
                "pending",
                job["created_at"],
                None,
                None,
                None,
                None,
                None,
            ),
        )
        connection.commit()
    return {"job": public_job(job)}


@app.get("/api/admin/jobs", dependencies=[Depends(require_admin)])
def admin_jobs() -> dict[str, list[dict[str, Any]]]:
    with db_lock, db_connect() as connection:
        rows = connection.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        jobs = [public_job(row_to_job(row)) for row in rows]
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
