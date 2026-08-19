"""
livefeed.py — Altaha Live Price Relay
======================================

WHAT THIS DOES (plain English):
Your chart wants live prices. Dhan streams them over a WebSocket. But that
WebSocket needs your access token, and a token sitting in browser JavaScript
is a token anyone can read and use to place orders on your account.

So the browser never talks to Dhan. It talks to YOUR server, and your server
talks to Dhan. One connection to Dhan is shared by every visitor, the token
never leaves the machine, and if the WebSocket fails the whole thing quietly
falls back to polling Dhan's normal REST quote endpoint.

THE SHAPE OF IT:

    Browser  --SSE-->  your backend  --WebSocket-->  Dhan
    (no token)         (holds token)                 (one shared connection)

WHY SSE AND NOT A WEBSOCKET TO THE BROWSER:
Your chart already speaks Server-Sent Events — charts.js opens
`EventSource(API + "/stream/quotes?tickers=...")` and expects `{"ltp": ...}`.
SSE is one-directional, which is all a price feed needs, and it reconnects by
itself. Building a browser WebSocket would mean rewriting working frontend code
for no gain.

FAILURE BEHAVIOUR (deliberate):
Every failure degrades rather than breaks.
  · Dhan WebSocket won't connect  -> REST polling, chart still ticks
  · Token expired                 -> dhan_source refreshes it, we reconnect
  · Symbol not in instrument master -> that symbol is skipped, others continue
  · Market closed                 -> stream stays open, sends heartbeats
Nothing here can take down the rest of the API.
"""

import asyncio
import json
import struct
import time

import dhan_source as D

# --- Dhan WebSocket protocol constants -------------------------------------
# From Dhan's v2 live market feed spec. These are wire-format values; changing
# them will silently produce garbage prices rather than an error.

WS_URL = "wss://api-feed.dhan.co"

REQ_SUBSCRIBE_TICKER = 15      # LTP + last-traded-time only. Smallest packet.
REQ_UNSUBSCRIBE_TICKER = 16
REQ_DISCONNECT = 12

FEED_TICKER = 2                # ticker packet
FEED_PREV_CLOSE = 6
FEED_DISCONNECT = 50

HEADER_LEN = 8                 # code(1) + msg_len(2) + segment(1) + security_id(4)
MAX_PER_MESSAGE = 100          # Dhan's cap per subscribe message

EXCHANGE_SEGMENT = "NSE_EQ"

# How long a symbol stays subscribed after the last viewer leaves. Avoids
# thrashing the subscription when someone flips between two stocks.
LINGER_SECONDS = 90

# REST fallback cadence when the WebSocket is unavailable.
FALLBACK_POLL_SECONDS = 3.0

# Heartbeat so an idle stream doesn't look dead to the browser.
HEARTBEAT_SECONDS = 15.0


class _Feed:
    """
    One shared connection to Dhan, fanned out to every SSE client.

    Deliberately a singleton: Dhan limits connections per account, and opening
    one per browser tab would exhaust that immediately.
    """

    def __init__(self):
        self.prices = {}           # symbol -> {"ltp": float, "at": epoch}
        self.watch = {}            # symbol -> last-wanted epoch (for linger)
        self.sid_to_sym = {}       # Dhan securityId -> symbol
        self.sym_to_sid = {}
        self.subscribed = set()    # securityIds currently live on the socket
        self.ws = None
        self.task = None
        self.mode = "idle"         # "websocket" | "rest" | "idle"
        self.last_error = None
        self.connected_at = None
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()

    # -- public ------------------------------------------------------------

    def want(self, symbols):
        """Register interest. Returns the symbols we could actually resolve."""
        now = time.time()
        resolved = []
        for s in symbols:
            sym = (s or "").upper().replace(".NS", "").strip()
            if not sym:
                continue
            self.watch[sym] = now
            if sym not in self.sym_to_sid:
                try:
                    sid = D.security_id(sym)
                except Exception:
                    sid = None
                if sid:
                    sid = str(sid)
                    self.sym_to_sid[sym] = sid
                    self.sid_to_sym[sid] = sym
            if sym in self.sym_to_sid:
                resolved.append(sym)
        self._wake.set()
        return resolved

    def snapshot(self, symbols):
        """Latest known price for each symbol, or None."""
        out = {}
        for s in symbols:
            sym = (s or "").upper().replace(".NS", "").strip()
            p = self.prices.get(sym)
            if p:
                out[sym] = {"ltp": p["ltp"], "age": round(time.time() - p["at"], 1)}
        return out

    def status(self):
        return {
            "mode": self.mode,
            "watching": len(self._active_symbols()),
            "subscribed": len(self.subscribed),
            "prices_held": len(self.prices),
            "connected_at": self.connected_at,
            "last_error": self.last_error,
            "dhan_configured": D.configured() if hasattr(D, "configured") else None,
        }

    def ensure_running(self):
        """Start the background pump once, lazily, on first subscriber."""
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._pump())

    # -- internals ---------------------------------------------------------

    def _active_symbols(self):
        """Symbols wanted recently enough to still be worth streaming."""
        cutoff = time.time() - LINGER_SECONDS
        return {s for s, t in self.watch.items() if t >= cutoff}

    def _prune(self):
        cutoff = time.time() - LINGER_SECONDS
        for s in [s for s, t in self.watch.items() if t < cutoff]:
            self.watch.pop(s, None)

    async def _pump(self):
        """
        Outer supervisor. Keeps a Dhan connection alive for as long as anyone
        is watching, and never raises — a dead feed must not kill the API.
        """
        backoff = 1.0
        while True:
            try:
                if not self._active_symbols():
                    self.mode = "idle"
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), timeout=30)
                    except asyncio.TimeoutError:
                        pass
                    continue

                ok = await self._run_websocket()
                if ok:
                    backoff = 1.0
                else:
                    # WebSocket unavailable — serve from REST so the chart
                    # still ticks, then retry the socket after a pause.
                    await self._run_rest(seconds=min(60.0, backoff * 10))
                    backoff = min(backoff * 2, 30.0)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {str(e)[:160]}"
                await asyncio.sleep(min(backoff, 15.0))
                backoff = min(backoff * 2, 30.0)

    async def _run_websocket(self):
        """
        Connect and stream until the socket drops.
        Returns True if we successfully connected at least once.
        """
        try:
            import websockets
        except ImportError:
            self.last_error = ("websockets package not installed — add "
                               "'websockets' to requirements.txt for live "
                               "streaming; using REST fallback")
            return False

        tok = D.token()
        if not tok or not D.CLIENT_ID:
            self.last_error = "Dhan credentials not configured"
            return False

        url = (f"{WS_URL}?version=2&token={tok}"
               f"&clientId={D.CLIENT_ID}&authType=2")

        try:
            async with websockets.connect(url, ping_interval=20,
                                          ping_timeout=20,
                                          close_timeout=5,
                                          max_size=2 ** 20) as ws:
                self.ws = ws
                self.mode = "websocket"
                self.connected_at = time.time()
                self.last_error = None
                self.subscribed = set()

                await self._sync_subscriptions(ws)
                resync = asyncio.create_task(self._resync_loop(ws))
                try:
                    async for raw in ws:
                        if isinstance(raw, (bytes, bytearray)):
                            self._decode(raw)
                finally:
                    resync.cancel()
                return True
        except Exception as e:
            self.last_error = f"WebSocket: {type(e).__name__}: {str(e)[:140]}"
            self.ws = None
            return False
        finally:
            self.ws = None
            if self.mode == "websocket":
                self.mode = "idle"

    async def _resync_loop(self, ws):
        """Subscribe to newly-requested symbols while the socket is up."""
        try:
            while True:
                await asyncio.sleep(2.0)
                self._prune()
                await self._sync_subscriptions(ws)
        except asyncio.CancelledError:
            return
        except Exception:
            return

    async def _sync_subscriptions(self, ws):
        """Send subscribe messages for anything wanted but not yet on the wire."""
        async with self._lock:
            wanted_sids = {self.sym_to_sid[s] for s in self._active_symbols()
                           if s in self.sym_to_sid}
            new = list(wanted_sids - self.subscribed)
            if not new:
                return
            for i in range(0, len(new), MAX_PER_MESSAGE):
                chunk = new[i:i + MAX_PER_MESSAGE]
                msg = {
                    "RequestCode": REQ_SUBSCRIBE_TICKER,
                    "InstrumentCount": len(chunk),
                    "InstrumentList": [
                        {"ExchangeSegment": EXCHANGE_SEGMENT, "SecurityId": sid}
                        for sid in chunk
                    ],
                }
                await ws.send(json.dumps(msg))
                self.subscribed.update(chunk)

    def _decode(self, buf):
        """
        Parse Dhan's binary feed.

        Packets arrive back-to-back in one frame, so this walks the buffer
        rather than assuming one packet per message. Little-endian throughout.

        Ticker packet layout:
            offset 0  uint8   feed response code
            offset 1  int16   message length
            offset 3  uint8   exchange segment
            offset 4  int32   security id
            offset 8  float32 last traded price
            offset 12 int32   last traded time
        """
        n = len(buf)
        pos = 0
        now = time.time()

        while pos + HEADER_LEN <= n:
            try:
                code = buf[pos]
                msg_len = struct.unpack_from("<h", buf, pos + 1)[0]
                sid = struct.unpack_from("<i", buf, pos + 4)[0]
            except Exception:
                return

            if msg_len <= 0 or pos + msg_len > n:
                # Truncated or nonsense length — stop rather than misread the
                # rest of the buffer as prices.
                return

            if code == FEED_DISCONNECT:
                self.last_error = "Dhan sent feed disconnect"
                return

            if code in (FEED_TICKER, FEED_PREV_CLOSE) and pos + 12 <= n:
                try:
                    ltp = struct.unpack_from("<f", buf, pos + 8)[0]
                except Exception:
                    ltp = None
                sym = self.sid_to_sym.get(str(sid))
                if sym and ltp and ltp > 0 and code == FEED_TICKER:
                    self.prices[sym] = {"ltp": round(float(ltp), 2), "at": now}

            pos += msg_len

    async def _run_rest(self, seconds=30.0):
        """
        Fallback: poll Dhan's REST quote endpoint.

        Slower and heavier than the socket, but it keeps the chart alive when
        the WebSocket can't connect — which is the difference between a chart
        that lags and a chart that looks broken.
        """
        self.mode = "rest"
        deadline = time.time() + seconds
        loop = asyncio.get_event_loop()

        while time.time() < deadline:
            syms = sorted(self._active_symbols())
            if not syms:
                return
            try:
                # dhan_source is synchronous requests — keep it off the event
                # loop so one slow call doesn't stall every SSE client.
                quotes = await loop.run_in_executor(None, self._rest_batch, syms)
                now = time.time()
                for sym, ltp in (quotes or {}).items():
                    if ltp:
                        self.prices[sym] = {"ltp": round(float(ltp), 2), "at": now}
            except Exception as e:
                self.last_error = f"REST: {type(e).__name__}: {str(e)[:120]}"
            await asyncio.sleep(FALLBACK_POLL_SECONDS)

    def _rest_batch(self, syms):
        """Best-effort batch quote via whatever dhan_source exposes."""
        out = {}
        for fn_name in ("quotes", "quote_batch", "ltp_batch"):
            fn = getattr(D, fn_name, None)
            if callable(fn):
                try:
                    res = fn(syms)
                    if isinstance(res, dict):
                        for k, v in res.items():
                            sym = str(k).upper().replace(".NS", "")
                            ltp = v.get("ltp") if isinstance(v, dict) else v
                            if ltp:
                                out[sym] = ltp
                        if out:
                            return out
                except Exception:
                    pass
        # Single-symbol fallback
        fn = getattr(D, "quote", None)
        if callable(fn):
            for s in syms[:20]:
                try:
                    q = fn(s)
                    ltp = q.get("ltp") if isinstance(q, dict) else None
                    if ltp:
                        out[s] = ltp
                except Exception:
                    continue
        return out


FEED = _Feed()


# ---------------------------------------------------------------------------
# SSE generator — what the endpoint in main.py actually streams
# ---------------------------------------------------------------------------

async def sse_quotes(tickers: str):
    """
    Yields Server-Sent Events for the requested symbols.

    Emits only when a price actually changes, plus a heartbeat so the browser
    and any proxy in between know the connection is alive. charts.js reads
    `{"ltp": ...}` for a single symbol and `{"SYM": {"ltp": ...}}` for several,
    which is the contract this honours.
    """
    syms = [s.strip().upper().replace(".NS", "")
            for s in (tickers or "").split(",") if s.strip()]
    syms = syms[:50]
    if not syms:
        yield "event: error\ndata: {\"error\":\"no tickers\"}\n\n"
        return

    FEED.want(syms)
    FEED.ensure_running()

    single = len(syms) == 1
    last_sent = {}
    last_beat = 0.0

    # Immediate first frame if we already hold a price — no blank chart while
    # waiting for the next tick.
    try:
        while True:
            FEED.want(syms)          # refresh interest so linger doesn't expire
            snap = FEED.snapshot(syms)

            changed = {s: v for s, v in snap.items()
                       if last_sent.get(s) != v["ltp"]}

            if changed:
                for s, v in changed.items():
                    last_sent[s] = v["ltp"]
                if single:
                    sym = syms[0]
                    if sym in changed:
                        payload = {"symbol": sym, "ltp": changed[sym]["ltp"],
                                   "mode": FEED.mode}
                        yield f"data: {json.dumps(payload)}\n\n"
                else:
                    payload = {s: {"ltp": v["ltp"]} for s, v in changed.items()}
                    payload["mode"] = FEED.mode
                    yield f"data: {json.dumps(payload)}\n\n"
                last_beat = time.time()

            elif time.time() - last_beat > HEARTBEAT_SECONDS:
                # Comment frame: keeps the connection warm without the browser
                # treating it as data.
                yield f": heartbeat {FEED.mode}\n\n"
                last_beat = time.time()

            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        return
    except Exception:
        return
