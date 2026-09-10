'use strict';
/*
 * The event list is a promise: ANALYTICS.md says these are the only things
 * this site collects, and this is what keeps that true. It runs in CI with no
 * browser, which is why analytics.js touches window only inside functions.
 */
const assert = require('node:assert/strict');
const { EVENTS, cleanProps, cleanValue } = require('./analytics.js');

// Names are snake_case and past tense; properties are lowercase identifiers.
// A stray capital or a hyphen makes two events that read as one in a funnel.
for (const [name, props] of Object.entries(EVENTS)) {
  assert.match(name, /^[a-z][a-z0-9_]*$/, `event name not snake_case: ${name}`);
  assert.ok(Array.isArray(props), `${name} must declare its properties`);
  for (const p of props) assert.match(p, /^[a-z][a-z0-9_]*$/, `bad property ${name}.${p}`);
}

// An unknown event is dropped, not guessed at. This is the guarantee that the
// documented list is the collected list.
assert.equal(cleanProps('not_an_event', { ticker: 'INFY' }), null);

// Only whitelisted properties survive. Somebody adding a field at a call site
// cannot start collecting it by accident.
assert.deepEqual(
  cleanProps('stock_viewed', { ticker: 'INFY', sector: 'IT', score: 71, email: 'a@b.com' }),
  { ticker: 'INFY', sector: 'IT', score: 71 });

// Free text is capped. The search box is the one field a user can type
// anything into, so it is cut hardest.
const long = 'X'.repeat(200);
assert.equal(cleanProps('search_no_match', { query: long }).query.length, 40);
assert.equal(cleanValue(long).length, 64);

// Empty, missing and non-finite values are omitted rather than sent as junk.
assert.deepEqual(cleanProps('chart_failed', { range: '6M', status: NaN }), { range: '6M' });
assert.deepEqual(cleanProps('stock_viewed', { ticker: '  ', sector: null }), {});

// A zero must survive: "score: 0" is a fact, and falsy-checking it away is the
// classic way a metric quietly stops existing.
assert.deepEqual(cleanProps('watchlist_changed', { ticker: 'INFY', action: 'removed', size: 0 }),
  { ticker: 'INFY', action: 'removed', size: 0 });

console.log(`Analytics event contract passed (${Object.keys(EVENTS).length} events)`);
