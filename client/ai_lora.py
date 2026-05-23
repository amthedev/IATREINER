from __future__ import annotations

import json
import shutil
import time
import zipfile
from pathlib import Path
from typing import Callable, Any
from urllib import request


MAX_DATASET_BYTES = 100 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 2 * 1024 * 1024 * 1024


def train_lora_job(
    payload: dict,
    output_root: Path,
    is_running,
    on_checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> dict:
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, TaskType, get_peft_model
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            DataCollatorForLanguageModeling,
            Trainer,
            TrainerCallback,
            TrainingArguments,
        )
    except Exception as exc:
        raise RuntimeError(
            "Dependencias de IA pesada ausentes. Instale client/requirements-ai.txt no worker."
        ) from exc

    if not is_running():
        return {"status": "cancelled_before_start"}

    model_id = str(payload.get("model_id") or payload.get("base_model_url") or "distilgpt2")
    local_checkpoint_key = safe_name(str(payload.get("local_checkpoint_key") or payload.get("adapter_name") or f"adapter-{int(time.time())}"))
    adapter_name = safe_name(str(payload.get("adapter_name") or local_checkpoint_key))
    output_dir = output_root / local_checkpoint_key
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoints_dir = output_dir / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)

    texts = load_training_texts(payload)
    if not texts:
        raise RuntimeError("train_lora precisa de texts, input_url ou dataset_url com textos")

    max_length = clamp_int(payload.get("max_length", 256), 32, 2048)
    max_steps = clamp_int(payload.get("max_steps", 20), 1, 5000)
    rank = clamp_int(payload.get("rank", 8), 1, 128)
    batch_size = clamp_int(payload.get("batch_size", 1), 1, 16)
    gradient_accumulation_steps = clamp_int(payload.get("gradient_accumulation_steps", 1), 1, 64)
    learning_rate = clamp_float(payload.get("learning_rate", 2e-4), 1e-6, 1e-2)
    checkpoint_url = payload.get("checkpoint_url")
    checkpoint_input_url = payload.get("checkpoint_input_url") or checkpoint_url
    checkpoint_output_url = payload.get("checkpoint_output_url") or checkpoint_url
    local_checkpoint = bool(payload.get("local_checkpoint", True))
    checkpoint_save_steps = clamp_int(
        payload.get("checkpoint_save_steps", max(1, min(25, max_steps // 5 or 1))),
        1,
        1000,
    )
    target_modules = payload.get("target_modules") or ["c_attn"]
    if not isinstance(target_modules, list) or not target_modules:
        raise RuntimeError("target_modules precisa ser uma lista nao vazia")

    device = detect_device(torch)
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(model_id)
    model.config.use_cache = False
    model.to(device)

    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=rank,
        lora_alpha=rank * 2,
        lora_dropout=float(payload.get("lora_dropout", 0.05)),
        target_modules=[str(item) for item in target_modules],
    )
    model = get_peft_model(model, lora_config)

    dataset = Dataset.from_dict({"text": texts})

    def tokenize(batch):
        tokens = tokenizer(
            batch["text"],
            truncation=True,
            max_length=max_length,
            padding="max_length",
        )
        tokens["labels"] = tokens["input_ids"].copy()
        return tokens

    tokenized = dataset.map(tokenize, batched=True, remove_columns=["text"])
    collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)
    remote_resume_checkpoint = restore_checkpoint_zip(str(checkpoint_input_url), checkpoints_dir) if checkpoint_input_url else None
    local_resume_checkpoint = find_latest_checkpoint(checkpoints_dir) if local_checkpoint else None
    resume_checkpoint = remote_resume_checkpoint or local_resume_checkpoint

    callbacks = []

    if on_checkpoint:
        class UploadCheckpointCallback(TrainerCallback):
            def on_save(self, args, state, control, **kwargs):
                checkpoint_path = Path(args.output_dir) / f"checkpoint-{state.global_step}"
                if not checkpoint_path.exists():
                    return control
                zip_path = None
                if checkpoint_output_url:
                    zip_path = shutil.make_archive(str(checkpoint_path), "zip", checkpoint_path)
                try:
                    on_checkpoint(
                        {
                            "checkpoint_zip_path": zip_path,
                            "local_checkpoint_path": str(checkpoint_path),
                            "checkpoint_step": int(state.global_step),
                            "checkpoint_url": str(checkpoint_input_url or checkpoint_output_url)
                            if (checkpoint_input_url or checkpoint_output_url)
                            else None,
                        }
                    )
                except Exception:
                    pass
                return control

        callbacks.append(UploadCheckpointCallback())

    training_args = TrainingArguments(
        output_dir=str(checkpoints_dir),
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=gradient_accumulation_steps,
        max_steps=max_steps,
        learning_rate=learning_rate,
        logging_steps=max(1, min(10, max_steps)),
        save_strategy="steps" if (local_checkpoint or checkpoint_output_url) else "no",
        save_steps=checkpoint_save_steps,
        save_total_limit=2,
        report_to=[],
        fp16=(device == "cuda"),
        bf16=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized,
        data_collator=collator,
        processing_class=tokenizer,
        callbacks=callbacks,
    )
    train_result = trainer.train(resume_from_checkpoint=str(resume_checkpoint) if resume_checkpoint else None)

    if not is_running():
        return {"status": "cancelled_after_train", "adapter_path": str(output_dir)}

    adapter_dir = output_dir / "adapter"
    model.save_pretrained(adapter_dir)
    tokenizer.save_pretrained(adapter_dir)
    zip_path = shutil.make_archive(str(output_dir / "adapter"), "zip", adapter_dir)

    return {
        "status": "completed",
        "model_id": model_id,
        "adapter_name": adapter_name,
        "device": device,
        "examples": len(texts),
        "max_steps": max_steps,
        "rank": rank,
        "target_modules": target_modules,
        "checkpoint_step": trainer.state.global_step,
        "resumed_from_checkpoint": bool(resume_checkpoint),
        "resume_source": "remote" if remote_resume_checkpoint else "local" if local_resume_checkpoint else None,
        "local_checkpoint": local_checkpoint,
        "train_loss": getattr(train_result, "training_loss", None),
        "adapter_path": str(adapter_dir),
        "adapter_zip_path": zip_path,
    }


def find_latest_checkpoint(checkpoints_dir: Path) -> Path | None:
    candidates = []
    for path in checkpoints_dir.glob("checkpoint-*"):
        if not path.is_dir():
            continue
        try:
            step = int(path.name.rsplit("-", 1)[1])
        except (IndexError, ValueError):
            continue
        candidates.append((step, path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def restore_checkpoint_zip(url: str, checkpoints_dir: Path) -> Path | None:
    checkpoint_zip = checkpoints_dir / "resume-checkpoint.zip"
    resume_dir = checkpoints_dir / "resume-checkpoint"
    if resume_dir.exists():
        shutil.rmtree(resume_dir)
    req = request.Request(url, headers={"User-Agent": "IATREINER-Worker/0.1"}, method="GET")
    try:
        with request.urlopen(req, timeout=300) as response:
            length = int(response.headers.get("Content-Length") or 0)
            if length > MAX_CHECKPOINT_BYTES:
                raise RuntimeError("checkpoint excede limite de download")
            with checkpoint_zip.open("wb") as handle:
                copied = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > MAX_CHECKPOINT_BYTES:
                        raise RuntimeError("checkpoint excede limite de download")
                    handle.write(chunk)
    except Exception:
        return None

    resume_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(checkpoint_zip) as archive:
        safe_extract_zip(archive, resume_dir)
    return resume_dir


def safe_extract_zip(archive: zipfile.ZipFile, target_dir: Path) -> None:
    target_root = target_dir.resolve()
    for member in archive.infolist():
        destination = (target_dir / member.filename).resolve()
        if target_root not in (destination, *destination.parents):
            raise RuntimeError("checkpoint contem caminho invalido")
        archive.extract(member, target_dir)


def detect_device(torch) -> str:
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_training_texts(payload: dict) -> list[str]:
    if isinstance(payload.get("texts"), list):
        return [str(item) for item in payload["texts"] if str(item).strip()]

    url = payload.get("input_url") or payload.get("dataset_url")
    if not url:
        return []

    data = load_json_from_url(str(url))
    if isinstance(data, list):
        return [extract_text(item) for item in data if extract_text(item)]
    if isinstance(data, dict):
        if isinstance(data.get("texts"), list):
            return [str(item) for item in data["texts"] if str(item).strip()]
        if isinstance(data.get("examples"), list):
            return [extract_text(item) for item in data["examples"] if extract_text(item)]
    raise RuntimeError("dataset precisa ser lista, {texts:[...]} ou {examples:[...]}")


def extract_text(item) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("text", "prompt", "content", "completion"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def load_json_from_url(url: str):
    req = request.Request(url, headers={"User-Agent": "IATREINER-Worker/0.1"}, method="GET")
    with request.urlopen(req, timeout=120) as response:
        length = int(response.headers.get("Content-Length") or 0)
        if length > MAX_DATASET_BYTES:
            raise RuntimeError("dataset excede limite de download")
        data = response.read(MAX_DATASET_BYTES + 1)
        if len(data) > MAX_DATASET_BYTES:
            raise RuntimeError("dataset excede limite de download")
    return json.loads(data.decode("utf-8"))


def safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in ("-", "_") else "-" for char in value)
    return cleaned.strip("-_")[:80] or "adapter"


def clamp_int(value, low: int, high: int) -> int:
    return max(low, min(int(value), high))


def clamp_float(value, low: float, high: float) -> float:
    return max(low, min(float(value), high))
