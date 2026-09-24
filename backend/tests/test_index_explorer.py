import sys
import unittest
import tempfile
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import index_explorer as E

RAW='modelDataAvailable({"groups":[{"label":"Cars 60%","weight":60,"groups":[{"label":"A 60%","weight":60,"date":"31-08-2026"},]},{"label":"Parts 40%","weight":40,"groups":[{"label":"B 40%","weight":40,"date":"31-08-2026"}]}]}, {label:"ignore"});'
class Weights(unittest.TestCase):
 def test_published_weights_and_date(self):
  d=E.parse_weights(RAW);self.assertEqual(d['as_of'],'2026-08-31');self.assertEqual(d['groups'][0]['name'],'Cars');self.assertEqual(d['groups'][0]['stocks'][0],{'symbol':'A','weight_pct':60})
 def test_partial_rejected(self):
  with self.assertRaises(ValueError):E.parse_weights(RAW.replace('"weight":40','"weight":30'))
 def test_mixed_dates_rejected(self):
  with self.assertRaises(ValueError):E.parse_weights(RAW.replace('31-08-2026','30-09-2026',1))
 def test_duplicate_symbol_rejected(self):
  with self.assertRaises(ValueError):E.parse_weights(RAW.replace('B 40%','A 40%'))
 def test_no_eval(self):
  with self.assertRaises(ValueError):E.parse_weights('alert(1)')
 def test_no_missing_weight_estimation(self):
  with self.assertRaises(ValueError):E.parse_weights(RAW.replace('"weight":60','"weight":null'))
 def test_refreshes_changed_publication_after_one_hour(self):
  E._cache.clear()
  with tempfile.TemporaryDirectory() as tmp, patch.dict(E.os.environ, {'DATA_DIR':tmp}):
   with patch.object(E.time,'time',return_value=10000):
    first=E.cached('monthly-test',lambda:{'as_of':'2026-08-31'})
   with patch.object(E.time,'time',return_value=13601):
    second=E.cached('monthly-test',lambda:{'as_of':'2026-09-30'})
   self.assertNotEqual(first['data']['as_of'],second['data']['as_of'])
 def test_failed_refresh_retains_dated_snapshot(self):
  E._cache.clear()
  with tempfile.TemporaryDirectory() as tmp, patch.dict(E.os.environ, {'DATA_DIR':tmp}):
   with patch.object(E.time,'time',return_value=10000):
    E.cached('failure-test',lambda:{'as_of':'2026-08-31'})
   with patch.object(E.time,'time',return_value=13601):
    result=E.cached('failure-test',lambda:None)
   self.assertTrue(result['stale']);self.assertEqual(result['data']['as_of'],'2026-08-31')
if __name__=='__main__':unittest.main()
