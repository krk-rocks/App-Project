"""Measure a model (base or fine-tuned) on the held-out prompts, through Ollama, exactly as the app would use it.

For each example it sends the same prompt and JSON schema as the live app, then reports how often the answer is valid
JSON, has the right number of days, and passes the app's fact-check (no time, number or name that is not in the prompt).
Use it to compare the base model with your fine-tune, or one quantisation with another.

    python eval_model.py --model qwen2.5:1.5b-instruct --n 20
    python eval_model.py --model epic-tn-planner --n 20
"""

import argparse
import json
import os
import re
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
os.environ.setdefault("LLM_PROVIDER", "none")
os.environ.setdefault("PLANNER_WEATHER", "0")
import narration  # noqa: E402


def context_from_prompt(prompt):
    """The fact-check context, rebuilt from the prompt alone: whatever the prompt says is allowed, nothing else."""
    words = ({w.lower() for w in re.findall(r"[A-Za-z]+", prompt)} | {w.lower() for w in narration._PROPER.findall(prompt)}
             | narration.ALWAYS_OK)
    towns = {pid for pid, rx in narration.NAME_PATTERNS.items() if rx.search(prompt)}
    nums = {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", prompt)} | set(range(0, 32))
    times = {t.lstrip("0") for t in re.findall(r"\b\d{1,2}:\d{2}\b", prompt)}
    return {"numbers": nums, "times": times, "towns": towns, "vocab": words}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:11434")
    ap.add_argument("--data", default=os.path.join(HERE, "data", "val.jsonl"))
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--timeout", type=float, default=300)
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(a.data, encoding="utf-8")][: a.n]
    stats = {"json": 0, "shape": 0, "parts_ok": 0, "parts": 0, "secs": 0.0, "tokens": 0}
    for i, row in enumerate(rows, 1):
        system, user = row["messages"][0], row["messages"][1]
        want = int(re.search(r"for each of the (\d+) day", user["content"]).group(1))
        body = {"model": a.model, "stream": False, "messages": [system, user], "format": narration.schema(want),
                "options": {"temperature": 0.3, "num_predict": 600}}
        t0 = time.time()
        try:
            r = requests.post(a.url + "/api/chat", json=body, timeout=a.timeout)
            r.raise_for_status()
            payload = r.json()
            out = json.loads(payload["message"]["content"])
            stats["json"] += 1
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"[{i}/{len(rows)}] failed: {type(e).__name__}")
            continue
        stats["secs"] += time.time() - t0
        stats["tokens"] += payload.get("eval_count", 0)
        days = out.get("days") if isinstance(out, dict) else None
        if isinstance(days, list) and len(days) == want:
            stats["shape"] += 1
        ctx = context_from_prompt(user["content"])
        texts = [out.get("intro")] + [x for d in (days or []) if isinstance(d, dict) for x in (d.get("summary"), d.get("tip"))] if isinstance(out, dict) else []
        stats["parts"] += 1 + 2 * want
        stats["parts_ok"] += sum(1 for t, lim in zip(texts, [narration.MAX_INTRO] + [narration.MAX_SUMMARY, narration.MAX_TIP] * want) if narration.safe(t, ctx, lim))
        print(f"[{i}/{len(rows)}] ok in {time.time() - t0:.1f}s")

    n = len(rows)
    print("\n=== results for", a.model, "===")
    print(f"valid JSON:           {stats['json']}/{n}")
    print(f"right number of days: {stats['shape']}/{n}")
    print(f"parts passing the fact-check: {stats['parts_ok']}/{stats['parts']}  ({100 * stats['parts_ok'] / max(1, stats['parts']):.0f}%)")
    if stats["json"]:
        print(f"average {stats['secs'] / stats['json']:.1f}s per answer" + (f", about {stats['tokens'] / stats['secs']:.1f} tokens/second" if stats["tokens"] else ""))


if __name__ == "__main__":
    main()
