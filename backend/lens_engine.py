"""
lens_engine.py — applying a lens's rules to one company

WHAT THIS DOES
A lens (backend/lenses.json) is a list of rules. Each rule names a field, an
operator, a threshold and a lookback. This module takes one company's metrics
(computed by lens_metrics.py) and says, for every rule:

    pass   the value meets the threshold
    fail   the value is known and does not meet it
    n/a    the value cannot be computed — too little history, a missing line,
           a ratio across a zero base — and so the rule is not judged at all

and then, for the lens as a whole:

    insufficient   fewer than min_coverage of the rules could be judged
    pass           every judged rule passed
    near_miss      exactly one judged rule failed and at least one passed —
                   so a one-rule lens has no near misses, only misses
    fail           anything else

WHY N/A IS NEVER A FAIL, AND NEVER A PASS
A company with seven years of filings cannot be said to have failed a
ten-year test, and it certainly has not passed one. Counting a missing value
either way would publish a statement the data does not support. So a missing
value lowers coverage instead, and below min_coverage the company is shown as
"insufficient data" rather than placed on either side of the line.

A metric can also decide a rule outright: a P/E cannot be computed for a
loss-making company, and "PEG below 1" is plainly not met. lens_metrics
returns {"fail": reason} for those, so the engine never has to know why.

This module is pure — no network, no disk — so every branch is unit-tested.
"""

import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "lenses.json")

DEFAULT_MIN_COVERAGE = 0.75
OPERATORS = (">", ">=", "<", "<=", "==", "between", "in", "abs_lte")
STATUSES = ("pass", "near_miss", "fail", "insufficient")


def load_config(path=None):
    with open(path or CONFIG_PATH, encoding="utf-8") as fh:
        cfg = json.load(fh)
    validate(cfg)
    return cfg


def validate(cfg):
    """Fail loudly on a config edit that would otherwise silently match nothing."""
    ids = set()
    default_cov = (cfg.get("defaults") or {}).get("min_coverage", DEFAULT_MIN_COVERAGE)
    for lens in cfg.get("lenses") or []:
        for key in ("id", "name", "originator", "idea", "rules"):
            if not lens.get(key):
                raise ValueError("lens %r is missing %r" % (lens.get("id"), key))
        if lens["id"] in ids:
            raise ValueError("duplicate lens id %r" % lens["id"])
        ids.add(lens["id"])
        if lens.get("status", "live") not in ("live", "coming_soon"):
            raise ValueError("lens %r has an unknown status" % lens["id"])
        cov = lens.get("min_coverage", default_cov)
        if not (0 < float(cov) <= 1):
            raise ValueError("lens %r min_coverage must be in (0, 1]" % lens["id"])
        for rule in lens["rules"]:
            for key in ("field", "operator", "label"):
                if rule.get(key) in (None, ""):
                    raise ValueError("a rule in %r is missing %r" % (lens["id"], key))
            op = rule["operator"]
            if op not in OPERATORS:
                raise ValueError("unknown operator %r in %r" % (op, lens["id"]))
            th = rule.get("threshold")
            if op == "between" and not (isinstance(th, list) and len(th) == 2):
                raise ValueError("'between' needs [low, high] in %r" % lens["id"])
            if op == "in" and not isinstance(th, list):
                raise ValueError("'in' needs a list in %r" % lens["id"])
    return True


def metric_key(field, lookback):
    return "%s@%s" % (field, int(lookback or 0))


def _num(v):
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def compare(value, op, threshold):
    """True / False, or None when the value cannot be compared at all."""
    if op == "in":
        if value is None:
            return None
        return value in threshold
    v = _num(value)
    if v is None:
        return None
    if op == "between":
        lo, hi = _num(threshold[0]), _num(threshold[1])
        return lo <= v <= hi
    if op == "abs_lte":
        return abs(v) <= _num(threshold)
    t = _num(threshold)
    if op == ">":
        return v > t
    if op == ">=":
        return v >= t
    if op == "<":
        return v < t
    if op == "<=":
        return v <= t
    if op == "==":
        return abs(v - t) < 1e-9
    raise ValueError("unknown operator %r" % op)


def evaluate_rule(rule, metrics):
    """
    One rule against one company's metrics.

    metrics maps metric_key(field, lookback) to either a bare value or a dict
    {"value": v, "display": text, "note": text, "fail": reason}.
    """
    key = metric_key(rule["field"], rule.get("lookback_years"))
    raw = metrics.get(key)
    info = raw if isinstance(raw, dict) else {"value": raw}
    value = info.get("value")
    out = {
        "field": rule["field"],
        "label": rule["label"],
        "operator": rule["operator"],
        "threshold": rule.get("threshold"),
        "lookback_years": rule.get("lookback_years"),
        "value": value,
        "display": info.get("display"),
        "note": info.get("note"),
    }
    if info.get("fail"):
        out["result"] = "fail"
        out["note"] = info["fail"]
        return out
    ok = compare(value, rule["operator"], rule.get("threshold"))
    out["result"] = "na" if ok is None else ("pass" if ok else "fail")
    if ok is None and not out["note"]:
        out["note"] = "Not enough data to compute this"
    return out


def evaluate_lens(lens, metrics, default_min_coverage=DEFAULT_MIN_COVERAGE):
    rules = [evaluate_rule(r, metrics) for r in lens["rules"]]
    passed = sum(1 for r in rules if r["result"] == "pass")
    failed = sum(1 for r in rules if r["result"] == "fail")
    na = sum(1 for r in rules if r["result"] == "na")
    total = len(rules)
    coverage = (passed + failed) / total if total else 0.0
    min_cov = float(lens.get("min_coverage", default_min_coverage))
    # A hair of tolerance, so 3 of 4 judged meets a 0.75 threshold exactly
    # rather than losing to floating point.
    if total == 0 or coverage + 1e-9 < min_cov:
        status = "insufficient"
    elif failed == 0:
        status = "pass"
    elif failed == 1 and passed >= 1:
        status = "near_miss"
    else:
        status = "fail"
    return {"status": status, "passed": passed, "failed": failed, "na": na,
            "total": total, "coverage": round(coverage, 4), "rules": rules}


def required_metrics(cfg, live_only=True):
    """Every (field, lookback) the live lenses need, so metrics compute only those."""
    out = set()
    for lens in cfg.get("lenses") or []:
        if live_only and lens.get("status", "live") != "live":
            continue
        for r in lens["rules"]:
            out.add((r["field"], int(r.get("lookback_years") or 0)))
    return sorted(out)


def public_lens(lens, cfg=None):
    """The part of a lens the site shows: everything except internals."""
    default_cov = ((cfg or {}).get("defaults") or {}).get("min_coverage", DEFAULT_MIN_COVERAGE)
    return {
        "id": lens["id"], "name": lens["name"], "originator": lens["originator"],
        "idea": lens["idea"], "status": lens.get("status", "live"),
        "coming_soon_reason": lens.get("coming_soon_reason"),
        "min_coverage": lens.get("min_coverage", default_cov),
        "rules": [{k: r.get(k) for k in ("field", "operator", "threshold",
                                          "lookback_years", "label")}
                  for r in lens["rules"]],
    }
