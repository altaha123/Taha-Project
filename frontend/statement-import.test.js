/* Reading a broker's holdings statement in the browser (statement-import.js).

   Every failure here is silent. A summary line ("Invested Value 2,02,279")
   read as a holding of two lakh shares; a statement whose names are cut short
   ("TATA CONSULTANCY SERV LT") matching nothing; a "Buy value" column taken
   for the buying price, so every average is the whole cost; a date read as
   the 11th of April instead of the 4th of November. Nothing throws — the
   preview just shows a portfolio that is not the one in the file. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');

const S = require('./statement-import.js');

const UNIVERSE = [
  { s: 'BEL', n: 'Bharat Electronics Limited' },
  { s: 'GAIL', n: 'GAIL (India) Limited' },
  { s: 'HDFCBANK', n: 'HDFC Bank Limited' },
  { s: 'INFY', n: 'Infosys Limited' },
  { s: 'ITC', n: 'ITC Limited' },
  { s: 'TCS', n: 'Tata Consultancy Services Limited' },
  { s: 'TATAPOWER', n: 'Tata Power Company Limited' },
  { s: 'NATIONALUM', n: 'National Aluminium Company Limited' },
  { s: 'TNPETRO', n: 'Tamilnadu Petroproducts Limited' }
];
const idx = S.indexUniverse(UNIVERSE);

// A tiny zip writer, so the test can also build an .xlsx the way other
// generators do: inline strings, and one part stored without compression.
function zip(entries) {
  const crcTable = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc = b => { let c = 0xffffffff; for (const x of b) c = crcTable[(c ^ x) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  const locals = [], central = [];
  let off = 0;
  for (const [name, text, store] of entries) {
    const raw = Buffer.from(text), data = store ? raw : zlib.deflateRawSync(raw), nm = Buffer.from(name);
    const lh = Buffer.alloc(30);
    lh.writeUInt32LE(0x04034b50, 0); lh.writeUInt16LE(20, 4); lh.writeUInt16LE(store ? 0 : 8, 8);
    lh.writeUInt32LE(crc(raw), 14); lh.writeUInt32LE(data.length, 18); lh.writeUInt32LE(raw.length, 22);
    lh.writeUInt16LE(nm.length, 26);
    const ch = Buffer.alloc(46);
    ch.writeUInt32LE(0x02014b50, 0); ch.writeUInt16LE(20, 4); ch.writeUInt16LE(20, 6); ch.writeUInt16LE(store ? 0 : 8, 10);
    ch.writeUInt32LE(crc(raw), 16); ch.writeUInt32LE(data.length, 20); ch.writeUInt32LE(raw.length, 24);
    ch.writeUInt16LE(nm.length, 28); ch.writeUInt32LE(off, 42);
    locals.push(lh, nm, data);
    central.push(ch, nm);
    off += 30 + nm.length + data.length;
  }
  const cd = Buffer.concat(central), end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(cd.length, 12); end.writeUInt32LE(off, 16);
  const all = Buffer.concat([...locals, cd, end]);
  return all.buffer.slice(all.byteOffset, all.byteOffset + all.length);
}

(async () => {
  // ── A Groww-shaped statement, as openpyxl writes it ──────────────────
  const buf = fs.readFileSync(path.join(__dirname, 'tests', 'fixtures', 'holdings-statement.xlsx'));
  const rows = await S.readXlsx(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length));
  const st = S.extract(rows, 'Stocks_Holdings_Statement_1234567890_04-11-2026.xlsx');
  assert.equal(st.meta.client, 'Priya Raman');
  assert.equal(st.meta.code, '1234567890');
  assert.equal(st.meta.as_of, '2026-11-04', 'the statement is as on 4 November, not 11 April');
  assert.equal(st.holdings.length, 6, 'the summary block above the table is not holdings');
  const bel = st.holdings.find(h => h.isin === 'INE263A01024');
  assert.deepEqual([bel.qty, bel.avg, bel.close], [120, 268.4, 412.15], '"Buy value" is not the buying price');
  assert.equal(bel.name, 'BHARAT ELECTRONICS L');

  // By ISIN — exact — when the map has it.
  const byIsin = S.resolve(st.holdings, idx, { INE263A01024: 'BEL', INE467B01029: 'TCS' });
  assert.equal(byIsin.find(h => h.isin === 'INE263A01024').how, 'isin');
  // And by name for the rest, including names the statement cut short.
  const got = Object.fromEntries(S.resolve(st.holdings, idx, {}).map(h => [h.name, h.symbol]));
  assert.deepEqual(got, {
    'BHARAT ELECTRONICS L': 'BEL', 'GAIL (INDIA) LIMITED': 'GAIL', 'HDFC BANK LIMITED': 'HDFCBANK',
    'INFOSYS LIMITED': 'INFY', 'ITC LIMITED': 'ITC', 'TATA CONSULTANCY SERV LT': 'TCS'
  });
  const r = S.resolve([{ label: 'NATIONAL ALUMINIUM CO LTD', name: 'NATIONAL ALUMINIUM CO LTD', qty: 1 },
                       { label: 'TAMILNADU PETROPRODUCTS L', name: 'TAMILNADU PETROPRODUCTS L', qty: 1 },
                       { label: 'TATA', name: 'TATA', qty: 1 }], idx, {});
  assert.deepEqual(r.map(h => h.symbol), ['NATIONALUM', 'TNPETRO', ''], 'an ambiguous name is not guessed');
  assert.ok(r[2].candidates.length >= 0);

  // ── Inline strings and a stored part, as other generators write ──────
  const sheet = '<?xml version="1.0"?><worksheet><sheetData>' +
    '<row r="1"><c r="A1" t="inlineStr"><is><t>Holdings as on 15-Oct-2026</t></is></c></row>' +
    '<row r="3"><c r="A3" t="inlineStr"><is><t>Symbol</t></is></c><c r="B3" t="inlineStr"><is><t>Qty.</t></is></c>' +
    '<c r="C3" t="inlineStr"><is><t>Avg. cost</t></is></c><c r="E3" t="inlineStr"><is><t>LTP</t></is></c>' +
    '<c r="F3" t="inlineStr"><is><t>Buy date</t></is></c></row>' +
    '<row r="4"><c r="A4" t="inlineStr"><is><t>M&amp;M</t></is></c><c r="B4"><v>12</v></c><c r="C4"><v>2901.5</v></c>' +
    '<c r="E4"><v>3120</v></c><c r="F4"><v>45658</v></c></row>' +
    '<row r="5"/>' +
    '<row r="6"><c r="A6" t="inlineStr"><is><t>Total</t></is></c><c r="B6"><v>12</v></c></row>' +
    '</sheetData></worksheet>';
  const x2 = await S.readXlsx(zip([['[Content_Types].xml', '<Types/>', true], ['xl/worksheets/sheet1.xml', sheet, false]]));
  const s2 = S.extract(x2);
  assert.equal(s2.meta.as_of, '2026-10-15');
  assert.equal(s2.holdings.length, 1, 'a Total line is not a holding');
  assert.deepEqual(s2.holdings[0], Object.assign({}, s2.holdings[0],
    { symbol: 'M&M', qty: 12, avg: 2901.5, close: 3120, date: '2025-01-01' }), 'an Excel date serial is a date');

  // ── CSV: a Zerodha-shaped file, and a list typed by hand ─────────────
  const z = S.extract(S.parseCSV('"Instrument","Qty.","Avg. cost","LTP","Cur. val","P&L","Net chg.","Day chg."\n' +
    '"INFY",20,"1,520.25",1501.1,30022,-383,-1.26,0.4\n"TCS-EQ",4,3300,3402.4,13609.6,409.6,3.1,0.2\n'));
  assert.deepEqual(z.holdings.map(h => [h.symbol, h.qty, h.avg, h.close]), [['INFY', 20, 1520.25, 1501.1], ['TCS', 4, 3300, 3402.4]]);
  assert.deepEqual(S.resolve(z.holdings, idx, {}).map(h => h.how), ['symbol', 'symbol']);
  const typed = S.extract(S.parseCSV('INFY,20,1500\nITC\t100\t410\t03/01/2025\t400'));
  assert.equal(typed.header, false);
  assert.deepEqual(typed.holdings.map(h => [h.symbol, h.qty, h.avg]), [['INFY', 20, 1500]],
    'one delimiter per paste; the tab row is not split by commas');
  const tabbed = S.extract(S.parseCSV('ITC\t100\t410\t03/01/2025\t400'));
  assert.deepEqual(tabbed.holdings.map(h => [h.symbol, h.qty, h.avg, h.date, h.rec]), [['ITC', 100, 410, '2025-01-03', 400]]);

  // ── What is refused, and how it says so ──────────────────────────────
  await assert.rejects(S.readFile({ name: 'holdings.xls', arrayBuffer: async () => new ArrayBuffer(8) }), /save it as \.xlsx or CSV/);
  await assert.rejects(S.readXlsx(new ArrayBuffer(64)), /does not look like an \.xlsx/);

  // ── Whose statement is this ──────────────────────────────────────────
  assert.equal(S.sameName('Priya Raman', 'Priya R. Raman'), true);
  assert.equal(S.sameName('Rajankumar Baburam Shukla', 'R. B. Shukla'), true);
  assert.equal(S.sameName('Priya Raman', 'Arjun Mehta'), false);

  console.log('statement import: xlsx and csv read in the browser, names and ISINs resolved, summaries skipped');
})().catch(e => { console.error(e); process.exit(1); });
