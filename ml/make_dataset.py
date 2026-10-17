"""Generate a fine-tuning dataset for the trip-narration model.

Every example is one planner run:
    input  = exactly the prompt the live app sends (narration.messages), i.e. the plan reduced to a fact sheet
    output = the JSON the model should return: an intro plus a summary and a tip for every day

The targets are written by a varied, rule-based writer that only ever uses facts from the plan and the town data,
and every target is checked with the SAME fact-checker the app uses on a real model's output (narration.safe), so
the training data can't teach the model to invent a time, a price or a place.

What fine-tuning on this buys you: the model learns the output format, to stay short, and to stay inside the facts.
It does not teach it anything new about Tamil Nadu: the planner supplies every fact at run time.

    python make_dataset.py --n 1500          # writes data/train.jsonl and data/val.jsonl
"""

import argparse
import json
import os
import random
import sys
from datetime import timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
os.environ.setdefault("LLM_PROVIDER", "none")
os.environ.setdefault("PLANNER_WEATHER", "0")

import clock                       # noqa: E402
import narration                   # noqa: E402
import planner as P                # noqa: E402
from activities import INTERESTS   # noqa: E402
from data import DESTINATIONS      # noqa: E402

BY_ID = {d["id"]: d for d in DESTINATIONS}


def join(items):
    items = list(items)
    if not items:
        return ""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def pick(rng, options):
    return rng.choice(options)


CTX = None            # the fact-check context for the plan being written; set per plan


def choose(rng, options, limit):
    """A random phrasing among those the app's own fact-checker would accept. Phrasings that mention a name,
    number or time the plan doesn't contain are simply not offered to the writer."""
    ok = [o for o in options if narration.safe(o, CTX, limit)]
    return rng.choice(ok) if ok else None


def days_word(n):
    return f"{n} {'day' if n == 1 else 'days'}"


# ------------------------------------------------------------------ the varied writer

def intro(plan, rng):
    s, r = plan["summary"], plan["request"]
    towns = join(s["town_names"])
    who = "a solo traveller" if r["travellers"] == 1 else f"{r['travellers']} travellers"
    tag = BY_ID[s["towns"][0]]["tagline"].rstrip(".")
    n = days_word(s["days"])
    return choose(rng, [
        f"{n[0].upper()}{n[1:]} across {towns} for {who}, starting {r['start_date']}.",
        f"A {s['days']}-day journey through {towns}. {tag}.",
        f"Here is a {s['days']}-day plan for {who}: {towns}, in the order that wastes the least time on the road.",
        f"Starting {r['start_date']}, this {s['days']}-day trip takes {who} through {towns}. {tag}.",
        f"{towns}: {n}, paced to {r['pace']} and planned around real opening hours.",
        f"{towns} over {n}, with the stops placed inside their real opening hours.",
    ], narration.MAX_INTRO)


def summary(day, rng):
    acts = [i["title"] for i in day["items"] if i["type"] == "activity"]
    legs = [i for i in day["items"] if i["type"] == "travel" and not i["title"].startswith("Arrive")]
    town, d = day["town_name"], day["day"]
    nxt = legs[0]["title"][0].lower() + legs[0]["title"][1:] if legs else ""
    if not acts:
        opts = [f"Day {d} is mostly about getting to the next stop.", f"Day {d} is a travel day with little time for sightseeing."]
    elif len(acts) == 1:
        opts = [f"Day {d} in {town} is built around {acts[0]}.", f"On day {d} the main stop in {town} is {acts[0]}."]
    else:
        opts = [f"Day {d} in {town}: {join(acts)}.", f"Spend day {d} in {town} at {join(acts)}.",
                f"Day {d} covers {join(acts)} in {town}.", f"In {town} on day {d} you will see {join(acts)}."]
    if legs:
        opts = [o.rstrip(".") + sep for o in opts for sep in (f", then {nxt}.", f". Afterwards, {nxt}.")]
    return choose(rng, opts, narration.MAX_SUMMARY)


def tip(plan, day, rng):
    base = narration._tip(plan, day)
    alt = {
        "Showers": ["Rain is likely, so carry an umbrella and keep the outdoor stops flexible.", "Expect showers: pack an umbrella and be ready to swap outdoor stops."],
        "busy": ["It will be busy, so reach the big sights early.", "Crowds are likely today, so start early at the main sights."],
        "close for": ["Temples close for a few hours at midday, so visits are timed around that.", "Many temples shut at midday, so the stops are placed before and after the break."],
        "night": ["The night journey saves a hotel night. Book your seat or berth early.", "Travelling overnight saves a hotel night, so reserve ahead."],
        "water": ["Carry water and start early, since outdoor spots are best in the morning.", "Start early and carry water: outdoor spots are nicest in the morning."],
    }
    for key, options in alt.items():
        if key in base:
            return choose(rng, options + [base], narration.MAX_TIP)
    return choose(rng, [base], narration.MAX_TIP)


def target(plan, rng):
    global CTX
    CTX = narration.allowed(plan)
    out = {"intro": intro(plan, rng), "days": [{"summary": summary(d, rng), "tip": tip(plan, d, rng)} for d in plan["days"]]}
    parts = [out["intro"]] + [x for d in out["days"] for x in (d["summary"], d["tip"])]
    return None if any(p is None for p in parts) else out


# ------------------------------------------------------------------ requests

def random_request(rng):
    r = {"start": rng.choice(P.PLACES), "days": rng.randint(1, 7), "travellers": rng.randint(1, 6),
         "interests": rng.sample(list(INTERESTS), rng.randint(1, 5)), "pace": rng.choice(P.PACES), "comfort": rng.choice(P.COMFORTS),
         "budget": rng.choice([None, None, None, 5000, 12000, 25000, 60000]), "return_home": rng.random() < 0.75,
         "start_date": (clock.today() + timedelta(days=rng.randint(1, 330))).isoformat()}
    if rng.random() < 0.3:
        r["must"] = rng.sample(P.PLACES, rng.randint(1, min(r["days"], 3)))
    if rng.random() < 0.25:
        r["avoid"] = rng.sample([p for p in P.PLACES if p not in r.get("must", [])], rng.randint(1, 4))
    return r


def rain_for(plan_req, rng):
    """Sometimes pretend it will rain, so the model sees the 'Showers' tip and the matching fact line."""
    if rng.random() > 0.25:
        return {}
    return {(t, plan_req["start_date"]): 90 for t in P.PLACES}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=os.path.join(HERE, "data"))
    a = ap.parse_args()
    rng = random.Random(a.seed)
    seen, rows, bad = set(), [], 0
    attempts = 0
    while len(rows) < a.n and attempts < a.n * 6:
        attempts += 1
        try:
            req = P.normalize(random_request(rng))
            plan = P.plan(req, rain_for(req, rng))
        except P.PlanError:
            continue
        msgs = narration.messages(plan)
        key = msgs[1]["content"]
        if key in seen:
            continue
        out = target(plan, rng)
        if out is None:                                  # some part had no phrasing that passes the fact-check
            bad += 1
            continue
        merged = narration.merge(plan, out)
        if merged["llm_parts"]["used"] != merged["llm_parts"]["of"]:      # the app's own checker rejects part of it: drop the example
            bad += 1
            continue
        seen.add(key)
        rows.append({"messages": msgs + [{"role": "assistant", "content": json.dumps(out, ensure_ascii=False)}], "days": len(plan["days"])})

    os.makedirs(a.out, exist_ok=True)
    cut = int(len(rows) * 0.9)
    for name, part in (("train", rows[:cut]), ("val", rows[cut:])):
        with open(os.path.join(a.out, f"{name}.jsonl"), "w", encoding="utf-8") as f:
            for r in part:
                f.write(json.dumps({"messages": r["messages"]}, ensure_ascii=False) + "\n")
    chars = sum(len(m["content"]) for r in rows for m in r["messages"]) / max(1, len(rows))
    print(f"wrote {cut} train and {len(rows) - cut} val examples to {a.out}")
    print(f"dropped {bad} plans where no acceptable phrasing existed; ~{chars:.0f} characters (~{chars / 3.6:.0f} tokens) per example")
    print("days per example:", {d: sum(1 for r in rows if r['days'] == d) for d in range(1, 8)})


if __name__ == "__main__":
    main()
