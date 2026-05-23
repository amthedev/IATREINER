from __future__ import annotations

import argparse
import json
import ssl
from pathlib import Path
from urllib import error, request


DEFAULT_SERVER_URL = "https://ia-treiner.squareweb.app"
DEFAULT_ADMIN_TOKEN = "IHybFWKOukrIoNex4j9q0Va12yUqLSQEbUu6QNNjuac"
USER_AGENT = "IATREINER-Admin/0.1 (+https://github.com/amthedev/IATREINER)"


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def api_request(server: str, token: str, method: str, path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{server.rstrip('/')}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method=method,
    )
    try:
        with request.urlopen(req, timeout=30, context=ssl_context()) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Erro HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise SystemExit(f"Falha de rede: {exc.reason}") from exc


def print_json(data: dict) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def load_payload(args: argparse.Namespace) -> dict:
    payload = {}
    if args.payload_json:
        payload.update(json.loads(args.payload_json))
    if args.payload_file:
        payload.update(json.loads(Path(args.payload_file).read_text(encoding="utf-8")))
    if args.input_url:
        payload["input_url"] = args.input_url
    if args.output_url:
        payload["output_url"] = args.output_url
    if args.checkpoint_url:
        payload["checkpoint_url"] = args.checkpoint_url
    if args.checkpoint_input_url:
        payload["checkpoint_input_url"] = args.checkpoint_input_url
    if args.checkpoint_output_url:
        payload["checkpoint_output_url"] = args.checkpoint_output_url
    if args.model_url:
        payload["model_url"] = args.model_url
    if args.model_id:
        payload["model_id"] = args.model_id
    if args.base_model_url:
        payload["base_model_url"] = args.base_model_url
    if args.dataset_url:
        payload["dataset_url"] = args.dataset_url
    if args.seconds is not None:
        payload["seconds"] = args.seconds
    if args.size is not None:
        payload["size"] = args.size
    if args.iterations is not None:
        payload["iterations"] = args.iterations
    if args.dimensions is not None:
        payload["dimensions"] = args.dimensions
    if args.epochs is not None:
        payload["epochs"] = args.epochs
    if args.learning_rate is not None:
        payload["learning_rate"] = args.learning_rate
    if args.max_length is not None:
        payload["max_length"] = args.max_length
    if args.batch_size is not None:
        payload["batch_size"] = args.batch_size
    if args.gradient_accumulation_steps is not None:
        payload["gradient_accumulation_steps"] = args.gradient_accumulation_steps
    if args.max_steps is not None:
        payload["max_steps"] = args.max_steps
    if args.checkpoint_save_steps is not None:
        payload["checkpoint_save_steps"] = args.checkpoint_save_steps
    if args.rank is not None:
        payload["rank"] = args.rank
    if args.adapter_name:
        payload["adapter_name"] = args.adapter_name
    if args.batch_id:
        payload["batch_id"] = args.batch_id
    if args.require_gpu:
        payload["require_gpu"] = True
    return payload


def aggregate_model_deltas(jobs: list[dict], batch_id: str | None) -> dict:
    selected = []
    for job in jobs:
        if job["status"] != "completed" or job["job_type"] != "fine_tune_chunk":
            continue
        if batch_id and job.get("payload", {}).get("batch_id") != batch_id:
            continue
        output = job.get("output") or {}
        delta = output.get("model_delta") or {}
        weights = delta.get("weights")
        if not isinstance(weights, list):
            continue
        selected.append(
            {
                "job_id": job["job_id"],
                "worker_id": job.get("worker_id"),
                "examples": max(1, int(output.get("examples", 1))),
                "weights": [float(value) for value in weights],
                "bias": float(delta.get("bias", 0.0)),
                "losses": output.get("losses") or [],
            }
        )

    if not selected:
        raise SystemExit("Nenhum delta completo encontrado para agregar.")

    feature_count = len(selected[0]["weights"])
    total_examples = sum(item["examples"] for item in selected)
    weights = [0.0 for _ in range(feature_count)]
    bias = 0.0
    for item in selected:
        if len(item["weights"]) != feature_count:
            raise SystemExit("Deltas com tamanhos diferentes nao podem ser agregados.")
        weight = item["examples"] / total_examples
        for index, value in enumerate(item["weights"]):
            weights[index] += value * weight
        bias += item["bias"] * weight

    return {
        "batch_id": batch_id,
        "chunks": len(selected),
        "examples": total_examples,
        "model": {"weights": weights, "bias": bias},
        "sources": [
            {
                "job_id": item["job_id"],
                "worker_id": item["worker_id"],
                "examples": item["examples"],
                "last_loss": item["losses"][-1] if item["losses"] else None,
            }
            for item in selected
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Admin ConsentCompute")
    parser.add_argument("--server", default=DEFAULT_SERVER_URL, help=f"URL do servidor; padrao: {DEFAULT_SERVER_URL}")
    parser.add_argument("--token", default=DEFAULT_ADMIN_TOKEN, help="Token admin; por padrao usa o token fixo do projeto")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("workers", help="Lista voluntarios registrados")
    sub.add_parser("jobs", help="Lista jobs")

    set_worker = sub.add_parser("set-worker", help="Altera limites de CPU/GPU/memoria de um worker")
    set_worker.add_argument("worker_id")
    set_worker.add_argument("--cpu-limit", type=int, required=True, help="Percentual de CPU entre 5 e 100")
    gpu_group = set_worker.add_mutually_exclusive_group(required=True)
    gpu_group.add_argument("--allow-gpu", action="store_true", help="Libera jobs com GPU/PyTorch")
    gpu_group.add_argument("--deny-gpu", action="store_true", help="Bloqueia jobs com GPU/PyTorch")
    set_worker.add_argument(
        "--memory-limit-mb",
        type=int,
        default=0,
        help="Limite de memoria em MB; use 0 para sem limite definido",
    )

    submit = sub.add_parser("submit", help="Cria um job")
    submit.add_argument(
        "--job-type",
        choices=[
            "hash_benchmark",
            "matrix_benchmark",
            "sleep",
            "generate_embeddings",
            "fine_tune_chunk",
            "evaluate_model",
            "train_lora",
        ],
        required=True,
    )
    submit.add_argument("--target-worker-id", default=None)
    submit.add_argument("--payload-json", default=None, help="JSON bruto para o payload do job")
    submit.add_argument("--payload-file", default=None, help="Arquivo JSON com payload do job")
    submit.add_argument("--input-url", default=None, help="URL assinada para dataset ou textos")
    submit.add_argument("--output-url", default=None, help="URL assinada para enviar resultado por PUT")
    submit.add_argument("--checkpoint-url", default=None, help="URL assinada unica para baixar/enviar checkpoint LoRA")
    submit.add_argument("--checkpoint-input-url", default=None, help="URL assinada de leitura do checkpoint LoRA")
    submit.add_argument("--checkpoint-output-url", default=None, help="URL assinada de escrita do checkpoint LoRA")
    submit.add_argument("--model-url", default=None, help="URL assinada para modelo de avaliacao")
    submit.add_argument("--model-id", default=None, help="Modelo Hugging Face para LoRA, ex: distilgpt2")
    submit.add_argument("--base-model-url", default=None, help="URL assinada do modelo base para LoRA")
    submit.add_argument("--dataset-url", default=None, help="URL assinada do dataset para LoRA")
    submit.add_argument("--seconds", type=int, default=None)
    submit.add_argument("--size", type=int, default=None)
    submit.add_argument("--iterations", type=int, default=None)
    submit.add_argument("--dimensions", type=int, default=None)
    submit.add_argument("--epochs", type=int, default=None)
    submit.add_argument("--learning-rate", type=float, default=None)
    submit.add_argument("--max-length", type=int, default=None)
    submit.add_argument("--batch-size", type=int, default=None)
    submit.add_argument("--gradient-accumulation-steps", type=int, default=None)
    submit.add_argument("--max-steps", type=int, default=None)
    submit.add_argument("--checkpoint-save-steps", type=int, default=None)
    submit.add_argument("--rank", type=int, default=None)
    submit.add_argument("--adapter-name", default=None)
    submit.add_argument("--batch-id", default=None)
    submit.add_argument("--require-gpu", action="store_true")

    collect = sub.add_parser("collect", help="Mostra apenas resultados finalizados")
    collect.add_argument("--job-type", default=None)

    aggregate = sub.add_parser("aggregate-deltas", help="Junta resultados de fine_tune_chunk")
    aggregate.add_argument("--batch-id", default=None, help="Filtra somente jobs com este batch_id")
    aggregate.add_argument("--output-file", default=None, help="Salva modelo agregado em JSON")

    args = parser.parse_args()

    if args.command == "workers":
        print_json(api_request(args.server, args.token, "GET", "/api/admin/workers"))
        return

    if args.command == "jobs":
        print_json(api_request(args.server, args.token, "GET", "/api/admin/jobs"))
        return

    if args.command == "set-worker":
        print_json(
            api_request(
                args.server,
                args.token,
                "PATCH",
                f"/api/admin/workers/{args.worker_id}/config",
                {
                    "cpu_limit_percent": args.cpu_limit,
                    "allow_gpu": bool(args.allow_gpu),
                    "memory_limit_mb": args.memory_limit_mb,
                },
            )
        )
        return

    if args.command == "submit":
        payload = load_payload(args)
        print_json(
            api_request(
                args.server,
                args.token,
                "POST",
                "/api/admin/jobs",
                {
                    "job_type": args.job_type,
                    "payload": payload,
                    "target_worker_id": args.target_worker_id,
                },
            )
        )
        return

    if args.command == "collect":
        response = api_request(args.server, args.token, "GET", "/api/admin/jobs")
        jobs = []
        for job in response["jobs"]:
            if job["status"] != "completed":
                continue
            if args.job_type and job["job_type"] != args.job_type:
                continue
            jobs.append(
                {
                    "job_id": job["job_id"],
                    "job_type": job["job_type"],
                    "worker_id": job["worker_id"],
                    "output": job["output"],
                }
            )
        print_json({"results": jobs})
        return

    if args.command == "aggregate-deltas":
        response = api_request(args.server, args.token, "GET", "/api/admin/jobs")
        result = aggregate_model_deltas(response["jobs"], args.batch_id)
        if args.output_file:
            Path(args.output_file).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print_json(result)
        return


if __name__ == "__main__":
    main()
