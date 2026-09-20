import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scan_preview import ScanPreview


def row(symbol, score=71.2):
    return {'symbol': symbol, 'name': symbol, 'composite': score, 'setup': 'Momentum', 'sector': 'Industrials'}


def test_only_current_run_checkpoints_and_no_duplicate_discoveries():
    tracker = ScanPreview()
    assert tracker.snapshot == {'discoveries': [], 'planet_batches': []}
    snapshot = tracker.checkpoint({'rankings': [row('A'), row('B')]})
    assert snapshot['planet_batches'][0]['count'] == 2
    assert snapshot['discoveries'][0]['finding'] == 'Setup: Momentum'
    assert tracker.checkpoint({'rankings': [row('A'), row('B')]}) is snapshot
    new = tracker.checkpoint({'rankings': [row('A'), row('B'), row('C')]})
    assert new['discoveries'][0]['symbol'] == 'C'
    assert snapshot['discoveries'][0]['symbol'] == 'A'  # old responses remain immutable
    assert ScanPreview().snapshot['discoveries'] == []


def test_bounded_response_and_nonfinite_scores():
    tracker = ScanPreview()
    for i in range(20):
        result = tracker.checkpoint({'factor_universe': [row(str(i), float('nan'))]})
    assert len(result['discoveries']) == 6
    assert len(result['planet_batches']) == 6
    assert result['planet_batches'][-1]['number'] == 20
    assert result['discoveries'][0]['score'] is None
    json.dumps(result, allow_nan=False)
