"""
Altaha Screener — the exchange's trading calendar

WHY THIS EXISTS
On Tuesday 24 November 2026 the site said the market was open all day. It was
Guru Nanak Jayanti and NSE did not trade. Everything that asked "is the market
open?" asked a clock: a weekday between 09:15 and 15:30. A clock does not know
a holiday.

/market was meant to know. It asked Dhan for the market's status and let the
answer overrule the clock. But Dhan has no such call: the address it asked,
/v2/marketfeed/marketstatus, answers 404, and has on every request since the
line was written. So the clock had always decided alone.

WHERE THE DAYS COME FROM
NSE publishes its trading holidays for the year, by segment, at
/api/holiday-master?type=trading. The capital-market list is read from there,
kept on the data disk, and read again twice a day, because the exchange does
add a holiday at short notice (15 January 2026, a municipal election, was one).

WHAT IT DOES NOT KNOW
  · A special session on a day the list calls a holiday or on a weekend: the
    hour of Muhurat trading on Diwali, a Saturday budget session. Those days
    read as closed here, as they did by the clock.
  · Anything, until the list has been read once. Then every weekday is a
    trading day, which is what the clock assumed. A request never waits for
    NSE: the list is fetched on a background thread and the answer in hand is
    given meanwhile.
"""

import datetime as dt
import json
import os
import threading
import time

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
URL = "https://www.nseindia.com/api/holiday-master"
REFERER = "https://www.nseindia.com/resources/exchange-communication-holidays"
SEGMENT = "CM"                  # capital market: the equity session
REFRESH = 12 * 3600             # read the list again this often
RETRY = 30 * 60                 # after a read that failed
OPEN_MIN = 9 * 60 + 15          # 09:15
CLOSE_MIN = 15 * 60 + 30        # 15:30

_PATH = os.path.join(os.environ.get("DATA_DIR", "").strip()
                     or os.path.dirname(os.path.abspath(__file__)), "nse_holidays.json")
_state = {"days": {}, "at": 0.0, "loaded": False, "retry_at": 0.0}
_busy = threading.Lock()


def now():
    """The clock, in IST. A function so a test can set the day and the hour."""
    return dt.datetime.now(IST)


def parse(body, segment=SEGMENT) -> dict:
    """NSE's holiday list -> {"2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev"}.

    {} for anything that is not the list, so a refusal or a changed shape is
    never read as "no holidays this year"."""
    rows = body.get(segment) if isinstance(body, dict) else None
    out = {}
    for r in rows if isinstance(rows, list) else []:
        try:
            day = dt.datetime.strptime(str(r.get("tradingDate", "")).strip(), "%d-%b-%Y").date()
        except (AttributeError, ValueError):
            continue
        out[day.isoformat()] = str(r.get("description") or "").strip() or "Trading holiday"
    return out


def _fetch():
    """The capital-market holidays from NSE, or {}. Replaced in tests."""
    import nse_http
    return parse(nse_http.get_json(URL, params={"type": "trading"}, referer=REFERER))


def _load():
    try:
        with open(_PATH) as fh:
            blob = json.load(fh)
        days = blob.get("days")
        if isinstance(days, dict):
            _state.update(days={str(k): str(v) for k, v in days.items()},
                          at=float(blob.get("at") or 0))
    except Exception:
        pass


def _save():
    try:
        tmp = _PATH + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"at": _state["at"], "days": _state["days"]}, fh)
        os.replace(tmp, _PATH)
    except Exception:
        pass


def _merge(fresh: dict) -> dict:
    """The list just read, over what was held. A year NSE answered for is
    replaced whole, so a holiday the exchange withdraws is withdrawn here;
    last year's days are kept for anything that still asks about them."""
    years = {d[:4] for d in fresh}
    kept = {d: name for d, name in _state["days"].items() if d[:4] not in years}
    return {**kept, **fresh}


def refresh() -> bool:
    """Read the list from NSE now. True when it answered with one."""
    try:
        fresh = _fetch()
    except Exception:
        fresh = {}
    if not fresh:
        _state["retry_at"] = time.time() + RETRY
        return False
    _state.update(days=_merge(fresh), at=time.time(), retry_at=0.0)
    _save()
    return True


def _refresh_in_background():
    if not _busy.acquire(blocking=False):
        return

    def run():
        try:
            refresh()
        finally:
            _busy.release()

    try:
        threading.Thread(target=run, daemon=True, name="nse-holidays").start()
    except Exception:
        _busy.release()


def holidays() -> dict:
    """Every trading holiday held, {ISO date: name}. Never waits for NSE."""
    if not _state["loaded"]:
        _state["loaded"] = True
        _load()
    now = time.time()
    if now - _state["at"] > REFRESH and now >= _state["retry_at"]:
        _refresh_in_background()
    return _state["days"]


def holiday(day):
    """The name of the trading holiday on `day`, or None.

    None also when the list has not been read yet: a day is a holiday only on
    the exchange's word."""
    try:
        return holidays().get(day.isoformat())
    except Exception:
        return None


def trading_day(day) -> bool:
    """Monday to Friday and not a listed holiday."""
    return day.weekday() < 5 and not holiday(day)


def session(at=None):
    """The NSE equity session at `at`: (status, holiday).

    status is "pre" before 09:15 on a trading day, "open" from 09:15 to 15:30,
    "closed" otherwise. holiday is the day's name when a holiday is why a
    weekday is closed, else None."""
    n = (at or now()).astimezone(IST)
    if n.weekday() >= 5:
        return "closed", None
    name = holiday(n.date())
    if name:
        return "closed", name
    mins = n.hour * 60 + n.minute
    if mins < OPEN_MIN:
        return "pre", None
    return ("open" if mins < CLOSE_MIN else "closed"), None


def status() -> dict:
    """What is held and how old it is, for /datasource."""
    days = holidays()
    return {"holidays": len(days),
            "read_at": (dt.datetime.fromtimestamp(_state["at"], IST).isoformat(timespec="seconds")
                        if _state["at"] else None),
            "source": "NSE holiday-master, capital market"}
