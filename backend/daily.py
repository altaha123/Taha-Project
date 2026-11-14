"""
Altaha Screener — today in a minute

People sent to this site said they could not tell what they were looking at.
The first screen was a dashboard: an index chart, flows, eleven sector tiles,
eight tool cards. Every figure was right and none of it said what happened.

This writes what happened, in five or six short sentences a person can read in
a minute and forward to a friend: where the market closed, which sectors led
and lagged, who moved most, what foreign and domestic funds did, and how many
companies report results. The same sentences are the top of the home page, the
/today page a search engine can read, and the text that goes out when somebody
taps "Share on WhatsApp".

IT COMPUTES NOTHING NEW
Every number is read from an answer another page already shows: /market, the
sector map, the week's flows, the results calendar and the policy brief. A
part that is missing leaves its sentence out. Nothing is estimated, and nothing
here is a view on what to buy or sell: these are statements of what the market
did, which is all this project may say to a stranger.
"""

import datetime as dt

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
SITE = "https://altahascreener.in"


def _num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def indian(n, places=0):
    """12345678.9 -> '1,23,45,679': the grouping every Indian reader expects."""
    v = _num(n)
    if v is None:
        return "—"
    neg = v < 0
    s = f"{abs(v):.{places}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return ("-" if neg else "") + whole + ("." + frac if frac else "")


def pct(x, sign=False):
    v = _num(x)
    if v is None:
        return "—"
    return (("+" if v > 0 else "−" if v < 0 else "") if sign else "") + f"{abs(v):.2f}%"


def _moved(v, up="rose", down="fell", flat="was flat"):
    v = _num(v)
    if v is None:
        return None
    return up if v > 0.005 else down if v < -0.005 else flat


def _index(market, label):
    for row in (market or {}).get("indices") or []:
        if str(row.get("label", "")).upper() == label:
            return row
    return None


def _market_line(market):
    nifty = _index(market, "NIFTY 50")
    if not nifty or _num(nifty.get("level")) is None:
        return None
    live = (market or {}).get("status") == "open"
    ch = _num(nifty.get("change_pct"))
    word = _moved(ch, "up", "down", "flat")
    if live:
        text = f"Nifty 50 is at {indian(nifty['level'])}"
        text += f", {word} {pct(ch)} so far today." if word != "flat" else ", flat so far today."
    else:
        text = f"Nifty 50 closed at {indian(nifty['level'])}"
        text += f", {word} {pct(ch)}." if word != "flat" else ", flat on the day."
    others = []
    for label, name in (("SENSEX", "Sensex"), ("BANK NIFTY", "Bank Nifty")):
        row = _index(market, label)
        verb = _moved((row or {}).get("change_pct"))
        if row and verb:
            others.append(f"{name} {verb} {pct(row['change_pct'])}" if verb != "was flat"
                          else f"{name} was flat")
    if others:
        text += " " + " and ".join(others) + "."
    return {"key": "market", "label": "Market", "text": text, "anchor": "market",
            "tone": "up" if (ch or 0) > 0 else "down" if (ch or 0) < 0 else "flat"}


def short_name(name):
    """'Phoenix Mills Ltd.' -> 'Phoenix Mills': how a person would say it."""
    out = (name or "").strip()
    for tail in (" Limited", " Ltd.", " Ltd"):
        if out.endswith(tail):
            out = out[: -len(tail)].rstrip(" ,")
    return out


def _sector_lines(sectors, names=None):
    rows = [r for r in (sectors or {}).get("rows") or [] if _num(r.get("change_pct")) is not None]
    if len(rows) < 3:
        return []
    rows = sorted(rows, key=lambda r: -float(r["change_pct"]))
    best, worst = rows[0], rows[-1]
    up = sum(1 for r in rows if float(r["change_pct"]) > 0)
    out = []
    if float(best["change_pct"]) > 0 and float(worst["change_pct"]) < 0:
        text = (f"{best['sector']} led, up {pct(best['change_pct'])}. "
                f"{worst['sector']} was weakest, down {pct(worst['change_pct'])}.")
    elif float(best["change_pct"]) <= 0:
        text = (f"Every sector fell. {best['sector']} held up best, down {pct(best['change_pct'])}; "
                f"{worst['sector']} fell most, {pct(worst['change_pct'])}.")
    else:
        text = (f"Every sector rose. {best['sector']} led, up {pct(best['change_pct'])}; "
                f"{worst['sector']} rose least, {pct(worst['change_pct'])}.")
    if 0 < up < len(rows):
        text += f" {up} of {len(rows)} sectors rose."
    out.append({"key": "sectors", "label": "Sectors", "text": text, "anchor": "sectors",
                "tone": "up" if up * 2 > len(rows) else "down" if up * 2 < len(rows) else "flat"})

    stocks = {}
    for r in rows:
        for s in r.get("stocks") or []:
            if s.get("symbol") and _num(s.get("change_pct")) is not None:
                stocks[s["symbol"]] = float(s["change_pct"])
    if len(stocks) >= 10:
        ranked = sorted(stocks.items(), key=lambda kv: -kv[1])
        (gs, gv), (ls, lv) = ranked[0], ranked[-1]
        say = lambda sym: short_name((names or {}).get(sym)) or sym
        bits = []
        if gv > 0:
            bits.append(f"{say(gs)} gained most among large companies, up {pct(gv)}.")
        if lv < 0:
            bits.append(f"{say(ls)} fell most, down {pct(lv)}.")
        if bits:
            out.append({"key": "movers", "label": "Movers", "text": " ".join(bits),
                        "anchor": "movers", "tone": "flat",
                        "symbols": ([gs] if gv > 0 else []) + ([ls] if lv < 0 else [])})
    return out


def _flow_line(week, today):
    sessions = [s for s in (week or {}).get("sessions") or []
                if ((s.get("flows") or {}).get("fii") or {}).get("net") is not None]
    if not sessions:
        return None
    s = sessions[-1]
    fii = _num(s["flows"]["fii"].get("net"))
    dii = _num(((s["flows"].get("dii") or {}).get("net")))
    if fii is None:
        return None

    def side(v, who):
        return f"{who} {'bought' if v > 0 else 'sold'} ₹{indian(abs(v))} crore of shares"
    text = side(fii, "Foreign investors")
    if dii is not None:
        joiner = "; " if (fii > 0) != (dii > 0) else " and "
        text += joiner + side(dii, "Indian funds").replace(" of shares", "")
    text += "."
    if s.get("date") and s["date"] != today:
        text += f" ({s.get('label') or s['date']}.)"
    return {"key": "flows", "label": "Money", "text": text, "anchor": "market",
            "tone": "up" if fii > 0 else "down"}


def _results_line(calendar, today):
    if not (calendar or {}).get("available"):
        return None
    day = next((d for d in calendar.get("days") or [] if d.get("date") == today), None)
    if not day:
        return None
    declared, pending = int(day.get("declared") or 0), int(day.get("pending") or 0)
    total = declared + pending
    if not total:
        return None
    noun = "company reports" if total == 1 else "companies report"
    text = f"{indian(total)} {noun} results today"
    if declared and pending:
        text += f"; {indian(declared)} filed so far."
    elif declared:
        text += "; all have filed."
    else:
        text += "."
    return {"key": "results", "label": "Results", "text": text, "goto": "discover/results",
            "tone": "flat"}


def _brief_line(brief):
    matter = int((brief or {}).get("matter") or 0)
    if not matter:
        return None
    noun = "circular matters" if matter == 1 else "circulars matter"
    return {"key": "brief", "label": "Policy",
            "text": f"{matter} new government or regulator {noun} for listed companies today.",
            "href": "brief.html", "tone": "flat"}


def _headline(lines):
    by = {l["key"]: l for l in lines}
    m = by.get("market")
    if not m:
        return "Today in the market"
    mood = {"up": "Markets rose", "down": "Markets fell", "flat": "Markets were flat"}[m["tone"]]
    if "is at" in m["text"]:
        mood = {"up": "Markets are up", "down": "Markets are down", "flat": "Markets are flat"}[m["tone"]]
    return mood


def story(market=None, sectors=None, week=None, calendar=None, brief=None, now=None,
          names=None):
    """Today's market in a few sentences. Any argument may be None. `names`
    maps a symbol to its company name, so a sentence can say Phoenix Mills
    where the feed says PHOENIXLTD."""
    now = now or dt.datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    lines = []
    for line in ([_market_line(market)] + _sector_lines(sectors, names)
                 + [_flow_line(week, today), _results_line(calendar, today), _brief_line(brief)]):
        if line:
            lines.append(line)
    day = f"{now.day} {now.strftime('%b %Y')}"
    headline = _headline(lines)
    share = ""
    if lines:
        share = (f"Indian market today, {day}\n\n"
                 + "\n".join("• " + l["text"] for l in lines)
                 + f"\n\nMore at {SITE}/today")
    return {"date": today, "day": day, "weekday": now.strftime("%A"),
            "status": (market or {}).get("status"),
            "headline": headline, "lines": lines, "share_text": share,
            "url": f"{SITE}/today",
            "note": "What the market did, read from the exchange's own figures. "
                    "Not advice."}
