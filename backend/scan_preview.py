"""Small, current-run-only discovery snapshots; no market requests or scoring."""
import math


def preview_row(row):
    score = row.get('composite')
    if not isinstance(score, (int, float)) or not math.isfinite(score):
        score = None
    return {
        'symbol': str(row.get('symbol') or '')[:40],
        'name': str(row.get('name') or row.get('symbol') or '')[:140],
        'score': round(score, 1) if score is not None else None,
        'sector': str(row.get('sector') or 'Sector unavailable')[:100],
        'finding': ('Setup: ' + str(row['setup'])[:120]) if row.get('setup') else
                   ('Fundamental data unavailable' if row.get('fundamental') is None else
                    'Technical and fundamental analysis available'),
    }


class ScanPreview:
    def __init__(self):
        self.seen = set()
        self.snapshot = {'discoveries': [], 'planet_batches': []}
        self.sequence = 0

    def checkpoint(self, payload):
        # Only called by this run's worker; never read an older cached payload.
        fresh = []
        for row in payload.get('factor_universe') or payload.get('rankings') or []:
            symbol = row.get('symbol')
            if not symbol or symbol in self.seen:
                continue
            self.seen.add(symbol)
            fresh.append(preview_row(row))
        if not fresh:
            return self.snapshot
        self.sequence += 1
        batches = list(self.snapshot['planet_batches'])
        batch = {'number': self.sequence, 'count': len(fresh), 'rows': fresh[:3]}
        # Keep five early discoveries and the latest checkpoint, bounded at six.
        if len(batches) < 6:
            batches.append(batch)
        else:
            batches[5] = batch
        self.snapshot = {
            'discoveries': (fresh + self.snapshot['discoveries'])[:6],
            'planet_batches': batches,
        }
        return self.snapshot
