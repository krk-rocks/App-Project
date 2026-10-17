"""Words for a finished plan: a template writer that always works, and a checker for an LLM's version.

The planner (planner.py) decides every fact. A language model is only ever asked to rephrase those facts, and it is
not trusted: whatever it returns is checked against the plan, and any text that mentions a time, a price, a number
or a town that is not in the plan is thrown away and replaced with the template's text for that day.
"""

import re

import planner as P
from data import DESTINATIONS

BY_ID = {d["id"]: d for d in DESTINATIONS}
NAME_PATTERNS = {d["id"]: re.compile(r"\b" + re.escape(d["name"].split(" (")[0]) + r"\b", re.I) for d in DESTINATIONS}
NAME_PATTERNS["ooty"] = re.compile(r"\b(?:Ooty|Udhagamandalam|Ootacamund)\b", re.I)
MAX_INTRO, MAX_SUMMARY, MAX_TIP = 320, 280, 200


def _join(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


# ------------------------------------------------------------------ template

def _tip(plan, day):
    town = day["town"]
    acts = [P.AC.BY_ID[i["id"]] for i in day["items"] if i["type"] == "activity"]
    if day.get("rain") is not None and day["rain"] >= 70:
        return "Showers are likely, so carry an umbrella and keep the outdoor stops flexible."
    if day["crowd"] == "High":
        return "It will be busy, so reach the big sights early in the day."
    if any(a["kind"] == "temple" and len(a["open"]) > 1 for a in acts):
        return "Temples close for a few hours at midday, so the visits are timed around that."
    if any(i.get("overnight") for i in day["items"] if i["type"] == "travel"):
        return "The night journey saves a hotel night. Book your seat or berth early."
    if any(a["outdoor"] for a in acts):
        return "Carry water and start early, since outdoor spots are most pleasant in the morning."
    return f"{P.NAMES[town]} is at its best from {BY_ID[town]['best_time']}."


def _summary(day):
    acts = [i["title"] for i in day["items"] if i["type"] == "activity"]
    trips = [i["title"] for i in day["items"] if i["type"] == "travel" and not i["title"].startswith("Arrive")]
    head = f"Day {day['day']} in {day['town_name']}: "
    if acts:
        text = head + _join(acts)
    else:
        text = head + "a travel day"
    return text + (f", then {trips[0][0].lower() + trips[0][1:]}." if trips else ".")


def packing(plan):
    towns = plan["summary"]["towns"]
    cats = {BY_ID[t]["category"] for t in towns}
    tags = {t for d in plan["days"] for i in d["items"] if i["type"] == "activity" for t in i["tags"]}
    out = ["A water bottle and a power bank"]
    if "religious" in tags:
        out.append("Modest clothes and socks for temple floors")
    if "Hill Station" in cats:
        out.append("A light jacket for cool hill evenings")
    if tags & {"beach"} or "Coastal" in cats:
        out.append("Sun protection and light cotton clothes")
    return out


def template(plan):
    r, s = plan["request"], plan["summary"]
    taglines = " ".join(f"{P.NAMES[t]}: {BY_ID[t]['tagline']}." for t in s["towns"][:2])
    who = f"{r['travellers']} traveller{'s' if r['travellers'] != 1 else ''}"
    return {"source": "template", "intro": f"{s['days']} {'day' if s['days'] == 1 else 'days'} for {who}, starting {r['start_date']}. {taglines}",
            "days": [{"summary": _summary(d), "tip": _tip(plan, d)} for d in plan["days"]], "packing": packing(plan)}


# ------------------------------------------------------------------ what an LLM is allowed to say

def _numbers(obj, out):
    if isinstance(obj, bool):
        return
    if isinstance(obj, int):
        out.add(obj)
    elif isinstance(obj, float):
        out.update({int(obj), int(round(obj))})
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers(v, out)


def allowed(plan):
    nums, times = set(), set()
    _numbers(plan["summary"], nums)
    _numbers(plan["legs"], nums)
    _numbers(plan["stays"], nums)
    _numbers(plan["request"], nums)
    nums.update(range(0, 32))                       # day counts, dates and small numbers are harmless
    for d in plan["days"]:
        for i in d["items"]:
            for k in ("start", "end"):
                if i.get(k):
                    times.add(i[k].lstrip("0") or "0")
    towns = set(plan["summary"]["towns"]) | {plan["request"]["start"]}
    corpus = " ".join(str(x) for d in plan["days"] for i in d["items"] for x in (i.get("title"), i.get("detail")) if x)
    corpus += " " + " ".join(plan["summary"]["town_names"]) + " " + P.NAMES[plan["request"]["start"]] + " " + " ".join(plan["notes"])
    corpus += " " + " ".join(d["weekday"] + " " + d["town_name"] for d in plan["days"])
    corpus += " " + " ".join(st["hotel"] for st in plan["stays"])
    vocab = {w.lower() for w in _PROPER.findall(corpus)} | {w.lower() for w in re.findall(r"[A-Za-z]+", corpus)} | ALWAYS_OK
    return {"numbers": nums, "times": times, "towns": towns, "vocab": vocab}


_PROPER = re.compile(r"[A-Z][A-Za-z]+(?:[-][A-Za-z]+)*")
ALWAYS_OK = {"tamil", "nadu", "india", "epic", "tn", "january", "february", "march", "april", "may", "june", "july", "august", "september",
              "october", "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}


def _names_ok(text, vocab):
    """Every capitalised word that is not the first word of a sentence or clause must already appear in the plan.
    This is what stops a model from adding a town, a monument or a person that the plan never mentioned."""
    for m in _PROPER.finditer(text):
        word = m.group(0)
        if len(word) < 2:
            continue
        before = text[:m.start()].rstrip()
        if not before or before[-1] in ".!?:;—–-":
            continue                                          # starts a sentence or clause
        if word.lower() not in vocab:
            return False
    return True


def _digits(text):
    return {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", text)}


def safe(text, ctx, limit):
    """True if `text` can be shown: short, plain, and it contains nothing that the plan doesn't."""
    if not isinstance(text, str) or not text.strip() or len(text) > limit:
        return False
    if re.search(r"[<>{}`]|https?:|www\.|\\u|\[|\]", text):
        return False
    for t in re.findall(r"\b\d{1,2}:\d{2}\b", text):
        if t.lstrip("0") not in ctx["times"]:
            return False
    plain = re.sub(r"\b\d{1,2}:\d{2}\b", "", text)
    for n in _digits(plain):
        if n not in ctx["numbers"]:
            return False
    for pid, rx in NAME_PATTERNS.items():
        if rx.search(text) and pid not in ctx["towns"]:
            return False
    return _names_ok(re.sub(r"['’]s", "", text), ctx["vocab"])


def merge(plan, llm_out):
    """Use the LLM's words wherever they pass the check, the template's wherever they don't."""
    base, ctx = template(plan), allowed(plan)
    if not isinstance(llm_out, dict):
        return base
    used = 0
    intro = llm_out.get("intro")
    if safe(intro, ctx, MAX_INTRO):
        base["intro"], used = intro.strip(), used + 1
    days = llm_out.get("days") if isinstance(llm_out.get("days"), list) else []
    for i, d in enumerate(base["days"]):
        got = days[i] if i < len(days) and isinstance(days[i], dict) else {}
        if safe(got.get("summary"), ctx, MAX_SUMMARY):
            d["summary"], used = got["summary"].strip(), used + 1
        if safe(got.get("tip"), ctx, MAX_TIP):
            d["tip"], used = got["tip"].strip(), used + 1
    total = 1 + 2 * len(base["days"])
    base["source"] = "template" if used == 0 else "llm" if used == total else "mixed"
    base["llm_parts"] = {"used": used, "of": total}
    return base


# ------------------------------------------------------------------ prompt

def facts(plan):
    """The plan as compact plain text. This is ALL the model gets to know."""
    r, s = plan["request"], plan["summary"]
    lines = [f"Trip: {s['days']} {'day' if s['days'] == 1 else 'days'} from {P.NAMES[r['start']]} for {r['travellers']} {'traveller' if r['travellers'] == 1 else 'travellers'}, starting {r['start_date']}.",
             f"Towns in order: {', '.join(s['town_names'])}."]
    for d in plan["days"]:
        parts = []
        for i in d["items"]:
            if i["type"] == "activity":
                parts.append(f"{i['start']} {i['title']}")
            elif i["type"] == "travel":
                parts.append(f"{i['start']} {i['title']}")
        extra = f" Crowd level {d['crowd']}." + (f" Rain chance {int(d['rain'])}%." if d.get("rain") is not None else "")
        lines.append(f"Day {d['day']} ({d['weekday']}, {d['town_name']}): " + ("; ".join(parts) or "no sightseeing") + "." + extra)
    if plan["notes"]:
        lines.append("Notes: " + " ".join(plan["notes"][:3]))
    return "\n".join(lines)


SYSTEM = ("You write short, friendly trip descriptions for Epic TN, a Tamil Nadu travel guide. Use ONLY the facts you are given. "
          "Never add places, prices, times, distances, years or history that are not in the facts. Do not mention any town that is not in the facts. "
          "Write in plain text with no markdown. Return JSON only.")


def schema(n_days):
    return {"type": "object", "required": ["intro", "days"], "properties": {
        "intro": {"type": "string", "maxLength": MAX_INTRO},
        "days": {"type": "array", "minItems": n_days, "maxItems": n_days, "items": {
            "type": "object", "required": ["summary", "tip"],
            "properties": {"summary": {"type": "string", "maxLength": MAX_SUMMARY}, "tip": {"type": "string", "maxLength": MAX_TIP}}}}}}


def messages(plan):
    n = len(plan["days"])
    ask = (f"Facts:\n{facts(plan)}\n\nWrite a one-sentence intro (under 40 words) and, for each of the {n} {'day' if n == 1 else 'days'} in order, "
           "a one-sentence summary (under 40 words) and one practical tip (under 25 words). Use only the facts above.")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": ask}]
