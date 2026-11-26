# -*- coding: utf-8 -*-
import csv,importlib.util,json,tempfile,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path

script=Path(__file__).with_name('27_racecard_fetch.py')
spec=importlib.util.spec_from_file_location('fetch27',script)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class TestRealPipeline(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)
  self.src=self.p/'exports';self.src.mkdir();self.dest=self.p/'racecards'
  self.config=self.p/'provider.json'
  self.config.write_text(json.dumps({'provider_name':'test_export','provider_type':'local_export',
   'authorized':True,'directory':str(self.src),'filename_template':'{date}_{course}_{race2}R.csv','format':'csv'}),encoding='utf8')
  self.rows=[dict(race_date='2026-11-29',course='東京',race_number='11',horse_number=str(i),horse_name=f'TEST_HORSE_{i}',surface='芝',distance='2400',carried_weight='57',jockey='TEST_JOCKEY',trainer='TEST_TRAINER',track_condition='良',win_odds=str(2+i),place_odds='',odds_timestamp='') for i in range(1,7)]
  self.file=self.src/'2026-11-29_東京_11R.csv'
  self.write(self.rows)
 def tearDown(self):self.tmp.cleanup()
 def write(self,rows):
  with self.file.open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.DictWriter(f,fieldnames=list(self.rows[0]));w.writeheader();w.writerows(rows)
 def run_fetch(self):return m.run(self.config,'2026-11-29','東京',11,self.dest)
 def test_success_and_v26_schema(self):
  result=self.run_fetch();self.assertEqual(result['runners'],6)
  self.assertEqual(result['odds_count'],6);self.assertEqual(result['odds_with_timestamp'],0)
  import pandas as pd
  out=pd.read_csv(self.dest/'2026-11-29_東京_11R.csv')
  self.assertEqual(len(out),6)
  self.assertIn('source_provider',out.columns)
  self.assertTrue(set(m.REQUIRED).issubset(out.columns))
 def test_idempotent_and_unsafe_payload_keeps_previous(self):
  result=self.run_fetch();b=(self.dest/'2026-11-29_東京_11R.csv').read_bytes()
  self.assertEqual(result['runners'],self.run_fetch()['runners'])
  wrong=[x.copy() for x in self.rows];wrong[1]['horse_number']='1';self.write(wrong)
  with self.assertRaisesRegex(ValueError,'Duplicate'):self.run_fetch()
  self.assertEqual(b,(self.dest/'2026-11-29_東京_11R.csv').read_bytes())
 def test_wrong_race_rejected(self):
  wrong=[x.copy() for x in self.rows];wrong[1]['course']='阪神';self.write(wrong)
  with self.assertRaisesRegex(ValueError,'wrong race'):self.run_fetch()
 def test_future_odds_timestamp_rejected(self):
  wrong=[x.copy() for x in self.rows];wrong[1]['odds_timestamp']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat();self.write(wrong)
  with self.assertRaisesRegex(ValueError,'odds_timestamp'):self.run_fetch()
 def test_not_authorized(self):
  cfg=json.loads(self.config.read_text());cfg['authorized']=False;self.config.write_text(json.dumps(cfg))
  with self.assertRaisesRegex(ValueError,'authorized'):self.run_fetch()
 def test_bad_sex_or_name_controls(self):
  wrong=[x.copy() for x in self.rows];wrong[0]['horse_name']='\x06BAD';self.write(wrong)
  with self.assertRaisesRegex(ValueError,'malformed'):self.run_fetch()
 def test_json_nested(self):
  obj={'runners':self.rows};self.assertEqual(len(m.parse_payload(json.dumps(obj).encode(),'json')),6)

if __name__=='__main__':unittest.main(verbosity=2)
