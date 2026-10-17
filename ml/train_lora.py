"""LoRA fine-tune a small instruct model on data/train.jsonl.

RUN THIS ON A BIGGER GPU THAN YOURS: a free Google Colab T4 or a Kaggle GPU notebook (see README.md). It refuses
to start on a GPU with under 6 GB of memory, because a 2 GB card such as the Quadro P620 would only run out of memory
partway through and leave you guessing why.

    pip install -U torch transformers peft trl datasets accelerate
    python train_lora.py                       # Qwen2.5-0.5B-Instruct, 2 epochs
    python train_lora.py --base Qwen/Qwen2.5-1.5B-Instruct --epochs 2

NOT RUN in the environment this was written in (it has no suitable GPU), so treat it as a careful starting point. The
trl and transformers APIs change between releases, so the script looks at what your installed version accepts rather
than assuming one set of argument names.
"""

import argparse
import inspect
import os
import sys


def accepted(cls, **wanted):
    """Keep only the keyword arguments this installed version of `cls` understands, under whichever name it uses."""
    params = set(inspect.signature(cls.__init__).parameters)
    out = {}
    for names, value in wanted.items():
        for name in names.split("|"):
            if name in params:
                out[name] = value
                break
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="Qwen/Qwen2.5-0.5B-Instruct", help="Hugging Face model id to fine-tune")
    ap.add_argument("--data", default="data", help="folder holding train.jsonl and val.jsonl")
    ap.add_argument("--out", default="out/epic-tn-lora", help="where the LoRA adapter is saved")
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--batch", type=int, default=4, help="per-device batch size; lower it if you run out of memory")
    ap.add_argument("--accum", type=int, default=4, help="gradient accumulation steps")
    ap.add_argument("--max-len", type=int, default=1536, help="longest example in tokens (examples are about 650)")
    ap.add_argument("--rank", type=int, default=16, help="LoRA rank")
    args = ap.parse_args()

    import torch
    from datasets import load_dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import SFTConfig, SFTTrainer

    if not torch.cuda.is_available():
        sys.exit("No CUDA GPU found. Fine-tuning on a CPU is far too slow. Use a free Colab or Kaggle GPU (see README.md).")
    props = torch.cuda.get_device_properties(0)
    gb = props.total_memory / 2**30
    print(f"GPU: {props.name}, {gb:.1f} GB")
    if gb < 6:
        sys.exit(f"{props.name} has only {gb:.1f} GB of memory, which is not enough to fine-tune even a 0.5B model. "
                 "Use a free Colab or Kaggle GPU instead (see README.md).")

    use_bf16 = torch.cuda.is_bf16_supported()
    dtype = torch.bfloat16 if use_bf16 else torch.float16           # a Colab T4 has no bf16, so it falls back to fp16
    tok = AutoTokenizer.from_pretrained(args.base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    def to_text(row):
        return {"text": tok.apply_chat_template(row["messages"], tokenize=False)}

    files = {"train": os.path.join(args.data, "train.jsonl"), "validation": os.path.join(args.data, "val.jsonl")}
    ds = load_dataset("json", data_files=files)
    ds = ds.map(to_text, remove_columns=ds["train"].column_names)
    print(f"{len(ds['train'])} training and {len(ds['validation'])} validation examples")
    print("example text begins:", ds["train"][0]["text"][:160].replace("\n", " | "))

    model = AutoModelForCausalLM.from_pretrained(args.base, torch_dtype=dtype)
    model.config.use_cache = False
    lora = LoraConfig(r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.05, target_modules="all-linear", task_type="CAUSAL_LM")

    cfg_kwargs = accepted(
        SFTConfig, output_dir=args.out, num_train_epochs=args.epochs, learning_rate=args.lr,
        per_device_train_batch_size=args.batch, per_device_eval_batch_size=args.batch, gradient_accumulation_steps=args.accum,
        lr_scheduler_type="cosine", warmup_ratio=0.05, logging_steps=10, save_strategy="epoch",
        **{"eval_strategy|evaluation_strategy": "epoch", "bf16": use_bf16, "fp16": not use_bf16, "gradient_checkpointing": True,
           "dataset_text_field": "text", "max_length|max_seq_length": args.max_len, "report_to": "none"})
    trainer_kwargs = dict(model=model, args=SFTConfig(**cfg_kwargs), train_dataset=ds["train"], eval_dataset=ds["validation"], peft_config=lora)
    trainer_kwargs.update(accepted(SFTTrainer, **{"processing_class|tokenizer": tok}))
    trainer = SFTTrainer(**trainer_kwargs)

    trainer.train()
    trainer.save_model(args.out)
    tok.save_pretrained(args.out)
    print(f"\nSaved the LoRA adapter to {args.out}\nNext: python merge_lora.py --base {args.base} --adapter {args.out}")


if __name__ == "__main__":
    main()
