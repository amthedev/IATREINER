from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


DEFAULT_SERVER_URL = "https://ia-treiner.squareweb.app"
VOLUNTEER_INVITE_TOKEN = "Urw9guyr50YyrvAoKL7ySnmacI0yuTWSC6g-6b6_D9U"
ADMIN_TOKEN = "IHybFWKOukrIoNex4j9q0Va12yUqLSQEbUu6QNNjuac"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "data/iatreiner.sqlite3"))
DATABASE_SSL_CERT_PEM = os.getenv("DATABASE_SSL_CERT_PEM", "").strip()
DATABASE_SSL_CERT_BASE64 = os.getenv("DATABASE_SSL_CERT_BASE64", "").strip()
DATABASE_SSL_CERT_PATH = os.getenv("DATABASE_SSL_CERT_PATH", "").strip()
DATABASE_SSL_KEY_PATH = os.getenv("DATABASE_SSL_KEY_PATH", "").strip()
DATABASE_SSL_ROOT_CERT_PATH = os.getenv("DATABASE_SSL_ROOT_CERT_PATH", "").strip()
WORKER_OFFLINE_SECONDS = int(os.getenv("WORKER_OFFLINE_SECONDS", "120"))
JOB_LEASE_SECONDS = int(os.getenv("JOB_LEASE_SECONDS", "1800"))
MAX_JOB_ATTEMPTS = int(os.getenv("MAX_JOB_ATTEMPTS", "3"))
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


class PostgresConnection:
    def __init__(self, database_url: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except Exception as exc:
            raise RuntimeError("DATABASE_URL exige a dependencia psycopg[binary] instalada") from exc

        self.connection = psycopg.connect(postgres_connection_url(database_url), row_factory=dict_row)

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self.connection.__exit__(exc_type, exc, tb)

    def execute(self, sql: str, params: tuple[Any, ...] = ()):
        return self.connection.execute(sql.replace("?", "%s"), params)

    def commit(self) -> None:
        self.connection.commit()


def db_connect():
    if DATABASE_URL:
        return PostgresConnection(DATABASE_URL)
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def postgres_connection_url(database_url: str) -> str:
    ssl_cert_path = postgres_ssl_cert_path()
    parts = urlsplit(database_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if ssl_cert_path:
        query.setdefault("sslmode", "verify-ca")
        query.setdefault("sslcert", secure_ssl_file(ssl_cert_path, "certificate.pem"))
        query.setdefault("sslkey", secure_ssl_file(postgres_ssl_key_path() or ssl_cert_path, "private-key.key"))
        query.setdefault("sslrootcert", secure_ssl_file(postgres_ssl_root_cert_path() or ssl_cert_path, "ca-certificate.crt"))
    else:
        query.setdefault("sslmode", "require")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def postgres_ssl_cert_path() -> str:
    if DATABASE_SSL_CERT_PATH:
        return DATABASE_SSL_CERT_PATH

    for candidate in (
        Path("/application/certificate.pem"),
        Path("/application/server/certificate.pem"),
        Path("certificate.pem"),
        Path("server/certificate.pem"),
    ):
        if candidate.exists():
            return str(candidate)

    cert_text = postgres_ssl_cert_text()
    if not cert_text:
        return ""
    cert_path = Path(os.getenv("DATABASE_SSL_CERT_FILE", "/tmp/iatreiner-postgres-certificate.pem"))
    cert_path.write_text(cert_text.rstrip() + "\n", encoding="utf-8")
    cert_path.chmod(0o600)
    return str(cert_path)


def secure_ssl_file(source_path: str, filename: str) -> str:
    source = Path(source_path)
    target = Path("/tmp") / f"iatreiner-{filename}"
    if source.resolve() != target.resolve():
        shutil.copyfile(source, target)
    target.chmod(0o600)
    return str(target)


def postgres_ssl_key_path() -> str:
    if DATABASE_SSL_KEY_PATH:
        return DATABASE_SSL_KEY_PATH
    for candidate in (
        Path("/application/private-key.key"),
        Path("/application/server/private-key.key"),
        Path("private-key.key"),
        Path("server/private-key.key"),
    ):
        if candidate.exists():
            return str(candidate)
    return ""


def postgres_ssl_root_cert_path() -> str:
    if DATABASE_SSL_ROOT_CERT_PATH:
        return DATABASE_SSL_ROOT_CERT_PATH
    for candidate in (
        Path("/application/ca-certificate.crt"),
        Path("/application/server/ca-certificate.crt"),
        Path("ca-certificate.crt"),
        Path("server/ca-certificate.crt"),
    ):
        if candidate.exists():
            return str(candidate)
    return ""


def postgres_ssl_cert_text() -> str:
    if DATABASE_SSL_CERT_BASE64:
        try:
            return base64.b64decode(clean_secret(DATABASE_SSL_CERT_BASE64)).decode("utf-8")
        except Exception as exc:
            raise RuntimeError("DATABASE_SSL_CERT_BASE64 invalido") from exc
    if DATABASE_SSL_CERT_PEM:
        return clean_secret(DATABASE_SSL_CERT_PEM).replace("\\n", "\n")
    return ""


def clean_secret(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def ensure_column(connection, table_name: str, column_name: str, definition: str) -> None:
    if DATABASE_URL:
        rows = connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = ? AND column_name = ?
            """,
            (table_name, column_name),
        ).fetchall()
        columns = {row["column_name"] for row in rows}
    else:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {definition}")


def init_db() -> None:
    with db_lock, db_connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS workers (
                worker_id TEXT PRIMARY KEY,
                worker_token TEXT NOT NULL,
                display_name TEXT NOT NULL,
                device_info TEXT NOT NULL,
                registered_at DOUBLE PRECISION NOT NULL,
                last_seen_at DOUBLE PRECISION NOT NULL,
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
                created_at DOUBLE PRECISION NOT NULL,
                started_at DOUBLE PRECISION,
                finished_at DOUBLE PRECISION,
                worker_id TEXT,
                output TEXT,
                error TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_heartbeat_at DOUBLE PRECISION,
                reset_reason TEXT,
                checkpoint_url TEXT,
                checkpoint_step INTEGER,
                checkpoint_at DOUBLE PRECISION
            )
            """
        )
        ensure_column(connection, "jobs", "attempts", "attempts INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "jobs", "last_heartbeat_at", "last_heartbeat_at DOUBLE PRECISION")
        ensure_column(connection, "jobs", "reset_reason", "reset_reason TEXT")
        ensure_column(connection, "jobs", "checkpoint_url", "checkpoint_url TEXT")
        ensure_column(connection, "jobs", "checkpoint_step", "checkpoint_step INTEGER")
        ensure_column(connection, "jobs", "checkpoint_at", "checkpoint_at DOUBLE PRECISION")
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


class JobCheckpointRequest(BaseModel):
    worker_token: str
    checkpoint_url: str | None = Field(default=None, max_length=2000)
    checkpoint_step: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


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


def requeue_stale_jobs(connection: sqlite3.Connection) -> int:
    current_time = now()
    stale_rows = connection.execute(
        """
        SELECT j.*, w.last_seen_at AS worker_last_seen_at
        FROM jobs j
        LEFT JOIN workers w ON w.worker_id = j.worker_id
        WHERE j.status = 'running'
          AND (
            j.worker_id IS NULL
            OR w.worker_id IS NULL
            OR COALESCE(w.last_seen_at, 0) < ?
            OR COALESCE(j.last_heartbeat_at, j.started_at, 0) < ?
          )
        """,
        (current_time - WORKER_OFFLINE_SECONDS, current_time - JOB_LEASE_SECONDS),
    ).fetchall()

    changed = 0
    for row in stale_rows:
        job = dict(row)
        attempts = int(job.get("attempts") or 0)
        reason = (
            "worker offline ou heartbeat do job expirou; "
            f"tentativa {attempts} de {MAX_JOB_ATTEMPTS}"
        )
        if attempts >= MAX_JOB_ATTEMPTS:
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, finished_at = ?, error = ?, reset_reason = ?
                WHERE job_id = ?
                """,
                ("failed", current_time, reason, reason, job["job_id"]),
            )
        else:
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, started_at = NULL, worker_id = NULL,
                    last_heartbeat_at = NULL, finished_at = NULL,
                    error = ?, reset_reason = ?
                WHERE job_id = ?
                """,
                ("pending", reason, reason, job["job_id"]),
            )
        changed += 1
    return changed


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
        heartbeat_at = now()
        connection.execute(
            """
            UPDATE workers
            SET last_seen_at = ?, status = ?, cpu_limit_percent = ?, allow_gpu = ?
            WHERE worker_id = ?
            """,
            (heartbeat_at, request.status, request.cpu_limit_percent, int(request.allow_gpu), worker_id),
        )
        if request.status == "working":
            connection.execute(
                """
                UPDATE jobs
                SET last_heartbeat_at = ?
                WHERE worker_id = ? AND status = 'running'
                """,
                (heartbeat_at, worker_id),
            )
        connection.commit()
    return {"status": "ok"}


@app.get("/api/workers/{worker_id}/jobs/next")
def next_job(worker_id: str, worker_token: str) -> dict[str, Any]:
    with db_lock, db_connect() as connection:
        worker = get_worker(connection, worker_id, worker_token)
        requeue_stale_jobs(connection)
        rows = connection.execute(
            "SELECT * FROM jobs WHERE status = ? AND attempts < ? ORDER BY created_at ASC",
            ("pending", MAX_JOB_ATTEMPTS),
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
                    """
                    UPDATE jobs
                    SET status = ?, worker_id = ?, started_at = ?, last_heartbeat_at = ?,
                        attempts = COALESCE(attempts, 0) + 1, error = NULL
                    WHERE job_id = ?
                    """,
                    ("running", worker_id, started_at, started_at, job["job_id"]),
                )
                connection.commit()
                job["status"] = "running"
                job["worker_id"] = worker_id
                job["started_at"] = started_at
                job["last_heartbeat_at"] = started_at
                job["attempts"] = int(job.get("attempts") or 0) + 1
                job["error"] = None
                if job.get("checkpoint_url"):
                    job["payload"].setdefault("checkpoint_input_url", job["checkpoint_url"])
                return {"job": public_job(job)}
    return {"job": None}


@app.post("/api/workers/{worker_id}/jobs/{job_id}/checkpoint")
def report_checkpoint(worker_id: str, job_id: str, request: JobCheckpointRequest) -> dict[str, str]:
    with db_lock, db_connect() as connection:
        get_worker(connection, worker_id, request.worker_token)
        row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="job nao encontrado")
        job = row_to_job(row)
        if job.get("worker_id") != worker_id:
            raise HTTPException(status_code=403, detail="job pertence a outro worker")
        if job.get("status") != "running":
            raise HTTPException(status_code=409, detail="job nao esta mais em execucao")

        checkpoint_url = request.checkpoint_url
        if checkpoint_url and not checkpoint_url.startswith(("https://", "http://")):
            raise HTTPException(status_code=400, detail="checkpoint_url precisa usar http ou https")
        checkpoint_at = now()
        connection.execute(
            """
            UPDATE jobs
            SET checkpoint_url = COALESCE(?, checkpoint_url),
                checkpoint_step = ?,
                checkpoint_at = ?,
                last_heartbeat_at = ?
            WHERE job_id = ?
            """,
            (checkpoint_url, request.checkpoint_step, checkpoint_at, checkpoint_at, job_id),
        )
        connection.commit()
    return {"status": "ok"}


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
        if job.get("status") != "running":
            raise HTTPException(status_code=409, detail="job nao esta mais em execucao")
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
        requeue_stale_jobs(connection)
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
                "model_id": "str",
                "base_model_url": "url",
                "input_url": "url",
                "dataset_url": "url",
                "output_url": "url",
                "checkpoint_url": "url",
                "checkpoint_input_url": "url",
                "checkpoint_output_url": "url",
                "local_checkpoint": "bool",
                "texts": "list",
                "adapter_name": "str",
                "max_steps": "int",
                "checkpoint_save_steps": "int",
                "rank": "int",
                "batch_size": "int",
                "gradient_accumulation_steps": "int",
                "max_length": "int",
                "learning_rate": "float",
                "lora_dropout": "float",
                "target_modules": "list",
                "require_gpu": "bool",
                "batch_id": "str",
            },
            int_ranges={
                "max_steps": (1, 5000),
                "checkpoint_save_steps": (1, 1000),
                "rank": (1, 128),
                "batch_size": (1, 16),
                "gradient_accumulation_steps": (1, 64),
                "max_length": (32, 2048),
            },
            float_ranges={"learning_rate": (0.000001, 0.01), "lora_dropout": (0.0, 0.5)},
            max_inline_items=500,
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
        "attempts": job.get("attempts", 0),
        "last_heartbeat_at": job.get("last_heartbeat_at"),
        "reset_reason": job.get("reset_reason"),
        "checkpoint_url": job.get("checkpoint_url"),
        "checkpoint_step": job.get("checkpoint_step"),
        "checkpoint_at": job.get("checkpoint_at"),
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
