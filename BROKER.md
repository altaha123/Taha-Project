# Connect your broker

A member links their own Dhan account to Altaha. On **Your broker**
(Portfolio › Your broker, `broker.html`) they see their funds, today's orders,
positions and holdings, cancel an open order, and copy their real holdings
into their Altaha portfolio in one tap. Once the owner switches orders on, a
**Trade** button beside the price on every Indian stock page opens an order
ticket. The order goes to Dhan and shows up in the member's Dhan app like any
other order.

Altaha is not the broker. Dhan executes every order and holds every rupee.

| file | what it does |
| --- | --- |
| `backend/brokers.py` | The rules: connecting, the encrypted token, order checks, limits, the kill switch |
| `backend/broker_dhan.py` | Dhan's API: login consent, orders, holdings, positions, funds |
| `backend/broker_routes.py` | The HTTP routes (`/broker/config`, `/me/broker/*`, `/admin/broker*`) |
| `frontend/broker.js`, `broker.css` | The order ticket and the Trade button on the stock page |
| `frontend/broker.html`, `broker-page.js` | Your broker: the connection, funds, orders, positions, holdings |
| `backend/tests/test_brokers.py`, `test_broker_dhan.py` | The safety rules, and the exact requests sent to Dhan |

---

## Switching it on

It is built in two stages, and each one is off until you turn it on.

**Stage 1: connect and see.** Members connect Dhan and see their account.
No order can be placed.

| Where | Setting | Why |
| --- | --- | --- |
| Render → Environment | `BROKER_TOKEN_KEY` | Encrypts every member's Dhan token at rest. Make one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. **Without it nothing connects**, because tokens are never stored in the clear |
| Render → Environment | `DHAN_PARTNER_ID`, `DHAN_PARTNER_SECRET` | Issued by Dhan to a platform. Any Dhan customer can then connect |
| Dhan partner settings | Redirect URL `https://altahascreener.in/broker` | Where Dhan sends the member back after they log in |

**While the partner application is pending**, you can test with your own
Dhan account instead of partner keys:

| Where | Setting | Why |
| --- | --- | --- |
| Render → Environment | `DHAN_API_KEY`, `DHAN_API_SECRET` | The API key you make on web.dhan.co › My Profile › Access DhanHQ APIs, with the redirect URL above |
| Render → Environment | `DHAN_CLIENT_ID` | Already set for market data. It names the one Dhan account this key can log in |
| Render → Environment | `BROKER_MEMBERS` | Your Altaha email. **Required in this mode**: only one Dhan account can ever log in with your key, so nobody else is offered the button |

`BROKER_MEMBERS` also works with partner keys, as a comma-separated beta list.
Leave it empty to open connections to every signed-in member.

**Stage 2: place orders.** Two more things are needed:

1. **Dhan must accept orders from the server's IP address.** Under SEBI's 2025
   rules, Dhan accepts placing, modifying and cancelling orders only from a
   whitelisted static IP. Reading funds, holdings and orders does not need
   it. Render's outbound addresses are shared ranges, not one fixed address,
   so **ask Dhan how this applies to a partner platform** and whether your
   outbound IPs can be whitelisted, or whether a dedicated egress IP is
   needed. If this is wrong, orders come back rejected with Dhan's reason on
   the screen. Nothing else breaks.
2. Set `BROKER_TRADING=on` on Render.

| Setting | Default | What it limits |
| --- | --- | --- |
| `BROKER_MAX_ORDER_VALUE` | 500000 | Rupees per order. Larger orders go through the broker's own app |
| `BROKER_MAX_ORDERS_PER_DAY` | 50 | Orders per member per day (India time) |
| `BROKER_MAX_ORDERS_PER_MINUTE` | 10 | Orders per member per minute. Stops a runaway script |

## The kill switch

To stop every order from Altaha at once, without a deploy:

```bash
curl -X POST https://taha-project.onrender.com/admin/broker/halt \
     -H 'X-Admin-Key: <ADMIN_KEY>' -H 'Content-Type: application/json' -d '{"halted": true}'
```

Send `{"halted": false}` to restart. Connections and reading still work while
orders are halted. `GET /admin/broker` shows how many members are linked,
today's orders by status, and any order still marked as unconfirmed.

Each member can also pause trading on their own account from Your broker.

## How it keeps a member's money safe

- **No passwords.** The member logs in on Dhan's own page. Altaha receives a
  token that Dhan ends by itself (about a day). It never sees a password, PIN,
  OTP or TOTP secret.
- **The token is encrypted** with `BROKER_TOKEN_KEY`. A copy of the database
  without the key cannot trade. `BROKER_TOKEN_KEY` takes a comma-separated
  list, newest first, so you can rotate the key. Tokens under a key you drop
  read as "log in to Dhan again", never as an error.
- **A login has to be started here.** Dhan sends the member back with a
  one-time id and nothing that says who they are. The server only accepts it
  for a login that this same member started in the last fifteen minutes and
  has not finished.
- **An order is never sent twice.** The ticket names each order when Review is
  pressed. The server writes the order down under that name before calling
  Dhan, so a double tap, a retry or a second tab finds the first order and
  sends nothing.
- **An order Dhan did not confirm is never guessed at, and never retried.**
  On a timeout, a dropped connection or a restart mid-call, the order reads
  "Not confirmed" and the member is told to check before placing it again.
  The next look asks Dhan for it by its correlation id. After ten minutes
  with no record at Dhan, it is marked not placed.
- **Typos are caught before they leave.** A limit or trigger price more than
  20% from the market is refused. A market order is valued at the server's
  live price, not the one the page sent.
- **A broker session ending is not a sign-out.** It comes back as 409 with
  `reconnect: true`. A 401 would make the site sign the member out of Altaha.

## The line it does not cross

The ticket takes the stock and its last price from the page, and nothing else
from Altaha. No score, level, target or pick fills a field, and there is no
Buy button on Ideas, the Portfolio review or any list of picks. The member
types the quantity and the price. A Buy button pre-filled from Altaha's
research would be a recommendation to trade, which needs SEBI registration
this project does not have (see the README). Keep it that way unless that
changes.

## Checking it works

1. Set stage 1, sign in, open Portfolio › Your broker and press **Connect
   Dhan**. Log in on Dhan's page. You should land back on Your broker with
   "Connected to Dhan" and your real funds and holdings.
2. Press **Copy to my Altaha portfolio**, then open the Portfolio review.
3. For stage 2, set `BROKER_TRADING=on`. Open a liquid stock, press **Trade**
   and place a one-share limit order well below the market. Check it appears
   in the Dhan app, then cancel it from Today's orders.

## Not built yet

- Other brokers. Each one is a module with the same functions as
  `broker_dhan.py`, added to `brokers._adapters()`. Zerodha (Kite Connect),
  Upstox and Angel One all have similar login and order APIs.
- Modifying an open order (cancel and place again for now), after-market
  orders, bracket and cover orders, F&O.
- Dhan's postback (order updates pushed to us). The ticket polls for a minute
  instead, and Today's orders reads the order book.
