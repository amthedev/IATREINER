from __future__ import annotations

import json
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from admin_cli import DEFAULT_ADMIN_TOKEN, DEFAULT_SERVER_URL, api_request


class AdminGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("IATREINER Admin")
        self.geometry("960x680")
        self.minsize(860, 560)

        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.server_var = tk.StringVar(value=DEFAULT_SERVER_URL)
        self.token_var = tk.StringVar(value=DEFAULT_ADMIN_TOKEN)
        self.status_var = tk.StringVar(value="Pronto")
        self.job_type_var = tk.StringVar(value="hash_benchmark")
        self.seconds_var = tk.IntVar(value=10)
        self.size_var = tk.IntVar(value=90)
        self.iterations_var = tk.IntVar(value=2)
        self.target_worker_var = tk.StringVar(value="")
        self.model_id_var = tk.StringVar(value="distilgpt2")
        self.dataset_url_var = tk.StringVar(value="")
        self.output_url_var = tk.StringVar(value="")
        self.max_steps_var = tk.IntVar(value=20)
        self.rank_var = tk.IntVar(value=8)

        self.build_ui()
        self.after(200, self.drain_messages)
        self.refresh_all()

    def build_ui(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        top = ttk.LabelFrame(root, text="Servidor", padding=10)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.server_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Label(top, text="Token").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(top, textvariable=self.token_var, show="*").grid(row=1, column=1, sticky="ew", padx=8, pady=(8, 0))
        ttk.Button(top, text="Atualizar", command=self.refresh_all).grid(row=0, column=2, rowspan=2, sticky="ns")

        actions = ttk.LabelFrame(root, text="Criar job", padding=10)
        actions.grid(row=1, column=0, sticky="ew", pady=10)
        for col in range(10):
            actions.columnconfigure(col, weight=0)
        actions.columnconfigure(9, weight=1)

        ttk.Label(actions, text="Tipo").grid(row=0, column=0, sticky="w")
        job_select = ttk.Combobox(
            actions,
            textvariable=self.job_type_var,
            values=("hash_benchmark", "matrix_benchmark", "sleep", "train_lora"),
            state="readonly",
            width=18,
        )
        job_select.grid(row=0, column=1, sticky="w", padx=(6, 12))
        ttk.Label(actions, text="Segundos").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(actions, from_=1, to=60, textvariable=self.seconds_var, width=6).grid(
            row=0, column=3, padx=(6, 12)
        )
        ttk.Label(actions, text="Size").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(actions, from_=10, to=180, textvariable=self.size_var, width=6).grid(
            row=0, column=5, padx=(6, 12)
        )
        ttk.Label(actions, text="Iter").grid(row=0, column=6, sticky="w")
        ttk.Spinbox(actions, from_=1, to=8, textvariable=self.iterations_var, width=6).grid(
            row=0, column=7, padx=(6, 12)
        )
        ttk.Button(actions, text="Enviar job", command=self.submit_job).grid(row=0, column=8, sticky="w")

        ttk.Label(actions, text="Worker alvo opcional").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(actions, textvariable=self.target_worker_var).grid(
            row=1, column=1, columnspan=8, sticky="ew", padx=(6, 0), pady=(8, 0)
        )
        ttk.Label(actions, text="Modelo LoRA").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(actions, textvariable=self.model_id_var, width=22).grid(
            row=2, column=1, sticky="ew", padx=(6, 12), pady=(8, 0)
        )
        ttk.Label(actions, text="Dataset URL").grid(row=2, column=2, sticky="w", pady=(8, 0))
        ttk.Entry(actions, textvariable=self.dataset_url_var).grid(
            row=2, column=3, columnspan=3, sticky="ew", padx=(6, 12), pady=(8, 0)
        )
        ttk.Label(actions, text="Output URL").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(actions, textvariable=self.output_url_var).grid(
            row=3, column=1, columnspan=5, sticky="ew", padx=(6, 12), pady=(8, 0)
        )
        ttk.Label(actions, text="Steps").grid(row=2, column=6, sticky="w", pady=(8, 0))
        ttk.Spinbox(actions, from_=1, to=5000, textvariable=self.max_steps_var, width=7).grid(
            row=2, column=7, padx=(6, 12), pady=(8, 0)
        )
        ttk.Label(actions, text="Rank").grid(row=3, column=6, sticky="w", pady=(8, 0))
        ttk.Spinbox(actions, from_=1, to=128, textvariable=self.rank_var, width=7).grid(
            row=3, column=7, padx=(6, 12), pady=(8, 0)
        )

        panes = ttk.PanedWindow(root, orient="horizontal")
        panes.grid(row=2, column=0, sticky="nsew")

        workers_frame = ttk.LabelFrame(panes, text="Workers", padding=8)
        jobs_frame = ttk.LabelFrame(panes, text="Jobs", padding=8)
        panes.add(workers_frame, weight=1)
        panes.add(jobs_frame, weight=2)

        workers_frame.rowconfigure(0, weight=1)
        workers_frame.columnconfigure(0, weight=1)
        self.workers_tree = ttk.Treeview(
            workers_frame,
            columns=("online", "status", "cpu", "gpu", "seen"),
            show="tree headings",
            selectmode="browse",
        )
        self.workers_tree.heading("#0", text="Nome / worker_id")
        self.workers_tree.heading("online", text="Online")
        self.workers_tree.heading("status", text="Status")
        self.workers_tree.heading("cpu", text="CPU")
        self.workers_tree.heading("gpu", text="GPU")
        self.workers_tree.heading("seen", text="Visto")
        self.workers_tree.column("#0", width=220)
        self.workers_tree.column("online", width=70, anchor="center")
        self.workers_tree.column("status", width=90)
        self.workers_tree.column("cpu", width=60, anchor="center")
        self.workers_tree.column("gpu", width=60, anchor="center")
        self.workers_tree.column("seen", width=100)
        self.workers_tree.grid(row=0, column=0, sticky="nsew")
        self.workers_tree.bind("<<TreeviewSelect>>", self.on_worker_selected)

        jobs_frame.rowconfigure(0, weight=1)
        jobs_frame.columnconfigure(0, weight=1)
        self.jobs_tree = ttk.Treeview(
            jobs_frame,
            columns=("type", "status", "attempts", "worker", "created"),
            show="tree headings",
            selectmode="browse",
        )
        self.jobs_tree.heading("#0", text="job_id")
        self.jobs_tree.heading("type", text="Tipo")
        self.jobs_tree.heading("status", text="Status")
        self.jobs_tree.heading("attempts", text="Tentativas")
        self.jobs_tree.heading("worker", text="Worker")
        self.jobs_tree.heading("created", text="Criado")
        self.jobs_tree.column("#0", width=180)
        self.jobs_tree.column("type", width=140)
        self.jobs_tree.column("status", width=100)
        self.jobs_tree.column("attempts", width=80, anchor="center")
        self.jobs_tree.column("worker", width=160)
        self.jobs_tree.column("created", width=120)
        self.jobs_tree.grid(row=0, column=0, sticky="nsew")

        bottom = ttk.Frame(root)
        bottom.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

    def on_worker_selected(self, _event=None) -> None:
        selected = self.workers_tree.selection()
        if selected:
            self.target_worker_var.set(selected[0])

    def refresh_all(self) -> None:
        self.status_var.set("Atualizando...")
        self.run_background("refresh", self.load_data)

    def load_data(self) -> dict:
        workers = api_request(self.server_var.get(), self.token_var.get(), "GET", "/api/admin/workers")
        jobs = api_request(self.server_var.get(), self.token_var.get(), "GET", "/api/admin/jobs")
        return {"workers": workers.get("workers", []), "jobs": jobs.get("jobs", [])}

    def submit_job(self) -> None:
        job_type = self.job_type_var.get()
        payload: dict = {}
        if job_type in {"hash_benchmark", "sleep"}:
            payload["seconds"] = int(self.seconds_var.get())
        elif job_type == "matrix_benchmark":
            payload["size"] = int(self.size_var.get())
            payload["iterations"] = int(self.iterations_var.get())
        elif job_type == "train_lora":
            payload = {
                "model_id": self.model_id_var.get().strip() or "distilgpt2",
                "dataset_url": self.dataset_url_var.get().strip(),
                "max_steps": int(self.max_steps_var.get()),
                "rank": int(self.rank_var.get()),
                "target_modules": ["c_attn"],
                "require_gpu": True,
            }
            if self.output_url_var.get().strip():
                payload["output_url"] = self.output_url_var.get().strip()
            if not payload["dataset_url"]:
                messagebox.showwarning("IATREINER Admin", "Informe uma Dataset URL para train_lora.")
                return

        target = self.target_worker_var.get().strip() or None
        body = {"job_type": job_type, "payload": payload, "target_worker_id": target}
        self.status_var.set("Enviando job...")
        self.run_background("submit", lambda: api_request(self.server_var.get(), self.token_var.get(), "POST", "/api/admin/jobs", body))

    def run_background(self, action: str, callback) -> None:
        def worker() -> None:
            try:
                self.messages.put((action, callback()))
            except Exception as exc:
                self.messages.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def drain_messages(self) -> None:
        while True:
            try:
                action, payload = self.messages.get_nowait()
            except queue.Empty:
                break
            if action == "refresh":
                self.render_data(payload)  # type: ignore[arg-type]
                self.status_var.set("Atualizado")
            elif action == "submit":
                job_id = payload.get("job", {}).get("job_id") if isinstance(payload, dict) else None
                self.status_var.set(f"Job enviado: {job_id or 'ok'}")
                self.refresh_all()
            elif action == "error":
                self.status_var.set("Erro")
                messagebox.showerror("IATREINER Admin", str(payload))
        self.after(200, self.drain_messages)

    def render_data(self, data: dict) -> None:
        self.workers_tree.delete(*self.workers_tree.get_children())
        self.jobs_tree.delete(*self.jobs_tree.get_children())

        for worker in data.get("workers", []):
            worker_id = worker.get("worker_id", "")
            device = worker.get("device_info", {})
            label = f"{worker.get('display_name', 'worker')} ({worker_id})"
            self.workers_tree.insert(
                "",
                "end",
                iid=worker_id,
                text=label,
                values=(
                    "sim" if worker.get("online") else "nao",
                    worker.get("status", ""),
                    worker.get("cpu_limit_percent", ""),
                    device.get("gpu_backend", "none"),
                    format_time(worker.get("last_seen_at")),
                ),
            )

        for job in data.get("jobs", []):
            self.jobs_tree.insert(
                "",
                "end",
                iid=job.get("job_id", ""),
                text=job.get("job_id", ""),
                values=(
                    job.get("job_type", ""),
                    job.get("status", ""),
                    job.get("attempts", 0),
                    job.get("worker_id") or "-",
                    format_time(job.get("created_at")),
                ),
            )


def format_time(timestamp) -> str:
    if not timestamp:
        return "-"
    return time.strftime("%H:%M:%S", time.localtime(float(timestamp)))


if __name__ == "__main__":
    AdminGui().mainloop()
