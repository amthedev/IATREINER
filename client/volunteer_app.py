from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import queue
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from urllib import error, request


APP_DIR = Path.home() / ".consentcompute"
CONFIG_PATH = APP_DIR / "client.json"
CONSENT_TEXT = (
    "Eu aceito colaborar voluntariamente com processamento limitado neste computador. "
    "Entendo que posso parar a qualquer momento e que este app nao permite controle remoto "
    "da tela, arquivos, teclado, mouse ou terminal."
)
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024


class ApiClient:
    def __init__(self, server_url: str):
        self.server_url = server_url.rstrip("/")

    def post(self, path: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.server_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._open(req)

    def put_json(self, url: str, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        self._open(req, expect_json=False)

    def get(self, path: str) -> dict:
        req = request.Request(f"{self.server_url}{path}", method="GET")
        return self._open(req)

    def _open(self, req: request.Request, expect_json: bool = True) -> dict:
        try:
            with request.urlopen(req, timeout=20) as response:
                if not expect_json:
                    response.read()
                    return {}
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Erro HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Falha de rede: {exc.reason}") from exc


class VolunteerApp(tk.Tk):
    def __init__(self, start_minimized: bool = False, auto_connect: bool = False):
        super().__init__()
        self.title("IATREINER")
        self.geometry("600x640")
        self.minsize(560, 560)

        self.running = False
        self.worker_thread: threading.Thread | None = None
        self.messages: queue.Queue[str] = queue.Queue()
        self.worker_id = ""
        self.worker_token = ""

        self.server_var = tk.StringVar(value="http://127.0.0.1:8000")
        self.name_var = tk.StringVar(value=platform.node() or "voluntario")
        self.invite_var = tk.StringVar(value="")
        self.cpu_var = tk.IntVar(value=50)
        self.gpu_var = tk.BooleanVar(value=False)
        self.autostart_var = tk.BooleanVar(value=False)
        self.auto_connect_var = tk.BooleanVar(value=False)
        self.consent_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Parado")

        self.load_config()
        self.build_ui()
        self.after(250, self.drain_messages)
        if start_minimized:
            self.after(100, self.iconify)
        if auto_connect:
            self.after(800, self.start_from_saved_consent)

    def build_ui(self) -> None:
        root = ttk.Frame(self, padding=20)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)

        ttk.Label(root, text="IATREINER", font=("Segoe UI", 20, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 14)
        )

        ttk.Label(root, text="Servidor").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(root, textvariable=self.server_var).grid(row=1, column=1, sticky="ew", pady=5)

        ttk.Label(root, text="Nome visivel").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(root, textvariable=self.name_var).grid(row=2, column=1, sticky="ew", pady=5)

        ttk.Label(root, text="Convite").grid(row=3, column=0, sticky="w", pady=5)
        ttk.Entry(root, textvariable=self.invite_var, show="*").grid(row=3, column=1, sticky="ew", pady=5)

        ttk.Label(root, text="Limite de CPU").grid(row=4, column=0, sticky="w", pady=5)
        cpu_frame = ttk.Frame(root)
        cpu_frame.grid(row=4, column=1, sticky="ew", pady=5)
        cpu_frame.columnconfigure(0, weight=1)
        ttk.Scale(cpu_frame, from_=10, to=100, variable=self.cpu_var, orient="horizontal").grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Label(cpu_frame, textvariable=self.cpu_var, width=4).grid(row=0, column=1, padx=(8, 0))

        ttk.Checkbutton(
            root,
            text="Permitir jobs com GPU/PyTorch quando disponivel",
            variable=self.gpu_var,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))

        startup_box = ttk.LabelFrame(root, text="Segundo plano", padding=12)
        startup_box.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Checkbutton(
            startup_box,
            text="Iniciar este app automaticamente com o Windows",
            variable=self.autostart_var,
            command=self.on_autostart_changed,
        ).pack(anchor="w")
        ttk.Checkbutton(
            startup_box,
            text="Comecar colaboracao automaticamente ao abrir o app",
            variable=self.auto_connect_var,
            command=self.save_config,
        ).pack(anchor="w", pady=(6, 0))
        ttk.Label(
            startup_box,
            text="O app nunca roda escondido: ele continua com janela, log e botao Parar.",
            wraplength=520,
        ).pack(anchor="w", pady=(8, 0))

        consent_box = ttk.LabelFrame(root, text="Consentimento", padding=12)
        consent_box.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(14, 8))
        ttk.Label(consent_box, text=CONSENT_TEXT, wraplength=490).pack(anchor="w")
        ttk.Checkbutton(
            consent_box,
            text="Li e aceito colaborar com essas condicoes",
            variable=self.consent_var,
        ).pack(anchor="w", pady=(10, 0))

        actions = ttk.Frame(root)
        actions.grid(row=8, column=0, columnspan=2, sticky="ew", pady=10)
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.start_button = ttk.Button(actions, text="Iniciar colaboracao", command=self.start)
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.stop_button = ttk.Button(actions, text="Parar", command=self.stop, state="disabled")
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        ttk.Label(root, text="Status").grid(row=9, column=0, sticky="w", pady=(10, 5))
        ttk.Label(root, textvariable=self.status_var).grid(row=9, column=1, sticky="w", pady=(10, 5))

        self.log = tk.Text(root, height=8, wrap="word", state="disabled")
        self.log.grid(row=10, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        root.rowconfigure(10, weight=1)

    def start(self) -> None:
        if self.running:
            return
        if not self.consent_var.get():
            messagebox.showwarning("Consentimento necessario", "Marque o consentimento antes de iniciar.")
            return
        if not self.server_var.get().strip() or not self.invite_var.get().strip():
            messagebox.showwarning("Campos obrigatorios", "Informe servidor e convite.")
            return

        self.running = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set("Conectando")
        self.save_config()
        self.worker_thread = threading.Thread(target=self.worker_loop, daemon=True)
        self.worker_thread.start()

    def start_from_saved_consent(self) -> None:
        if self.auto_connect_var.get() and self.consent_var.get():
            self.messages.put("Inicio automatico autorizado pelo voluntario.")
            self.start()
        elif self.auto_connect_var.get():
            self.messages.put("Inicio automatico bloqueado: consentimento nao esta marcado.")

    def stop(self) -> None:
        self.running = False
        self.status_var.set("Parando")
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.messages.put("Colaboracao pausada pelo voluntario.")

    def on_autostart_changed(self) -> None:
        enabled = self.autostart_var.get()
        ok, message = set_windows_autostart(enabled)
        if not ok:
            self.autostart_var.set(False)
            messagebox.showwarning("Inicializacao automatica", message)
        else:
            self.messages.put(message)
        self.save_config()

    def worker_loop(self) -> None:
        client = ApiClient(self.server_var.get().strip())
        try:
            self.register(client)
            while self.running:
                self.heartbeat(client, "idle")
                response = client.get(
                    f"/api/workers/{self.worker_id}/jobs/next?worker_token={self.worker_token}"
                )
                job = response.get("job")
                if job:
                    self.handle_job(client, job)
                else:
                    self.messages.put("Aguardando jobs...")
                    time.sleep(5)
        except Exception as exc:
            self.running = False
            self.messages.put(f"Erro: {exc}")
            self.after(0, lambda: self.start_button.configure(state="normal"))
            self.after(0, lambda: self.stop_button.configure(state="disabled"))
            self.after(0, lambda: self.status_var.set("Erro"))

    def register(self, client: ApiClient) -> None:
        response = client.post(
            "/api/workers/register",
            {
                "display_name": self.name_var.get().strip(),
                "invite_token": self.invite_var.get().strip(),
                "consent_text_accepted": True,
                "device_info": {
                    "system": platform.system(),
                    "release": platform.release(),
                    "machine": platform.machine(),
                    "python": platform.python_version(),
                    "allow_gpu": self.gpu_var.get(),
                },
            },
        )
        self.worker_id = response["worker_id"]
        self.worker_token = response["worker_token"]
        self.messages.put(f"Registrado como {self.worker_id}")
        self.after(0, lambda: self.status_var.set("Online"))

    def heartbeat(self, client: ApiClient, status: str) -> None:
        client.post(
            f"/api/workers/{self.worker_id}/heartbeat",
            {
                "worker_token": self.worker_token,
                "status": status,
                "cpu_limit_percent": int(self.cpu_var.get()),
                "allow_gpu": bool(self.gpu_var.get()),
            },
        )

    def handle_job(self, client: ApiClient, job: dict) -> None:
        job_id = job["job_id"]
        job_type = job["job_type"]
        payload = job.get("payload", {})
        self.messages.put(f"Executando {job_type} ({job_id})")
        self.after(0, lambda: self.status_var.set("Trabalhando"))
        self.heartbeat(client, "working")
        try:
            if job_type == "hash_benchmark":
                output = run_hash_benchmark(payload, self.cpu_var.get(), self.is_running)
            elif job_type == "matrix_benchmark":
                output = run_matrix_benchmark(payload, self.cpu_var.get(), self.is_running)
            elif job_type == "sleep":
                output = run_sleep(payload, self.is_running)
            elif job_type == "generate_embeddings":
                output = run_generate_embeddings(payload, client, self.is_running)
            elif job_type == "fine_tune_chunk":
                output = run_fine_tune_chunk(payload, client, self.cpu_var.get(), self.is_running)
            elif job_type == "evaluate_model":
                output = run_evaluate_model(payload, client, self.is_running)
            elif job_type == "train_lora":
                output = run_train_lora(payload, client, self.gpu_var.get(), self.is_running)
            else:
                raise RuntimeError("tipo de job nao permitido pelo cliente")

            status = "completed" if self.running else "cancelled"
            error_message = None
        except Exception as exc:
            output = {}
            status = "failed"
            error_message = str(exc)

        client.post(
            f"/api/workers/{self.worker_id}/jobs/{job_id}/result",
            {
                "worker_token": self.worker_token,
                "status": status,
                "output": output,
                "error": error_message,
            },
        )
        self.messages.put(f"Job {job_id} finalizado: {status}")
        self.after(0, lambda: self.status_var.set("Online" if self.running else "Parado"))

    def is_running(self) -> bool:
        return self.running

    def drain_messages(self) -> None:
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                break
            self.log.configure(state="normal")
            self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {message}\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.after(250, self.drain_messages)

    def load_config(self) -> None:
        if not CONFIG_PATH.exists():
            return
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            self.server_var.set(data.get("server", self.server_var.get()))
            self.name_var.set(data.get("name", self.name_var.get()))
            self.invite_var.set(data.get("invite", ""))
            self.cpu_var.set(int(data.get("cpu_limit", 50)))
            self.gpu_var.set(bool(data.get("allow_gpu", False)))
            self.autostart_var.set(bool(data.get("autostart", False)))
            self.auto_connect_var.set(bool(data.get("auto_connect", False)))
            self.consent_var.set(bool(data.get("consent_accepted", False)))
        except Exception:
            return

    def save_config(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(
                {
                    "server": self.server_var.get().strip(),
                    "name": self.name_var.get().strip(),
                    "invite": self.invite_var.get().strip(),
                    "cpu_limit": int(self.cpu_var.get()),
                    "allow_gpu": bool(self.gpu_var.get()),
                    "autostart": bool(self.autostart_var.get()),
                    "auto_connect": bool(self.auto_connect_var.get()),
                    "consent_accepted": bool(self.consent_var.get()),
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def set_windows_autostart(enabled: bool) -> tuple[bool, str]:
    if platform.system() != "Windows":
        return False, "Inicializacao automatica so foi implementada para Windows neste MVP."
    startup_dir = Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
    startup_path = startup_dir / "IATREINER.cmd"
    legacy_startup_path = startup_dir / "ConsentCompute.cmd"
    if not enabled:
        if startup_path.exists():
            startup_path.unlink()
        if legacy_startup_path.exists():
            legacy_startup_path.unlink()
        return True, "Inicializacao automatica desativada."

    startup_dir.mkdir(parents=True, exist_ok=True)
    if getattr(sys, "frozen", False):
        args = [sys.executable, "--minimized", "--auto-connect"]
    else:
        args = [sys.executable, str(Path(__file__).resolve()), "--minimized", "--auto-connect"]
    command = subprocess.list2cmdline(args)
    startup_path.write_text(f"@echo off\nstart \"\" /min {command}\n", encoding="utf-8")
    return True, "Inicializacao automatica ativada para o proximo login do Windows."


def throttle(cpu_limit_percent: int) -> None:
    cpu_limit = max(10, min(int(cpu_limit_percent), 100))
    pause = (100 - cpu_limit) / 1000
    if pause > 0:
        time.sleep(pause)


def run_hash_benchmark(payload: dict, cpu_limit_percent: int, is_running) -> dict:
    seconds = max(1, min(int(payload.get("seconds", 5)), 60))
    deadline = time.time() + seconds
    digest = b"consentcompute"
    count = 0
    started = time.time()
    while time.time() < deadline and is_running():
        digest = hashlib.sha256(digest + count.to_bytes(8, "little")).digest()
        count += 1
        if count % 5000 == 0:
            throttle(cpu_limit_percent)
    elapsed = max(time.time() - started, 0.001)
    return {
        "hashes": count,
        "hashes_per_second": round(count / elapsed, 2),
        "digest_preview": digest.hex()[:16],
        "elapsed_seconds": round(elapsed, 3),
    }


def run_matrix_benchmark(payload: dict, cpu_limit_percent: int, is_running) -> dict:
    size = max(10, min(int(payload.get("size", 90)), 180))
    iterations = max(1, min(int(payload.get("iterations", 2)), 8))
    rng = random.Random(42)
    a = [[rng.random() for _ in range(size)] for _ in range(size)]
    b = [[rng.random() for _ in range(size)] for _ in range(size)]
    checksum = 0.0
    started = time.time()
    completed = 0

    for _ in range(iterations):
        if not is_running():
            break
        result = [[0.0 for _ in range(size)] for _ in range(size)]
        for i in range(size):
            row_a = a[i]
            row_r = result[i]
            for k in range(size):
                aik = row_a[k]
                row_b = b[k]
                for j in range(size):
                    row_r[j] += aik * row_b[j]
            if i % 6 == 0:
                throttle(cpu_limit_percent)
                if not is_running():
                    break
        checksum += sum(sum(row) for row in result)
        completed += 1

    elapsed = max(time.time() - started, 0.001)
    return {
        "size": size,
        "iterations_completed": completed,
        "elapsed_seconds": round(elapsed, 3),
        "checksum": round(checksum, 4),
    }


def run_sleep(payload: dict, is_running) -> dict:
    seconds = max(1, min(int(payload.get("seconds", 2)), 30))
    started = time.time()
    while time.time() - started < seconds and is_running():
        time.sleep(0.2)
    return {"slept_seconds": round(time.time() - started, 3)}


def run_generate_embeddings(payload: dict, client: ApiClient, is_running) -> dict:
    texts = load_texts(payload)
    dimensions = max(8, min(int(payload.get("dimensions", 64)), 512))
    embeddings = []
    for text in texts:
        if not is_running():
            break
        embeddings.append(hash_embedding(str(text), dimensions))

    artifact = {
        "job_type": "generate_embeddings",
        "dimensions": dimensions,
        "count": len(embeddings),
        "embeddings": embeddings,
    }
    uploaded = upload_if_requested(payload, client, artifact)
    return {
        "count": len(embeddings),
        "dimensions": dimensions,
        "uploaded": uploaded,
        "preview": embeddings[:2],
    }


def run_fine_tune_chunk(payload: dict, client: ApiClient, cpu_limit_percent: int, is_running) -> dict:
    examples = load_examples(payload)
    learning_rate = max(0.0001, min(float(payload.get("learning_rate", 0.05)), 2.0))
    epochs = max(1, min(int(payload.get("epochs", 3)), 20))
    if not examples:
        raise RuntimeError("dataset vazio")

    feature_count = len(examples[0]["features"])
    weights = [0.0 for _ in range(feature_count)]
    bias = 0.0
    losses = []
    processed = 0

    for _ in range(epochs):
        if not is_running():
            break
        total_loss = 0.0
        for example in examples:
            features = normalize_features(example["features"], feature_count)
            label = 1.0 if float(example["label"]) >= 0.5 else 0.0
            score = dot(weights, features) + bias
            prediction = sigmoid(score)
            error_value = prediction - label
            for index, value in enumerate(features):
                weights[index] -= learning_rate * error_value * value
            bias -= learning_rate * error_value
            total_loss += binary_loss(prediction, label)
            processed += 1
            if processed % 100 == 0:
                throttle(cpu_limit_percent)
                if not is_running():
                    break
        losses.append(round(total_loss / max(len(examples), 1), 6))

    artifact = {
        "job_type": "fine_tune_chunk",
        "model_delta": {"weights": weights, "bias": bias},
        "losses": losses,
        "examples": len(examples),
        "epochs_completed": len(losses),
    }
    uploaded = upload_if_requested(payload, client, artifact)
    return {
        "examples": len(examples),
        "epochs_completed": len(losses),
        "losses": losses,
        "uploaded": uploaded,
        "model_delta": artifact["model_delta"],
        "model_delta_preview": {"weights": [round(v, 6) for v in weights[:5]], "bias": round(bias, 6)},
    }


def run_evaluate_model(payload: dict, client: ApiClient, is_running) -> dict:
    examples = load_examples(payload)
    model = payload.get("model") or {}
    if "model_url" in payload:
        model = load_json_from_url(str(payload["model_url"]))
    weights = [float(value) for value in model.get("weights", [])]
    bias = float(model.get("bias", 0.0))
    if not examples or not weights:
        raise RuntimeError("modelo ou dataset ausente")

    correct = 0
    evaluated = 0
    losses = []
    for example in examples:
        if not is_running():
            break
        features = normalize_features(example["features"], len(weights))
        label = 1.0 if float(example["label"]) >= 0.5 else 0.0
        prediction = sigmoid(dot(weights, features) + bias)
        predicted_label = 1.0 if prediction >= 0.5 else 0.0
        correct += int(predicted_label == label)
        evaluated += 1
        losses.append(binary_loss(prediction, label))

    result = {
        "job_type": "evaluate_model",
        "evaluated": evaluated,
        "accuracy": round(correct / max(evaluated, 1), 6),
        "loss": round(sum(losses) / max(len(losses), 1), 6),
    }
    uploaded = upload_if_requested(payload, client, result)
    result["uploaded"] = uploaded
    return result


def run_train_lora(payload: dict, client: ApiClient, allow_gpu: bool, is_running) -> dict:
    if not allow_gpu:
        raise RuntimeError("voluntario nao autorizou jobs com GPU/PyTorch")
    try:
        import torch  # type: ignore
    except Exception as exc:
        raise RuntimeError("PyTorch nao esta instalado neste computador") from exc
    if not torch.cuda.is_available():
        raise RuntimeError("GPU CUDA nao disponivel para train_lora")
    if not is_running():
        return {"status": "cancelled_before_start"}

    result = {
        "job_type": "train_lora",
        "status": "ready_for_pytorch_worker",
        "device": torch.cuda.get_device_name(0),
        "adapter_name": payload.get("adapter_name", "adapter"),
        "max_steps": int(payload.get("max_steps", 100)),
        "rank": int(payload.get("rank", 8)),
        "message": "Executor PyTorch detectado. Integre aqui o loop fechado de LoRA do seu modelo.",
    }
    uploaded = upload_if_requested(payload, client, result)
    result["uploaded"] = uploaded
    return result


def load_texts(payload: dict) -> list[str]:
    if "texts" in payload:
        return [str(item) for item in payload["texts"]]
    if "input_url" in payload:
        data = load_json_from_url(str(payload["input_url"]))
        if isinstance(data, list):
            return [str(item) for item in data]
        if isinstance(data, dict) and isinstance(data.get("texts"), list):
            return [str(item) for item in data["texts"]]
    raise RuntimeError("generate_embeddings precisa de texts ou input_url")


def load_examples(payload: dict) -> list[dict]:
    if "examples" in payload:
        return normalize_examples(payload["examples"])
    if "input_url" in payload:
        return normalize_examples(load_json_from_url(str(payload["input_url"])))
    raise RuntimeError("job precisa de examples ou input_url")


def normalize_examples(data) -> list[dict]:
    if isinstance(data, dict):
        data = data.get("examples", [])
    if not isinstance(data, list):
        raise RuntimeError("dataset precisa ser lista ou objeto com examples")
    examples = []
    for item in data:
        if not isinstance(item, dict):
            continue
        features = item.get("features")
        if not isinstance(features, list) or "label" not in item:
            continue
        examples.append({"features": [float(value) for value in features], "label": float(item["label"])})
    return examples


def load_json_from_url(url: str):
    req = request.Request(url, method="GET")
    with request.urlopen(req, timeout=60) as response:
        length = int(response.headers.get("Content-Length") or 0)
        if length > MAX_DOWNLOAD_BYTES:
            raise RuntimeError("artefato excede limite de download")
        data = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(data) > MAX_DOWNLOAD_BYTES:
            raise RuntimeError("artefato excede limite de download")
    return json.loads(data.decode("utf-8"))


def upload_if_requested(payload: dict, client: ApiClient, artifact: dict) -> bool:
    output_url = payload.get("output_url")
    if not output_url:
        return False
    client.put_json(str(output_url), artifact)
    return True


def hash_embedding(text: str, dimensions: int) -> list[float]:
    vector = [0.0 for _ in range(dimensions)]
    tokens = text.lower().split()
    if not tokens:
        tokens = [text.lower()]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "little") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [round(value / norm, 6) for value in vector]


def normalize_features(features: list[float], feature_count: int) -> list[float]:
    values = [float(value) for value in features[:feature_count]]
    if len(values) < feature_count:
        values.extend([0.0] * (feature_count - len(values)))
    return values


def dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1 / (1 + z)
    z = math.exp(value)
    return z / (1 + z)


def binary_loss(prediction: float, label: float) -> float:
    prediction = max(1e-8, min(1 - 1e-8, prediction))
    return -(label * math.log(prediction) + (1 - label) * math.log(1 - prediction))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ConsentCompute volunteer app")
    parser.add_argument("--minimized", action="store_true", help="abre minimizado")
    parser.add_argument("--auto-connect", action="store_true", help="inicia colaboracao se ja autorizado")
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = parse_args()
    VolunteerApp(start_minimized=cli_args.minimized, auto_connect=cli_args.auto_connect).mainloop()
