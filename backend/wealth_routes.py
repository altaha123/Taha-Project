"""
wealth_routes.py — every route for the Wealth desk, in one router.

The rules live in wealth.py; this file turns them into HTTP. Errors arrive as
exceptions and leave as status codes, the same table advisor_routes.py uses:

  ValueError       400  something typed is not acceptable, with a sentence
  PermissionError  403  signed in, but there is no desk yet
  LookupError      404  not there — or not yours, which is answered the same,
                        so one manager cannot probe for another's client ids
  sqlite3.Error    503  the accounts database cannot be reached

Routes
  GET    /wealth/desk                          my desk, or null
  PUT    /wealth/desk                          set it up, or edit it
  DELETE /wealth/desk                          everything on it, gone ({confirm: "DELETE"})
  GET    /wealth/book                          the whole book, valued at live prices
  GET    /wealth/demo                          a sample book, no sign-in, nothing stored
  POST   /wealth/clients                       add a client
  PUT    /wealth/clients/{id}                  edit a client, their terms, their status
  DELETE /wealth/clients/{id}                  remove a client and their ledger
  POST   /wealth/clients/{id}/events           add trades / money / dividends / splits
  POST   /wealth/clients/{id}/import           paste rows from a spreadsheet
  DELETE /wealth/clients/{id}/events/{eid}     remove one ledger entry
  PUT    /wealth/clients/{id}/events/{eid}     correct one ledger entry
  PUT    /wealth/clients/{id}/events           correct several at once ({edits: [...]})
  PUT    /wealth/clients/{id}/holdings/{sym}   a holding's average buying / recommended price
  POST   /wealth/isin                          ISINs to NSE symbols, for a broker's statement
  POST   /wealth/clients/{id}/statement/plan   what a holdings statement would change
  POST   /wealth/clients/{id}/statement/apply  take it in
  POST   /wealth/clients/{id}/settle           crystallise the fee for the period
  POST   /wealth/clients/{id}/past             record a settlement made before Altaha
  POST   /wealth/settlements/{sid}             mark due / paid / waived
  DELETE /wealth/settlements/{sid}             undo the latest settlement
  POST   /wealth/recs                          make a recommendation
  PUT    /wealth/recs/{id}                     edit, or close it
  DELETE /wealth/recs/{id}                     delete it (the fills stay)
  POST   /wealth/recs/{id}/apply               book it for many clients at once
  PUT    /wealth/prices                        set (or clear) a hand price
  POST   /wealth/corporate-action              a bonus or split, for every client holding it
  GET    /wealth/shared                        portfolios a manager shows me, read-only
  GET    /wealth/export.csv?what=              holdings | ledger | fees
"""
from __future__ import annotations

import csv
import io
import sqlite3
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import Response

import accounts
import wealth as W

router = APIRouter(tags=["wealth"])

# main.py points this at the universe scan rows already in memory, so a quote
# carries the Altaha Score, the company's name and its sector at no cost.
SCAN_ROWS = lambda: []                                        # noqa: E731
# Tests replace this with a dict of rows; production asks watchlist_quotes.
QUOTES = None


def _bearer(authorization: Optional[str]) -> str:
    if not authorization:
        return ""
    parts = authorization.split(None, 1)
    return parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else ""


def _do(fn, *a, **k):
    try:
        return fn(*a, **k)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except sqlite3.Error as e:
        print(f"[wealth] database: {type(e).__name__}: {e}", flush=True)
        raise HTTPException(503, "The wealth desk is unavailable just now. Try again in a minute.")


def _user(authorization: Optional[str]) -> dict:
    user = _do(accounts.user_for_session, _bearer(authorization))
    if not user:
        raise HTTPException(401, "Sign in to use your wealth desk.")
    return user


def _manager(authorization: Optional[str]) -> dict:
    user = _user(authorization)
    if not _do(W.has_desk, user["id"]):
        raise HTTPException(403, "Set up your wealth desk first.")
    return user


def _quotes(symbols) -> tuple:
    """({SYMBOL: row}, pending, market_open). Asked a hundred at a time, the
    most watchlist_quotes takes; it fetches what is not cached in chunks and
    says which names are still coming."""
    if QUOTES is not None:
        rows = QUOTES() if callable(QUOTES) else QUOTES
        return {s: rows[s] for s in symbols if s in rows}, [], False
    if not symbols:
        return {}, [], False
    try:
        import watchlist_quotes as WQ
    except Exception:                                         # pragma: no cover
        return {}, list(symbols), False
    rows, pending, mo = {}, [], False
    try:
        scan = SCAN_ROWS() or []
    except Exception:
        scan = []
    for i in range(0, len(symbols), WQ.MAX_SYMBOLS):
        try:
            d = WQ.quotes(symbols[i:i + WQ.MAX_SYMBOLS], scan_rows=scan)
        except Exception as e:                                # pragma: no cover
            print(f"[wealth] quotes: {type(e).__name__}: {e}", flush=True)
            pending.extend(symbols[i:i + WQ.MAX_SYMBOLS])
            continue
        mo = d.get("market_open", mo)
        for r in d.get("rows") or []:
            rows[r["symbol"]] = r
        pending.extend(d.get("pending") or [])
    return rows, pending, mo


def _book(user_id: int) -> dict:
    data = _do(W.load, user_id)
    if not data:
        raise HTTPException(403, "Set up your wealth desk first.")
    quotes, pending, mo = _quotes(W.symbols_needed(data))
    return W.compute_book(data, quotes, pending=pending, market_open=mo)


# ── The desk ────────────────────────────────────────────────────────────────

@router.get("/wealth/desk")
def wealth_desk(authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    shared = _do(W.shared_with, user["email"])
    return {"desk": _do(W.get_desk, user["id"]), "email": user["email"], "shared": len(shared),
            "registrations": [{"id": k, "label": v["label"], "hint": v["hint"]}
                              for k, v in W.REGISTRATIONS.items()],
            "default_terms": W.DEFAULT_TERMS, "fee_note": W.FEE_NOTE, "disclaimer": W.DISCLAIMER}


@router.put("/wealth/desk")
def wealth_save_desk(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    return {"desk": _do(W.save_desk, user["id"], payload)}


@router.delete("/wealth/desk")
def wealth_delete_desk(payload: dict = Body(default={}), authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    if str((payload or {}).get("confirm") or "") != "DELETE":
        raise HTTPException(400, 'Type DELETE to confirm. Every client, trade and settlement goes with it.')
    return {"deleted": _do(W.delete_desk, user["id"])}


@router.get("/wealth/book")
def wealth_book(authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    return _book(user["id"])


@router.get("/wealth/demo")
def wealth_demo():
    """A sample desk anyone can open: five invented clients built around
    today's prices, every screen working, nothing stored."""
    quotes, pending, mo = _quotes(W.sample_symbols())
    data = W.sample_data(quotes)
    return W.compute_book(data, quotes, pending=pending, market_open=mo, demo=True)


# ── Clients ─────────────────────────────────────────────────────────────────

@router.post("/wealth/clients")
def wealth_add_client(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    return {"client": _do(W.create_client, user["id"], payload)}


@router.put("/wealth/clients/{client_id}")
def wealth_edit_client(client_id: int, payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    return {"client": _do(W.update_client, user["id"], client_id, payload)}


@router.delete("/wealth/clients/{client_id}")
def wealth_delete_client(client_id: int, authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    return _do(W.delete_client, user["id"], client_id)


@router.post("/wealth/clients/{client_id}/events")
def wealth_add_events(client_id: int, payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    evs = payload.get("events")
    if evs is None and payload.get("kind"):
        evs = [payload]
    return _do(W.add_events, user["id"], client_id, evs)


@router.post("/wealth/clients/{client_id}/import")
def wealth_import(client_id: int, payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    return _do(W.import_rows, user["id"], client_id, payload.get("text"), payload.get("date"))


@router.delete("/wealth/clients/{client_id}/events/{event_id}")
def wealth_delete_event(client_id: int, event_id: int, authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    return _do(W.delete_event, user["id"], client_id, event_id)


@router.put("/wealth/clients/{client_id}/events/{event_id}")
def wealth_edit_event(client_id: int, event_id: int, payload: dict = Body(...),
                      authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    return _do(W.update_events, user["id"], client_id, [dict(payload or {}, id=event_id)])


@router.put("/wealth/clients/{client_id}/events")
def wealth_edit_events(client_id: int, payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    return _do(W.update_events, user["id"], client_id, (payload or {}).get("edits"))


@router.put("/wealth/clients/{client_id}/holdings/{symbol}")
def wealth_edit_holding(client_id: int, symbol: str, payload: dict = Body(...),
                        authorization: Optional[str] = Header(None)):
    """Correct a holding's average buying price (every purchase it draws on
    is scaled by one factor) and/or the recommended price on them."""
    user = _manager(authorization)
    payload = payload or {}
    return _do(W.set_holding, user["id"], client_id, symbol, payload.get("avg"),
               payload.get("rec_price") if "rec_price" in payload else None)


@router.post("/wealth/isin")
def wealth_isin(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    """ISINs to NSE symbols. Only the codes are sent: the statement they came
    from, with the client's name and code on it, stays in the browser."""
    _manager(authorization)
    return _do(W.isin_symbols, (payload or {}).get("isins"))


def _held_quotes(user_id: int, client_id: int):
    data = _do(W.load, user_id)
    syms = sorted({e["symbol"] for e in data["events"].get(client_id, []) if e.get("symbol")}
                  - set(data["prices"]))
    quotes, _, _ = _quotes(syms)
    for s, p in (data["prices"] or {}).items():
        quotes[s] = {"symbol": s, "ltp": p["price"]}
    return quotes


@router.post("/wealth/clients/{client_id}/statement/plan")
def wealth_statement_plan(client_id: int, payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    _do(W._client_row, W._conn(), user["id"], client_id)
    return _do(W.statement_plan, user["id"], client_id, payload, _held_quotes(user["id"], client_id))


@router.post("/wealth/clients/{client_id}/statement/apply")
def wealth_statement_apply(client_id: int, payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    _do(W._client_row, W._conn(), user["id"], client_id)
    return _do(W.statement_apply, user["id"], client_id, payload, _held_quotes(user["id"], client_id))


@router.post("/wealth/clients/{client_id}/settle")
def wealth_settle(client_id: int, payload: dict = Body(default={}), authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    data = _do(W.load, user["id"])
    syms = sorted({e["symbol"] for e in data["events"].get(client_id, []) if e.get("symbol")}
                  - set(data["prices"]))
    quotes, pending, _ = _quotes(syms)
    payload = payload or {}
    return {"settlement": _do(W.settle, user["id"], client_id, quotes, payload.get("as_of"),
                              payload.get("amount"), payload.get("note") or "")}


@router.post("/wealth/clients/{client_id}/past")
def wealth_record_past(client_id: int, payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    return {"settlement": _do(W.record_past, user["id"], client_id, payload)}


@router.post("/wealth/settlements/{settlement_id}")
def wealth_mark(settlement_id: int, payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    return {"settlement": _do(W.mark_settlement, user["id"], settlement_id, payload.get("status"),
                              payload.get("paid_on"))}


@router.delete("/wealth/settlements/{settlement_id}")
def wealth_undo(settlement_id: int, authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    return _do(W.undo_settlement, user["id"], settlement_id)


# ── Recommendations ─────────────────────────────────────────────────────────

@router.post("/wealth/recs")
def wealth_add_rec(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    return {"rec": _do(W.create_rec, user["id"], payload)}


@router.put("/wealth/recs/{rec_id}")
def wealth_edit_rec(rec_id: int, payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    return {"rec": _do(W.update_rec, user["id"], rec_id, payload)}


@router.delete("/wealth/recs/{rec_id}")
def wealth_delete_rec(rec_id: int, authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    return _do(W.delete_rec, user["id"], rec_id)


@router.post("/wealth/recs/{rec_id}/apply")
def wealth_apply_rec(rec_id: int, payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    return _do(W.apply_rec, user["id"], rec_id, payload.get("fills"))


# ── Prices and corporate actions ────────────────────────────────────────────

@router.put("/wealth/prices")
def wealth_set_price(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    return _do(W.set_price, user["id"], payload.get("symbol"), payload.get("price"))


@router.post("/wealth/corporate-action")
def wealth_corporate_action(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    """A bonus or split, written into the ledger of every client who held the
    stock the day before. Yahoo adjusts its prices for these, so without it a
    1:1 bonus would show every holder a 50% loss."""
    user = _manager(authorization)

    def run():
        sym = W.clean_symbol(payload.get("symbol"))
        ev = W.clean_event({"kind": "split", "symbol": sym, "qty": payload.get("factor"),
                            "on_date": payload.get("on_date"), "note": payload.get("note") or "Bonus / split"})
        data = W.load(user["id"])
        done = []
        for c in data["clients"]:
            st = W.replay(data["events"].get(c["id"], []), until=ev["on_date"])
            if st.qty(sym) > 1e-6:
                W.add_events(user["id"], c["id"], [ev])
                done.append(c["id"])
        if not done:
            raise ValueError(f"No client held {sym} on {ev['on_date']}.")
        return {"clients": done, "symbol": sym, "factor": ev["qty"]}

    return _do(run)


# ── A client's own view ─────────────────────────────────────────────────────

@router.get("/wealth/shared")
def wealth_shared(authorization: Optional[str] = Header(None)):
    """What managers have chosen to show the signed-in person: their own
    portfolio with each, read-only, and nothing about anybody else."""
    user = _user(authorization)
    entries = _do(W.shared_with, user["email"])
    if not entries:
        return {"portfolios": []}
    quotes, pending, mo = _quotes(_do(W.shared_symbols, entries))
    return {"portfolios": [_do(W.client_view, e, quotes) for e in entries], "pending": pending,
            "market_open": mo, "disclaimer": W.DISCLAIMER}


# ── Export ──────────────────────────────────────────────────────────────────

def _cell(v):
    """Text a manager typed, made safe for a spreadsheet. A name or note that
    begins with = + - or @ is read by Excel as a formula — the old CSV
    injection — so it is quoted as text. Numbers pass through untouched."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


@router.get("/wealth/export.csv")
def wealth_export(what: str = "holdings", authorization: Optional[str] = Header(None)):
    user = _manager(authorization)
    book = _book(user["id"])
    buf = io.StringIO()
    raw = csv.writer(buf)

    class _Safe:
        def writerow(self, row):
            raw.writerow([_cell(v) for v in row])

    w = _Safe()
    what = (what or "holdings").lower()
    if what == "ledger":
        w.writerow(["client_code", "client", "date", "kind", "symbol", "qty", "price", "amount", "charges",
                    "recommended_price", "note"])
        for c in book["clients"]:
            for e in reversed(c["events"]):
                w.writerow([c["code"], c["name"], e["on_date"], e["kind"], e.get("symbol") or "",
                            e.get("qty") or "", e.get("price") or "", e.get("amount") or "",
                            e.get("charges") or "", e.get("rec_price") or "", e.get("note") or ""])
    elif what == "fees":
        w.writerow(["client_code", "client", "period_start", "period_end", "profit_level", "computed",
                    "billed", "gst", "status", "paid_on"])
        for c in book["clients"]:
            for s in reversed(c["settlements"]):
                lvl = s["level_realised"] if c["terms"]["basis"] == "realised" else s["level_total"]
                w.writerow([c["code"], c["name"], s["period_start"], s["period_end"], lvl, s["computed"],
                            s["amount"], s["gst"], s["status"], s["paid_on"] or ""])
            f = c["fee"]
            w.writerow([c["code"], c["name"], f["period_start"], f["period_end"], f["level"], f["total"],
                        "", f["gst"], "accrued", ""])
    else:
        what = "holdings"
        w.writerow(["client_code", "client", "symbol", "qty", "avg_buy", "recommended", "ltp", "value",
                    "pnl", "pnl_pct", "weight_pct"])
        for c in book["clients"]:
            for h in c["holdings"]:
                w.writerow([c["code"], c["name"], h["symbol"], h["qty"], h["avg"], h["rec_price"] or "",
                            h["ltp"] or "", h["value"], h["pnl"] if h["pnl"] is not None else "",
                            h["pnl_pct"] if h["pnl_pct"] is not None else "", h["weight"] or ""])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="wealth-{what}-{book["as_of"]}.csv"'})
