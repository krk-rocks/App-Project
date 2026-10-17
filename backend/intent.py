"""Turn a sentence such as "4 days from Chennai, temples and beaches, budget 20k for two" into a planner request.

Rule-based on purpose: it is instant, needs no model, and cannot be talked into anything. An LLM may refine the
result (llm.parse_request) but whatever it returns still goes through planner.normalize, which clamps and
validates every field, so free text can never put an out-of-range value into the planner.

`understood` lists, in plain words, what was picked up, so the user can see how their sentence was read.
"""

import re

import planner as P

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
_NUM = r"(\d+|" + "|".join(_WORDS) + r")"
INTEREST_WORDS = {
    "temples": r"temple|pilgrim|spiritual|church|mosque|darshan|worship",
    "heritage": r"heritage|history|historic|palace|museum|culture|architecture|craft|fort",
    "nature": r"nature|hill|hills|lake|waterfall|falls|trek|scenic|mountain|garden",
    "beaches": r"beach|beaches|sea|coast|ocean|sunrise",
    "food": r"food|foodie|cuisine|eat|eating|dosa|biryani",
}


def _n(token):
    return int(token) if token.isdigit() else _WORDS[token]


def _money(text):
    """Largest rupee amount mentioned, or None. Understands 20k, 1.5 lakh, Rs 12,000, 'under 15000'."""
    best = None
    pats = [r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)\s*(k|thousand|lakh|lac)?",
            r"(?:budget|under|within|upto|up to|around|about|max(?:imum)?)\s*(?:of|is|:)?\s*(?:₹|rs\.?)?\s*([\d,]+(?:\.\d+)?)\s*(k|thousand|lakh|lac)?",
            r"([\d,]+(?:\.\d+)?)\s*(k|thousand|lakh|lac)\b"]
    for pat in pats:
        for m in re.finditer(pat, text):
            try:
                v = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            mult = {"k": 1000, "thousand": 1000, "lakh": 100000, "lac": 100000}.get(m.group(2) or "", 1)
            v *= mult
            if 1000 <= v <= 1_000_000:
                best = v if best is None else max(best, v)
    return int(best) if best else None


def parse(text):
    low = " " + re.sub(r"\s+", " ", str(text or "").lower()) + " "
    req, said = {}, []

    m = re.search(_NUM + r"\s*[- ]?\s*(day|days|night|nights)\b", low)
    if m:
        n = _n(m.group(1))
        req["days"] = n + 1 if m.group(2).startswith("night") else n
    elif re.search(r"\blong weekend\b", low):
        req["days"] = 3
    elif re.search(r"\bweekend\b", low):
        req["days"] = 2
    elif re.search(r"\b(a|one) week\b", low):
        req["days"] = 7
    elif re.search(r"\bday trip\b|\bone day\b", low):
        req["days"] = 1
    if "days" in req:
        asked = req["days"]
        req["days"] = min(max(asked, 1), P.MAX_DAYS)
        said.append(f"{req['days']} day{'s' if req['days'] != 1 else ''}" if asked == req["days"]
                    else f"{asked} days asked for, planning the maximum of {P.MAX_DAYS}")

    m = re.search(r"family of " + _NUM, low) or re.search(_NUM + r"\s*(?:people|persons|pax|travell?ers|adults|friends|of us|members)", low)
    if m:
        req["travellers"] = min(max(_n(m.group(1)), 1), 6)
    elif re.search(r"\b(solo|alone|by myself|just me)\b", low):
        req["travellers"] = 1
    elif re.search(r"\b(couple|honeymoon|my wife|my husband|my partner)\b", low):
        req["travellers"] = 2
    elif re.search(r"\bfamily\b", low):
        req["travellers"] = 4
    if "travellers" in req:
        said.append(f"{req['travellers']} traveller{'s' if req['travellers'] != 1 else ''}")
    asked_people = m and m.group(1) and _n(m.group(1))
    if asked_people and asked_people > 6:
        said[-1] = f"{asked_people} travellers asked for, planning for the maximum of 6"

    money = _money(low)
    if money:
        if re.search(r"per (person|head)|each|pp\b", low) and "travellers" in req:
            money *= req["travellers"]
        req["budget"] = min(money, 1_000_000)
        said.append(f"budget {P.inr(req['budget'])}")

    avoid_zone = " ".join(re.findall(r"(?:avoid|skip|without|except|not)\s+(?:visiting\s+)?([a-z ]+?)(?:[,.;]|\band\b|$)", low))
    from_zone = ""
    m = re.search(r"\b(?:from|starting (?:in|from|at)|leaving from|start (?:in|from|at)|based in)\s+([a-z ()]+?)(?=\s+(?:to|for|with|and|on|in)\b|\s+\d|[,.;]|$)", low)
    if m:
        from_zone = m.group(1)
    for pid in P.PLACES:
        names = {pid, P.NAMES[pid].lower(), BY_NAME_ALIASES.get(pid, "")} - {""}
        hit = any(re.search(r"\b" + re.escape(n) + r"\b", low) for n in names)
        if not hit:
            continue
        in_from = any(re.search(r"\b" + re.escape(n) + r"\b", from_zone) for n in names)
        in_avoid = any(re.search(r"\b" + re.escape(n) + r"\b", avoid_zone) for n in names)
        if in_avoid:
            req.setdefault("avoid", []).append(pid)
        elif in_from and "start" not in req:
            req["start"] = pid
        else:
            req.setdefault("must", []).append(pid)
    if "start" in req:
        said.append(f"starting from {P.NAMES[req['start']]}")
    if req.get("must"):
        said.append("including " + ", ".join(P.NAMES[p] for p in req["must"]))
    if req.get("avoid"):
        said.append("skipping " + ", ".join(P.NAMES[p] for p in req["avoid"]))

    found = [k for k, rx in INTEREST_WORDS.items() if re.search(r"\b(?:" + rx + r")(?:s|es)?\b", low)]
    if found:
        req["interests"] = found
        said.append("interested in " + ", ".join(found))

    if re.search(r"\b(relax|relaxed|slow|easy|leisurely|unhurried)\b", low):
        req["pace"] = "relaxed"
    elif re.search(r"\b(packed|busy|fast[- ]paced|as much as|action[- ]packed|hectic)\b", low):
        req["pace"] = "packed"
    if "pace" in req:
        said.append(f"{req['pace']} pace")

    if re.search(r"\b(cheap|cheapest|economy|backpack\w*|low[- ]cost|on a budget|budget[- ](?:trip|travel|friendly|stay))\b", low):
        req["comfort"] = "budget"
    elif re.search(r"\b(luxury|luxurious|premium|comfortable|comfort|5[- ]star|splurge)\b", low):
        req["comfort"] = "comfort"
    if "comfort" in req:
        said.append(f"{req['comfort']} travel and stays")

    if re.search(r"\b(one[- ]way|not returning|no return|don'?t (?:need to )?return)\b", low):
        req["return_home"] = False
        said.append("no return journey")
    return {"request": req, "understood": said}


BY_NAME_ALIASES = {"ooty": "udhagamandalam", "mahabalipuram": "mamallapuram", "kanyakumari": "cape comorin", "chennai": "madras"}
