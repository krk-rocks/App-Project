"""Fold a trained LoRA adapter back into its base model, giving one ordinary Hugging Face model folder that
llama.cpp can convert to GGUF (see README.md). Needs enough memory to load the model in fp16: 1 GB for the 0.5B
model, about 3 GB for the 1.5B one. It runs on a CPU, so it works on your own PC as well as on Colab.

    python merge_lora.py --base Qwen/Qwen2.5-0.5B-Instruct --adapter out/epic-tn-lora
"""

import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="Qwen/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--adapter", default="out/epic-tn-lora")
    ap.add_argument("--out", default="out/epic-tn-merged")
    args = ap.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    base = AutoModelForCausalLM.from_pretrained(args.base, torch_dtype=torch.float16)
    merged = PeftModel.from_pretrained(base, args.adapter).merge_and_unload()
    merged.save_pretrained(args.out, safe_serialization=True)
    AutoTokenizer.from_pretrained(args.adapter).save_pretrained(args.out)
    print(f"Merged model saved to {args.out}. Convert it to GGUF next (README.md, step 4).")


if __name__ == "__main__":
    main()
