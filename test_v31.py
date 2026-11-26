import json, tempfile, unittest
from pathlib import Path
from importlib.util import spec_from_file_location,module_from_spec
import pandas as pd
import pymupdf
s=spec_from_file_location('v31',str(Path(__file__).with_name('31_jra_rpdf.py')));m=module_from_spec(s);s.loader.exec_module(m)

class Tests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.base=Path(self.t.name)
 def tearDown(self):self.t.cleanup()
 def test_discovery(self):
  h='<a href="/keiba/rpdf/pdf/20261107-05tokyo01.pdf">5回 東京1日</a><a href="/keiba/rpdf/pdf/20261108-05tokyo02.pdf">東京2日</a><a href="https://evil.example/x.pdf">bogus</a>'
  v=m.discover_rpdf(h,'2026-11-07','東京');self.assertEqual(len(v),1);self.assertTrue(v[0]['url'].endswith('tokyo01.pdf'))
 def test_url_reject(self):
  for url in ['http://www.jra.go.jp/keiba/rpdf/pdf/x.pdf','https://attacker.example/keiba/rpdf/pdf/x.pdf','https://www.jra.go.jp/other.pdf']:
   with self.assertRaises(m.IntakeError):m.allowed_url(url)
 def make_pdf(self):
  doc=pymupdf.open()
  for page_idx in range(3):
   p=doc.new_page(width=1190,height=842)
   for col in range(4):
    r=page_idx*4+col+1;x=col*297.5
    p.insert_text((x+26,60),f'{r}R',fontsize=19)
    for i in range(1,7):
     y=135+i*52
     p.insert_text((x+20,y),str(i),fontsize=12)
     p.insert_text((x+75,y),f'サンプルホース{i}',fontname='japan',fontsize=13)
     p.insert_text((x+172,y),'56',fontsize=12)
  file=self.base/'20261107-05tokyo01.pdf';doc.save(file);return file
 def test_race_panel_and_no_autopublish(self):
  pdf=self.make_pdf();r=m.analyze_pdf(pdf,'2026-11-07','東京',12,self.base/'output')
  self.assertEqual(r['race'],12);self.assertEqual(r['page'],3);self.assertEqual(r['column'],4);self.assertEqual(r['draft_rows'],6)
  self.assertTrue((self.base/'output'/'race_panel.png').is_file())
  self.assertTrue((self.base/'output'/'review_draft.csv').is_file())
  self.assertFalse((self.base/'input'/'racecards').exists())
 def test_publication_rejects_pending_and_atomic(self):
  pdf=self.make_pdf();out=self.base/'output';m.analyze_pdf(pdf,'2026-11-07','東京',3,out)
  f=out/'review_draft.csv';df=pd.DataFrame([dict(race_date='2026-11-07',course='東京',race_number='3',horse_number=str(i),horse_name='サンプル馬'+str(i),surface='芝',distance='1600',carried_weight='56',jockey='騎手',trainer='調教師',verified='NO') for i in range(1,7)]);df.to_csv(f,index=False,encoding='utf-8-sig')
  with self.assertRaises(m.IntakeError):m.check_and_publish(f,'2026-11-07','東京',3,self.base/'input'/'racecards',6)
  df.loc[:,'verified']='YES';df.to_csv(f,index=False,encoding='utf-8-sig')
  with self.assertRaises(m.IntakeError):m.check_and_publish(f,'2026-11-07','東京',3,self.base/'input'/'racecards',7)
  result=m.check_and_publish(f,'2026-11-07','東京',3,self.base/'input'/'racecards',6);self.assertEqual(result['runners'],6)
  before=Path(result['file']).read_bytes();df.loc[0,'horse_number']='19';df.to_csv(f,index=False,encoding='utf-8-sig')
  with self.assertRaises(m.IntakeError):m.check_and_publish(f,'2026-11-07','東京',3,self.base/'input'/'racecards',6)
  self.assertEqual(before,Path(result['file']).read_bytes())
 def test_verified_csv_loads_in_existing_mvp(self):
  from importlib.machinery import SourceFileLoader
  core=SourceFileLoader('mvp_v31_test',str(Path(__file__).with_name('26_mvp_core.py'))).load_module()
  data=[dict(race_date='2026-11-07',course='東京',race_number='12',horse_number=str(i),horse_name=f'サンプル馬{i}',surface='芝',distance='1600',carried_weight='56',jockey='騎手',trainer='調教師',verified='YES') for i in range(1,7)]
  source=self.base/'verified.csv';pd.DataFrame(data).to_csv(source,index=False,encoding='utf-8-sig')
  m.check_and_publish(source,'2026-11-07','東京',12,self.base/'racecards',6)
  cards,errors=core.load_cards(self.base/'racecards')
  self.assertEqual(len(cards),6);self.assertFalse(errors);self.assertEqual(cards.race_number.iloc[0],12)

 def test_4_column_no_race_contamination(self):
  path=self.make_pdf();doc,spans,width,cand,summary=m._pdf_parse_core(path.read_bytes(),6,'2026-11-07','東京')
  self.assertEqual(summary['column'],2);self.assertTrue(summary['race_heading_detected']);self.assertTrue(all(z['x0']>=0 for z in spans))

if __name__=='__main__':unittest.main(verbosity=2)
