"""The optional local language model (Ollama). Everything here is a nice-to-have: the planner and its template
narration work without it, and any failure becomes "unavailable", never an error page.

Configured by environment variables, read on every call:
    LLM_PROVIDER   "ollama" (default) or "none"
    OLLAMA_URL     default http://127.0.0.1:11434
    OLLAMA_MODEL   default "epic-tn-planner" - the model you fine-tune and load with `ollama create` (see ml/README.md)
    LLM_TIMEOUT    seconds to wait for a generation, default 180 (a small model on a CPU is slow)

The model is asked for JSON that matches a schema, then everything it returns is fact-checked by narration.merge.
Only ONE generation runs at a time: a second request gets "busy" rather than queueing behind a slow CPU.
"""

import json
import os
import threading
import time

import requests

import narration
import planner

_gen_lock = threading.Semaphore(1)
_status_cache = {}
STATUS_TTL = 10.0


class LlmUnavailable(Exception):
    pass


class LlmBusy(Exception):
    pass


def _cfg():
    return {"provider": os.environ.get("LLM_PROVIDER", "ollama").strip().lower(),
            "url": os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
            "model": os.environ.get("OLLAMA_MODEL", "epic-tn-planner"),
            "timeout": float(os.environ.get("LLM_TIMEOUT", "180"))}


def _has(models, wanted):
    base = wanted.split(":")[0]
    return any(m == wanted or (":" not in wanted and m.split(":")[0] == base) for m in models)


def status(force=False):
    """{provider, available, model, reason}. Cached for a few seconds so page loads don't hammer the model server."""
    c = _cfg()
    if c["provider"] != "ollama":
        return {"provider": "none", "available": False, "model": None,
                "reason": "The language model is switched off on this server. Descriptions are written from templates."}
    key = (c["url"], c["model"])
    hit = _status_cache.get(key)
    if hit and not force and time.monotonic() - hit[0] < STATUS_TTL:
        return hit[1]
    try:
        r = requests.get(c["url"] + "/api/tags", timeout=1.5)
        r.raise_for_status()
        models = [m.get("name", "") for m in r.json().get("models", [])]
    except (requests.RequestException, ValueError, AttributeError):
        out = {"provider": "ollama", "available": False, "model": c["model"],
               "reason": "No local model server was found. Start Ollama to get written descriptions."}
    else:
        ok = _has(models, c["model"])
        out = {"provider": "ollama", "available": ok, "model": c["model"], "models": models,
               "reason": None if ok else f"The model '{c['model']}' isn't installed. See ml/README.md to create it."}
    _status_cache[key] = (time.monotonic(), out)
    return out


def _chat(messages, schema, max_tokens=450):
    c = _cfg()
    if not _gen_lock.acquire(blocking=False):
        raise LlmBusy()
    try:
        body = {"model": c["model"], "messages": messages, "stream": False, "format": schema,
                "options": {"temperature": 0.3, "num_predict": max_tokens}}
        try:
            r = requests.post(c["url"] + "/api/chat", json=body, timeout=c["timeout"])
            if r.status_code == 400 and isinstance(body["format"], dict):      # an older Ollama that only knows format="json"
                body["format"] = "json"
                r = requests.post(c["url"] + "/api/chat", json=body, timeout=c["timeout"])
            r.raise_for_status()
            return json.loads(r.json()["message"]["content"])
        except (requests.RequestException, KeyError, ValueError, TypeError) as e:
            raise LlmUnavailable(f"The model did not return a usable answer ({type(e).__name__}).")
    finally:
        _gen_lock.release()


def narrate(plan):
    """Describe a plan in the model's words, fact-checked. Raises LlmUnavailable / LlmBusy."""
    st = status()
    if not st["available"]:
        raise LlmUnavailable(st["reason"])
    raw = _chat(narration.messages(plan), narration.schema(len(plan["days"])))
    out = narration.merge(plan, raw)
    out["model"] = st["model"]
    return out


# ------------------------------------------------------------------ understanding a sentence

PARSE_SYSTEM = ("Extract trip preferences from the user's sentence about a trip in Tamil Nadu. "
                "Return JSON only. Use null for anything not stated. Never invent values.")


def _parse_schema():
    towns = [planner.NAMES[p] for p in planner.PLACES]
    return {"type": "object", "properties": {
        "days": {"type": ["integer", "null"]}, "travellers": {"type": ["integer", "null"]}, "budget": {"type": ["integer", "null"]},
        "start": {"type": ["string", "null"], "enum": towns + [None]},
        "must": {"type": "array", "items": {"type": "string", "enum": towns}}, "avoid": {"type": "array", "items": {"type": "string", "enum": towns}},
        "interests": {"type": "array", "items": {"type": "string", "enum": list(planner.AC.INTERESTS)}},
        "pace": {"type": ["string", "null"], "enum": list(planner.PACES) + [None]},
        "comfort": {"type": ["string", "null"], "enum": list(planner.COMFORTS) + [None]}}}


def refine_request(text, rules):
    """Let the model fill in what the rule-based parser missed. Rules win wherever they found something, and the
    model's values are only ever hints: the planner validates and clamps every field again."""
    st = status()
    if not st["available"]:
        return rules, "rules"
    try:
        raw = _chat([{"role": "system", "content": PARSE_SYSTEM}, {"role": "user", "content": str(text)[:500]}], _parse_schema(), 200)
    except (LlmUnavailable, LlmBusy):
        return rules, "rules"
    if not isinstance(raw, dict):
        return rules, "rules"
    merged = dict(rules)
    for k, v in raw.items():
        if k in merged or v in (None, [], ""):
            continue
        if k in ("days", "travellers", "budget") and (isinstance(v, bool) or not isinstance(v, int)):
            continue
        merged[k] = v
    try:
        planner.normalize(merged)
    except planner.PlanError:
        return rules, "rules"
    return merged, "llm+rules"
