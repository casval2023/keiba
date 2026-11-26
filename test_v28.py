from __future__ import annotations
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

P=Path(__file__).with_name('28_scrape_racecard.py')
spec=importlib.util.spec_from_file_location('racecard_scrape',P)
scrape=importlib.util.module_from_spec(spec);spec.loader.exec_module(scrape)

def fixture(n=7,offset=0,duplicate=False):
 rows=[]
 for i in range(1,n+1):
  num=(1 if duplicate and i==n else i+offset)
  rows.append(f'<tr class="HorseList"><td class="Umaban">{num}</td>'
   f'<td class="HorseInfo"><a href="/horse/2026{i:06d}/">テスト馬{i}</a></td>'
   f'<td class="Kinryo">55.0</td><td class="Jockey"><a href="/jockey/12/">テスト騎手{i}</a></td>'
   f'<td class="Trainer"><a href="/trainer/12/">テスト調教師{i}</a></td><td class="Odds">{2+i}.5</td></tr>')
 return ('<html><head><title>2026年11月29日 東京11R 出馬表</title></head>'
         '<body><div class="RaceData01">15:00 / 芝2000m</div><table class="RaceTable01">'
         +''.join(rows)+'</table></body></html>').encode('utf-8')

class TestScraper(unittest.TestCase):
 def test_seven_runner_html_to_mvp_csv(self):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);(d/'test.html').write_bytes(fixture())
   args=SimpleNamespace(html=str(d/'test.html'),url='',date='2026-11-29',course='東京',race=11,source_url='',out=str(d/'out'),report=str(d/'report.json'),confirm_permission=False,dry_run=False)
   x=scrape.run(args)
   self.assertEqual(x['runners'],7);self.assertEqual(x['quality'],'PARSER_VALIDATED_NOT_SOURCE_VERIFIED')
   self.assertTrue((d/'out'/'2026-11-29_東京_11R.csv').is_file())
   self.assertEqual(x['odds_with_timestamp'],0)
   x2=scrape.run(args);self.assertEqual(x2['status'],'UNCHANGED')
 def test_reject_wrong_date(self):
  with self.assertRaisesRegex(ValueError,'date does not match'):
   scrape.parse_html(fixture(),'2026-11-28','東京',11,'file.html')
 def test_reject_duplicate_and_preserve(self):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);(d/'ok.html').write_bytes(fixture())
   args=SimpleNamespace(html=str(d/'ok.html'),url='',date='2026-11-29',course='東京',race=11,source_url='',out=str(d/'out'),report=str(d/'report.json'),confirm_permission=False,dry_run=False)
   scrape.run(args)
   target=d/'out'/'2026-11-29_東京_11R.csv';content=target.read_bytes()
   (d/'bad.html').write_bytes(fixture(duplicate=True));args.html=str(d/'bad.html')
   with self.assertRaisesRegex(ValueError,'Duplicate'):scrape.run(args)
   self.assertEqual(target.read_bytes(),content)
 def test_reject_non_race_page(self):
  with self.assertRaisesRegex(ValueError,'Surface/distance'):
   scrape.parse_html(b'<html><title>Not a race</title></html>','2026-11-29','東京',11,'offline')
 def test_reject_live_without_permission(self):
  with self.assertRaises(PermissionError):scrape.download('https://race.netkeiba.com/race/shutuba.html?race_id=202605050811',False)

if __name__=='__main__':unittest.main(verbosity=2)
