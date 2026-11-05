"""
Writes frontend/tests/fixtures/holdings-statement.xlsx: a broker's holdings
statement in the layout Groww exports (account lines, a summary, then the
table keyed by stock name and ISIN, with no ticker column), for
statement-import.test.js and wealth-browser.cjs.

Everything in it is invented — the client, the code, the quantities and the
prices. A real statement is never committed: it carries a person's name and
client code. The companies are real, so their ISINs resolve. Rebuild with:

    python backend/tests/make_statement_fixture.py
"""
import os

import openpyxl

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   "frontend", "tests", "fixtures", "holdings-statement.xlsx")

ROWS = [
    # name as a statement truncates it, ISIN, qty, avg buy price, closing price
    ("BHARAT ELECTRONICS L", "INE263A01024", 120, 268.40, 412.15),
    ("GAIL (INDIA) LIMITED", "INE129A01019", 300, 171.25, 182.60),
    ("HDFC BANK LIMITED", "INE040A01034", 25, 1612.00, 1955.30),
    ("INFOSYS LIMITED", "INE009A01021", 18, 1745.50, 1521.75),
    ("ITC LIMITED", "INE154A01025", 210, 432.10, 418.95),
    ("TATA CONSULTANCY SERV LT", "INE467B01029", 6, 3890.00, 3402.40),
]


def build(path=OUT):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name", "Priya Raman"])
    ws.append(["Unique Client Code", "1234567890"])
    ws.append([])
    ws.append(["Holdings statement for stocks as on 04-11-2026"])
    ws.append([])
    invested = sum(q * a for _, _, q, a, _ in ROWS)
    closing = sum(q * c for _, _, q, _, c in ROWS)
    ws.append(["Summary"])
    ws.append(["Invested Value", round(invested, 2)])
    ws.append(["Closing Value", round(closing, 2)])
    ws.append(["Unrealised P&L", round(closing - invested, 2)])
    ws.append([])
    ws.append(["Stock Name", "ISIN", "Quantity", "Average buy price", "Buy value", "Closing price",
               "Closing value", "Unrealised P&L"])
    for name, isin, q, a, c in ROWS:
        ws.append([name, isin, q, a, round(q * a, 2), c, round(q * c, 2), round(q * (c - a), 2)])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb.save(path)
    return path


if __name__ == "__main__":
    print(build(), os.path.getsize(OUT), "bytes")
