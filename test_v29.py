# -*- coding: utf-8 -*-
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch
from urllib.error import HTTPError
import tempfile

P=Path(__file__).resolve().parent

def load(name,file):
 spec=importlib.util.spec_from_file_location(name,P/file)
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

src=load('sources_v29','29_sources.py')
scr=load('scrape_v29','28_scrape_racecard.py')
original=load('test_v28_data','test_v28.py')

class TestV29(TestCase):
 def test_parent_links_are_https_and_site_nav(self):
  self.assertEqual(len(src.SOURCES),3)
  for s in src.SOURCES:
   self.assertTrue(s['url'].startswith('https://'))
 def test_valid_race_url(self):
  url='https://race.netkeiba.com/race/shutuba.html?race_id=202605050811'
  self.assertEqual(src.validate_target_url(url),url)
 def test_invalid_domain_and_root_rejected(self):
  for url in ['https://example.org/race','http://race.netkeiba.com/race/shutuba.html','https://race.netkeiba.com/','https://race.netkeiba.com:8443/race/shutuba.html']:
   with self.assertRaises(ValueError):src.validate_target_url(url)
 def test_url_success_with_mocked_allowed_one_shot_download(self):
  with tempfile.TemporaryDirectory() as d:
   args=SimpleNamespace(html='',url='https://race.netkeiba.com/race/shutuba.html?race_id=202605050811',source_url='',date='2026-11-29',course='東京',race=11,out=str(Path(d)/'racecards'),report=str(Path(d)/'report.json'),confirm_permission=True,dry_run=False)
   with patch.object(scr,'download',return_value=original.fixture()):
    r=scr.run(args)
   self.assertEqual(r['runners'],7)
   self.assertEqual(r['odds_with_timestamp'],0)
   self.assertEqual(r['quality'],'PARSER_VALIDATED_NOT_SOURCE_VERIFIED')
   self.assertTrue((Path(d)/'racecards'/'2026-11-29_東京_11R.csv').exists())
 def test_failed_download_preserves_existing(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d)/'racecards';out.mkdir()
   prior=out/'2026-11-29_東京_11R.csv';prior.write_text('OLD',encoding='utf-8')
   args=SimpleNamespace(html='',url='https://race.netkeiba.com/race/shutuba.html?race_id=202605050811',source_url='',date='2026-11-29',course='東京',race=11,out=str(out),report='',confirm_permission=True,dry_run=False)
   with patch.object(scr,'download',side_effect=PermissionError('robots denied')):
    with self.assertRaises(PermissionError):scr.run(args)
   self.assertEqual(prior.read_text(encoding='utf-8'),'OLD')
 def test_online_permission_required(self):
  with self.assertRaises(PermissionError):scr.download('https://race.netkeiba.com/race/shutuba.html?race_id=202605050811',False)

if __name__=='__main__':main(verbosity=2)
