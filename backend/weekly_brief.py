"""
The weekly brief: the week in one page, and one email on Saturday morning.

WHAT IS IN AN ISSUE
One issue per week, Monday to Sunday in IST, named by its ISO week
("2026-W47"). Five sections, each built from something this site already
keeps, and each left out when it has nothing to say:

  The market     each index's close at the end of the week against the end of
                 the week before, and Nifty session by session
                 (market_week's own closes)
  Money flow     FII and DII net buying in the cash market, each session and
                 the week's total (market_week's record of NSE's provisional
                 figures; a session the server never saw says so)
  New rules      the week's DGFT, RBI, SEBI and PIB circulars that matter for
                 listed companies (policy_brief's store), most important first
  The forum      the busiest discussions and the most talked-about stocks,
                 counted in posts (forum.activity)
  Topics         anything the owner chooses to write about that week, on any
                 subject: the budget, how to read a concall, a sector, tax
                 season. Added from the page (weekly.html, with the admin key)
                 or POST /admin/weekly/topics, and shown in the order added.

Above them, "the week in brief": three or four sentences written from those
numbers by fixed rules, so every claim in it is one of the figures below it.

WHEN AN ISSUE IS FIXED
The current week is a draft, built when it is asked for and held for fifteen
minutes. On Saturday morning the scheduled job (.github/workflows/
weekly-brief.yml) builds the week that has just traded, stores it, and mails
it. A stored issue does not change afterwards, except for its topics, which
are read live so a topic added on Sunday reaches the page. A past week that was
never stored is assembled from what is still on record (flows are kept for 90
days and circulars for 30) and is marked as such.

WHAT IT IS NOT
Facts and the owner's notes, never a call. A topic is checked by the same
rules as a forum post: no price to buy or sell at, no target, no stop-loss,
no promise of returns. The note at the foot of every issue says so.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import time
import uuid

import accounts

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.environ.get("DATA_DIR", "").strip() or _HERE
STORE = os.path.join(_DATA_DIR, "weekly_brief.json")
KEEP_WEEKS = 104
DRAFT_TTL = 900
_lock = threading.Lock()
_draft = {"week": None, "at": 0.0, "body": None}

INDICES = ("NIFTY 50", "SENSEX", "BANK NIFTY", "INDIA VIX")

NOTE = ("Facts from the week's prices, the exchange's provisional flow figures, the "
        "regulators' circulars and the forum, and notes from Altaha. None of it is a "
        "recommendation to buy or sell, and none of it changes a rank on the Ideas lists.")

TOPIC_TITLE = (4, 120)
TOPIC_BODY = (20, 8000)
MAX_TOPICS = 12


# ---------------------------------------------------------------------------
# Weeks
# ---------------------------------------------------------------------------

_WEEK = re.compile(r"^(\d{4})-W(\d{2})$")


def week_id(day: dt.date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def week_days(week: str):
    """(monday, sunday) of an ISO week id, or ValueError."""
    m = _WEEK.match(str(week or ""))
    if not m:
        raise ValueError("A week looks like 2026-W47.")
    try:
        monday = dt.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        raise ValueError("There is no such week.")
    return monday, monday + dt.timedelta(days=6)


def week_label(week: str) -> str:
    a, b = week_days(week)
    if a.month == b.month:
        return f"{a.day}–{b.day} {b.strftime('%b %Y')}"
    if a.year == b.year:
        return f"{a.day} {a.strftime('%b')} – {b.day} {b.strftime('%b %Y')}"
    return f"{a.day} {a.strftime('%b %Y')} – {b.day} {b.strftime('%b %Y')}"


def today_ist() -> dt.date:
    return dt.datetime.now(IST).date()


def last_traded_week(today: dt.date = None) -> str:
    """The week a Saturday run publishes: this one on a weekend, the one
    before on a weekday (a run by hand mid-week publishes last week)."""
    today = today or today_ist()
    if today.weekday() >= 5:
        return week_id(today)
    return week_id(today - dt.timedelta(days=7))


def _utc_bounds(week: str):
    a, b = week_days(week)
    start = dt.datetime.combine(a, dt.time(0, 0), IST).astimezone(dt.timezone.utc)
    end = dt.datetime.combine(b + dt.timedelta(days=1), dt.time(0, 0), IST).astimezone(dt.timezone.utc)
    return start, end


# ---------------------------------------------------------------------------
# The sections, each from plain data so each can be tested without a network
# ---------------------------------------------------------------------------

def _pct(a, b):
    return round((a - b) / b * 100, 2) if a is not None and b else None


def market_section(series: dict, week: str) -> dict:
    """series: {"NIFTY 50": {"2026-11-20": 25150.7, ...}, ...}."""
    a, b = week_days(week)
    lo, hi = a.isoformat(), b.isoformat()
    rows = []
    for label in INDICES:
        closes = series.get(label) or {}
        days = sorted(closes)
        inside = [d for d in days if lo <= d <= hi]
        before = [d for d in days if d < lo]
        if not inside:
            continue
        end = closes[inside[-1]]
        start = closes[before[-1]] if before else None
        rows.append({"index": label, "close": round(end, 2), "as_of": inside[-1],
                     "week_change_pct": _pct(end, start) if start else None})
    nifty = series.get("NIFTY 50") or {}
    days = sorted(nifty)
    sessions = []
    for d in days:
        if lo <= d <= hi:
            i = days.index(d)
            prev = nifty[days[i - 1]] if i else None
            sessions.append({"date": d, "weekday": dt.date.fromisoformat(d).strftime("%a"),
                             "close": round(nifty[d], 2), "change_pct": _pct(nifty[d], prev)})
    return {"indices": rows, "sessions": sessions}


def flows_section(record: dict, week: str, sessions: list) -> dict:
    """record: market_week's {date: {"fii": {"net"}, "dii": {"net"}}}. The
    sessions are the week's trading days as the market section saw them;
    with no prices at all, Monday to Friday stand in."""
    a, _ = week_days(week)
    days = [s["date"] for s in sessions] or [(a + dt.timedelta(days=i)).isoformat() for i in range(5)]
    out, fii, dii, seen = [], 0.0, 0.0, 0
    for d in days:
        f = (record or {}).get(d) or {}
        fn = (f.get("fii") or {}).get("net")
        dn = (f.get("dii") or {}).get("net")
        if fn is not None and dn is not None:
            fii += fn
            dii += dn
            seen += 1
        out.append({"date": d, "weekday": dt.date.fromisoformat(d).strftime("%a"),
                    "fii": fn, "dii": dn, "recorded": fn is not None and dn is not None})
    return {"sessions": out, "recorded": seen, "of": len(days),
            "fii_total": round(fii, 2) if seen else None,
            "dii_total": round(dii, 2) if seen else None,
            "source": "NSE provisional cash-market figures, ₹ crore"}


_RANK = {"high": 0, "medium": 1, "low": 2}


def policy_section(items: dict, week: str, limit: int = 8) -> dict:
    """items: policy_brief's store, {id: item}. The circulars first seen in
    the week whose effect on listed companies is not "none"."""
    a, b = week_days(week)
    lo, hi = a.isoformat(), b.isoformat()
    rows = [v for v in (items or {}).values() if lo <= (v.get("first_seen") or "") <= hi]
    matter = [r for r in rows if r.get("impact") in ("positive", "negative", "mixed")]
    matter.sort(key=lambda r: (_RANK.get(r.get("importance"), 3), r.get("date") or "", r.get("title") or ""))
    sectors = {}
    for r in matter:
        for s in r.get("sectors") or []:
            sectors.setdefault(s, {"positive": 0, "negative": 0, "mixed": 0})[r["impact"]] += 1
    keep = ("source", "number", "title", "date", "impact", "summary", "sectors", "link")
    return {
        "read": len(rows), "matter": len(matter),
        "items": [dict({k: r.get(k) for k in keep},
                       stocks=[{"symbol": s.get("symbol"), "direction": s.get("direction")}
                               for s in (r.get("stocks") or [])[:6]])
                  for r in matter[:limit]],
        "sectors": sorted(({"sector": k, **v} for k, v in sectors.items()),
                          key=lambda x: -(x["positive"] + x["negative"] + x["mixed"]))[:8],
    }


def _whole(v) -> int:
    """Half away from zero, as the page's own number formatting rounds, so a
    figure in the summary is the figure in the table under it. Python's
    format() rounds a half to even: -2,200.5 would read 2,200 here and 2,201
    there."""
    from decimal import ROUND_HALF_UP, Decimal
    return int(Decimal(str(v)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _crore(v):
    return f"₹{abs(_whole(v)):,} crore"


def summary(market: dict, flows: dict, policy: dict, forum: dict) -> list:
    """The week in a few sentences, each one a figure from the sections."""
    out = []
    nifty = next((r for r in (market or {}).get("indices") or [] if r["index"] == "NIFTY 50"), None)
    if nifty and nifty.get("week_change_pct") is not None:
        ch = nifty["week_change_pct"]
        verb = "rose" if ch > 0.05 else ("fell" if ch < -0.05 else "ended flat")
        amt = f" {abs(ch):.2f}%" if verb != "ended flat" else ""
        out.append(f"Nifty {verb}{amt} over the week, to {nifty['close']:,.0f}.")
    if flows and flows.get("recorded"):
        f, d = flows["fii_total"], flows["dii_total"]
        line = (f"FIIs {'bought' if f >= 0 else 'sold'} a net {_crore(f)} in the cash market and "
                f"DIIs {'bought' if d >= 0 else 'sold'} {_crore(d)}")
        if flows["recorded"] < flows["of"]:
            line += f", across the {flows['recorded']} of {flows['of']} sessions on record"
        out.append(line + ".")
    if policy and policy.get("matter"):
        n = policy["matter"]
        line = f"{n} new circular{'s' if n != 1 else ''} mattered for listed companies"
        if policy.get("sectors"):
            line += ", most of all for " + policy["sectors"][0]["sector"]
        out.append(line + ".")
    if forum and forum.get("threads"):
        top = forum["threads"][0]
        out.append(f"On the forum, {forum['posts']} post{'s' if forum['posts'] != 1 else ''} from "
                   f"{forum['members']} member{'s' if forum['members'] != 1 else ''}; the busiest discussion "
                   f"was “{top['title']}”.")
    return out


def build(week: str, series=None, flows_record=None, policy_items=None, forum_activity=None) -> dict:
    """One issue from plain data. Every source is optional: a missing one
    leaves its section out rather than failing the issue."""
    market = market_section(series or {}, week)
    flows = flows_section(flows_record or {}, week, market["sessions"])
    policy = policy_section(policy_items or {}, week)
    forum = forum_activity or {"posts": 0, "members": 0, "new_threads": 0, "threads": [], "stocks": []}
    return {
        "week": week, "label": week_label(week),
        "start": week_days(week)[0].isoformat(), "end": week_days(week)[1].isoformat(),
        "built_at": dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M"),
        "summary": summary(market, flows, policy, forum),
        "market": market, "flows": flows, "policy": policy, "forum": forum,
        "note": NOTE,
    }


def has_content(issue: dict) -> bool:
    return bool(issue.get("summary") or issue.get("topics"))


# ---------------------------------------------------------------------------
# The live sources, read the way the rest of the site reads them
# ---------------------------------------------------------------------------

def live_sources(week: str) -> dict:
    """Everything build() needs, from this server's own records. Each source
    that cannot be read is left empty and named in `missing`."""
    out, missing = {}, []
    try:
        import market_week
        out["series"] = {label: market_week._closes(sym) for sym, label in market_week.INDICES}
        if not any(out["series"].values()):
            missing.append("prices")
    except Exception:
        out["series"] = {}
        missing.append("prices")
    try:
        import market_week
        out["flows_record"] = market_week._load()
    except Exception:
        out["flows_record"] = {}
        missing.append("flows")
    try:
        import policy_brief
        out["policy_items"] = policy_brief.load().get("items") or {}
    except Exception:
        out["policy_items"] = {}
        missing.append("circulars")
    try:
        import forum
        start, end = _utc_bounds(week)
        out["forum_activity"] = forum.activity(start, end)
    except Exception:
        out["forum_activity"] = None
        missing.append("forum")
    out["missing"] = missing
    return out


# ---------------------------------------------------------------------------
# The store: published issues, and the owner's topics
# ---------------------------------------------------------------------------

def load() -> dict:
    try:
        with open(STORE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("issues", {})
            data.setdefault("topics", {})
            return data
    except Exception:
        pass
    return {"issues": {}, "topics": {}}


def _save(state: dict) -> None:
    keep = sorted(state["issues"])[-KEEP_WEEKS:]
    state["issues"] = {k: state["issues"][k] for k in keep}
    tkeep = sorted(state["topics"])[-KEEP_WEEKS:]
    state["topics"] = {k: state["topics"][k] for k in tkeep}
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, STORE)


def publish(week: str, sources: dict = None) -> dict:
    """Build a week's issue from the live sources (or those given) and keep it."""
    week_days(week)
    src = sources if sources is not None else live_sources(week)
    issue = build(week, src.get("series"), src.get("flows_record"), src.get("policy_items"),
                  src.get("forum_activity"))
    issue["published"] = True
    issue["missing"] = list(src.get("missing") or [])
    with _lock:
        state = load()
        state["issues"][week] = issue
        _save(state)
    return with_topics(issue)


def with_topics(issue: dict) -> dict:
    out = dict(issue)
    out["topics"] = load()["topics"].get(issue["week"], [])
    return out


def issue(week: str = "", today: dt.date = None, sources=None) -> dict:
    """A stored issue; the current week as a draft; or a past week assembled
    from what is still on record."""
    today = today or today_ist()
    week = week or week_id(today)
    a, _ = week_days(week)
    if a > today:
        raise LookupError("That week has not started yet.")
    stored = load()["issues"].get(week)
    if stored:
        return with_topics(stored)
    current = week == week_id(today)
    now = time.time()
    if current and sources is None and _draft["week"] == week and now - _draft["at"] < DRAFT_TTL:
        return with_topics(_draft["body"])
    src = sources if sources is not None else live_sources(week)
    body = build(week, src.get("series"), src.get("flows_record"), src.get("policy_items"),
                 src.get("forum_activity"))
    body["published"] = False
    body["draft"] = current
    body["missing"] = list(src.get("missing") or [])
    if current and sources is None:
        _draft.update(week=week, at=now, body=body)
    return with_topics(body)


def issues() -> list:
    """Every stored issue, newest first, with its first line."""
    state = load()
    return [{"week": w, "label": i.get("label") or week_label(w),
             "headline": (i.get("summary") or [""])[0],
             "topics": len(state["topics"].get(w, []))}
            for w, i in sorted(state["issues"].items(), reverse=True)]


def _clean_text(raw, lo_hi, what) -> str:
    lo, hi = lo_hi
    s = str(raw or "").replace("\r\n", "\n").strip()
    s = re.sub(r"\n{3,}", "\n\n", s)
    if what == "title":
        s = " ".join(s.split())
    if len(s) < lo:
        raise ValueError(f"The {what} needs at least {lo} characters.")
    if len(s) > hi:
        raise ValueError(f"Keep the {what} under {hi:,} characters.")
    return s


def _check_topic(text: str) -> None:
    """The brief is Altaha's own voice, so it is held to the forum's rules on
    tips and promises: no level to trade at, no promised return."""
    import forum
    s = forum.tip_sentence(text)
    if s:
        raise forum.PostRefused("The brief gives no prices to buy or sell at, targets or stop-loss "
                                "levels. Rephrase the sentence below.", s, "tip")
    s = forum.promise_sentence(text)
    if s:
        raise forum.PostRefused("The brief promises no returns. Rephrase the sentence below.", s, "promise")


def add_topic(week: str, title, body, symbols=None) -> dict:
    """A note from the owner, on any subject, in that week's issue."""
    week_days(week)
    t = _clean_text(title, TOPIC_TITLE, "title")
    b = _clean_text(body, TOPIC_BODY, "body")
    _check_topic(t + "\n" + b)
    syms = []
    for s in (symbols if isinstance(symbols, list) else re.split(r"[\s,]+", str(symbols or ""))):
        c = accounts._clean_symbol(s)
        if c and c not in syms:
            syms.append(c)
    topic = {"id": uuid.uuid4().hex[:10], "title": t, "body": b, "symbols": syms[:8],
             "added_at": dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M")}
    with _lock:
        state = load()
        topics = state["topics"].setdefault(week, [])
        if len(topics) >= MAX_TOPICS:
            raise ValueError(f"An issue holds at most {MAX_TOPICS} topics.")
        topics.append(topic)
        _save(state)
    return topic


def delete_topic(week: str, topic_id: str) -> bool:
    week_days(week)
    with _lock:
        state = load()
        before = state["topics"].get(week, [])
        after = [t for t in before if t["id"] != str(topic_id)]
        if len(after) == len(before):
            raise LookupError("No such topic in that week.")
        state["topics"][week] = after
        _save(state)
    return True


# ---------------------------------------------------------------------------
# The email
# ---------------------------------------------------------------------------

def email_subject(issue: dict) -> str:
    return f"The week in brief, {issue['label']}"


def _sign(v, digits=2):
    return ("+" if v > 0 else "") + f"{v:.{digits}f}%" if v is not None else "n/a"


def email_text(issue: dict, site: str = "", unsubscribe_url: str = "") -> str:
    lines = [email_subject(issue), ""]
    lines += issue.get("summary") or []
    m = issue.get("market") or {}
    if m.get("indices"):
        lines += ["", "THE MARKET"]
        lines += [f"  {r['index']}: {r['close']:,.2f} ({_sign(r['week_change_pct'])} on the week)" for r in m["indices"]]
    f = issue.get("flows") or {}
    if f.get("recorded"):
        lines += ["", "MONEY FLOW (₹ crore, provisional)",
                  f"  FII {_whole(f['fii_total']):+,} · DII {_whole(f['dii_total']):+,}"]
    p = issue.get("policy") or {}
    if p.get("items"):
        lines += ["", "NEW RULES THAT MATTER"]
        for r in p["items"]:
            lines.append(f"  {r['source']}: {r['title']} ({r['impact']})")
    fo = issue.get("forum") or {}
    if fo.get("threads"):
        lines += ["", "ON THE FORUM"]
        for t in fo["threads"][:3]:
            lines.append(f"  {t['title']} · {t['posts']} posts" + (f" · {site}/forum.html#t/{t['id']}" if site else ""))
    for t in issue.get("topics") or []:
        lines += ["", t["title"].upper(), t["body"]]
    lines += ["", issue.get("note") or NOTE]
    if site:
        lines += ["", f"Read it on the site: {site}/weekly.html?w={issue['week']}&from=email"]
    if unsubscribe_url:
        lines += ["", "Unsubscribe: " + unsubscribe_url]
    return "\n".join(lines)


def email_html(issue: dict, site: str = "", unsubscribe_url: str = "") -> str:
    from html import escape as e
    sec = lambda title: (f'<h3 style="font:600 12px/1.3 Arial,sans-serif;letter-spacing:.08em;'      # noqa: E731
                         f'text-transform:uppercase;color:#8a6d1e;margin:22px 0 6px">{e(title)}</h3>')
    row = 'style="padding:6px 0;border-top:1px solid #e5e1d8;font-size:14px"'
    out = ['<div style="font-family:Georgia,serif;max-width:620px;margin:0 auto;color:#1a1a1a">',
           f'<h2 style="font-size:22px;margin:0 0 6px">{e(email_subject(issue))}</h2>']
    for s in issue.get("summary") or []:
        out.append(f'<p style="font-size:15px;line-height:1.55;margin:0 0 6px">{e(s)}</p>')
    m = issue.get("market") or {}
    if m.get("indices"):
        out.append(sec("The market"))
        for r in m["indices"]:
            out.append(f'<div {row}>{e(r["index"])}: <b>{r["close"]:,.2f}</b> '
                       f'<span style="color:#6b665c">({e(_sign(r["week_change_pct"]))} on the week)</span></div>')
    f = issue.get("flows") or {}
    if f.get("recorded"):
        out.append(sec("Money flow"))
        out.append(f'<div {row}>FII net <b>{_whole(f["fii_total"]):+,}</b> · DII net <b>{_whole(f["dii_total"]):+,}</b> '
                   f'<span style="color:#6b665c">₹ crore, provisional</span></div>')
    p = issue.get("policy") or {}
    if p.get("items"):
        out.append(sec("New rules that matter"))
        for r in p["items"]:
            title = e(r["title"])
            if r.get("link"):
                title = f'<a href="{e(r["link"])}" style="color:#1a1a1a">{title}</a>'
            out.append(f'<div {row}><span style="color:#6b665c">{e(r["source"])} · {e(r["impact"])}</span><br>{title}</div>')
    fo = issue.get("forum") or {}
    if fo.get("threads"):
        out.append(sec("On the forum"))
        for t in fo["threads"][:3]:
            title = e(t["title"])
            if site:
                title = f'<a href="{e(site)}/forum.html#t/{t["id"]}" style="color:#1a1a1a">{title}</a>'
            out.append(f'<div {row}>{title} <span style="color:#6b665c">· {t["posts"]} posts</span></div>')
    for t in issue.get("topics") or []:
        out.append(sec(t["title"]))
        for para in t["body"].split("\n\n"):
            out.append(f'<p style="font-size:15px;line-height:1.6;margin:0 0 10px">{e(para).replace(chr(10), "<br>")}</p>')
    out.append(f'<p style="font-size:12px;color:#6b665c;border-top:1px solid #e5e1d8;padding-top:12px;margin-top:22px">'
               f'{e(issue.get("note") or NOTE)}</p>')
    if site:
        out.append(f'<p style="font-size:13px"><a href="{e(site)}/weekly.html?w={e(issue["week"])}&amp;from=email">'
                   'Read it on the site</a></p>')
    if unsubscribe_url:
        out.append(f'<p style="font-size:11px;color:#6b665c"><a href="{e(unsubscribe_url)}">Unsubscribe</a></p>')
    out.append("</div>")
    return "".join(out)
