# Local LLM for the AI trip planner

## Can your PC train an LLM? (Quadro P620, i5-7600, 8 GB RAM)

**No, not realistically.** What I measured on your machine:

| Part | What you have | Why it matters |
|---|---|---|
| GPU | Quadro P620, **2 GB** VRAM, about 1 GB already used by Windows | Even a 0.5B model needs 4 to 6 GB to fine-tune. |
| GPU generation | Pascal (compute 6.1): no tensor cores, no bf16 | Slow, and some training libraries refuse it. |
| CPU | i5-7600, 4 threads | CPU training would take days for a tiny model. |
| RAM | 8 GB | Enough to **run** a small model, tight to train one. |

What your PC **can** do well:

- **Run** (inference) a 1.5B model, quantised to 4 bits (about 1 GB), on the CPU at roughly 5 to 10 tokens/second. That is fine for the planner, which asks for about 300 tokens.
- Generate the training data, merge a LoRA adapter, convert to GGUF, and evaluate.

So the split is: **train on a free cloud GPU, run on your PC.**

## Do you even need to train?

Not to get started. The planner (route, days, times, costs) is ordinary code, and it supplies every fact. The LLM only
*words* the result, and the app fact-checks its output and falls back to a template when it slips. A stock
`qwen2.5:1.5b-instruct` already works. Fine-tuning improves the output format, brevity and how often it passes the
fact-check. It teaches the model nothing new about Tamil Nadu.

## Path A: no training (10 minutes)

1. Install Ollama from ollama.com (a download, so I did not do it for you).
2. `ollama pull qwen2.5:1.5b-instruct`
3. `ollama cp qwen2.5:1.5b-instruct epic-tn-planner` (or set `OLLAMA_MODEL=qwen2.5:1.5b-instruct`)
4. Start the backend. The planner page will show that the wording came from the model.

## Path B: fine-tune it (free Colab or Kaggle GPU)

1. **Data** (on your PC, already done once; rerun to change it):
   `python make_dataset.py --n 1500` writes `data/train.jsonl` and `data/val.jsonl`. Each example is the exact prompt
   the app sends plus a fact-checked target answer.
2. **Train** in a Colab (T4) or Kaggle notebook: upload the `ml` and `backend` folders, then
   ```
   !pip install -U transformers peft trl datasets accelerate
   !python train_lora.py --base Qwen/Qwen2.5-1.5B-Instruct --epochs 2
   !python merge_lora.py --base Qwen/Qwen2.5-1.5B-Instruct --adapter out/epic-tn-lora
   ```
   Use `Qwen/Qwen2.5-0.5B-Instruct` (the default) if you hit out-of-memory. Expect about 15 to 40 minutes.
   `train_lora.py` refuses to run on GPUs under 6 GB, including yours.
3. **Download** `out/epic-tn-merged` to your PC.
4. **Convert to GGUF and quantise** (llama.cpp, on your PC, CPU only):
   ```
   git clone https://github.com/ggerganov/llama.cpp
   pip install -r llama.cpp/requirements.txt
   python llama.cpp/convert_hf_to_gguf.py out/epic-tn-merged --outfile out/epic-tn-f16.gguf
   llama.cpp/llama-quantize out/epic-tn-f16.gguf out/epic-tn-q4_k_m.gguf Q4_K_M
   ```
   (`llama-quantize` has to be built or downloaded from the llama.cpp releases.)
5. **Register**: `ollama create epic-tn-planner -f Modelfile`
6. **Measure**: `python eval_model.py --model epic-tn-planner --n 20`, and the same with the base model, then compare
   valid-JSON rate, day count and the fact-check pass rate. Keep the fine-tune only if it wins.

## Settings the backend reads

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `none` turns the model off and uses the template |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | where Ollama listens |
| `OLLAMA_MODEL` | `epic-tn-planner` | model name |
| `LLM_TIMEOUT` | `180` | seconds before falling back to the template |

## Honest limits

- Nothing here has been trained or run against a real model in this repository; the scripts and the Ollama client were
  tested against a mock server. Expect to adjust `train_lora.py` for your installed `trl` version.
- The training targets come from a rule-based writer, so the fine-tuned model learns to imitate that writer's style.
