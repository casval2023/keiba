# -*- coding: utf-8 -*-
"""JRA official racecard PDF intake: explicit single-race download, conservative PDF extraction.
PDF layout is editorial and can change; never promote unverified rows to prediction CSV.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, re, sys, tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin,urlparse
from urllib.request import Request,urlopen
from urllib.robotparser import RobotFileParser
import pandas as pd
try:
 import pymupdf as fitz
except ImportError:
 import fitz

INDEX_URL='https://www.jra.go.jp/keiba/rpdf/'
VENUE_EN={'東京':'tokyo','中山':'nakayama','京都':'kyoto','阪神':'hanshin','中京':'chukyo','小倉':'kokura','新潟':'niigata','福島':'fukushima','札幌':'sapporo','函館':'hakodate'}
USER_AGENT='KeibaPersonalResearchPDF/1.0 (single manual request; no crawling)'
HEADERS={'User-Agent':USER_AGENT,'Accept':'text/html,application/pdf'}
PAGE_SIZE_LIMIT=12_000_000

class IntakeError(Exception):pass

def allowed_url(url,kind='pdf'):
 p=urlparse(url)
 if p.scheme!='https' or p.hostname not in ('www.jra.go.jp','jra.jp'):raise IntakeError('JRA公式のHTTPS URLではありません')
 if p.username or p.password or p.port or p.fragment:raise IntakeError('URL形式が不適切です')
 if kind=='pdf' and not (p.path.startswith('/keiba/rpdf/pdf/') and p.path.lower().endswith('.pdf')):
  raise IntakeError('開催場別出馬表PDFのURLではありません')
 if kind=='index' and not p.path.rstrip('/') in ('/keiba/rpdf','/keiba/rpdf/index.html'):
  raise IntakeError('出馬表一覧ページではありません')
 return url

def _read_url(url,kind='pdf',max_bytes=PAGE_SIZE_LIMIT):
 """One requested official resource. Strict TLS verification via Windows OS trust.

 urllib.robotparser uses urllib internally, so truststore must be activated BEFORE
 RobotFileParser.read(), not just before urlopen(pdf).
 """
 allowed_url(url,kind)
 try:
  import truststore
 except ImportError as exc:
  raise IntakeError('HTTPS証明書検証用のtruststoreが未導入です。python -m pip install truststore を実行してください') from exc
 try:
  truststore.inject_into_ssl()
 except Exception as exc:
  raise IntakeError(f'Windows証明書ストアを使用できません：{exc}') from exc
 robots=RobotFileParser();robots.set_url(f'https://{urlparse(url).hostname}/robots.txt')
 try:
  robots.read()
 except Exception as exc:
  raise IntakeError(f'robots.txtを確認できません（PDFをブラウザ保存してください）：{exc}') from exc
 if not robots.mtime():
  raise IntakeError('robots.txtの取得状態を確認できません（PDFをブラウザ保存してください）')
 if not robots.can_fetch(USER_AGENT,url):
  raise IntakeError('robots.txtにより取得が許可されていません（PDFをブラウザ保存してください）')
 req=Request(url,headers=HEADERS)
 try:
  with urlopen(req,timeout=18) as r:
   final=r.geturl();allowed_url(final,kind)
   raw=r.read(max_bytes+1)
 except Exception as exc:
  raise IntakeError(f'HTTP取得に失敗：{exc}') from exc
 if len(raw)>max_bytes:raise IntakeError('PDF/HTMLがサイズ上限を超えています')
 if kind=='pdf' and not raw.startswith(b'%PDF-'):raise IntakeError('取得内容がPDFではありません')
 return raw

def discover_rpdf(pdf_index_html:bytes|str,date:str,course:str):
 """Parse only JRA-rpdf published links. Dates are read from PDF filenames, never guessed from headers."""
 from html.parser import HTMLParser
 class Links(HTMLParser):
  def __init__(self):super().__init__();self.href=None;self.items=[];self.tmp=[]
  def handle_starttag(self,tag,attrs):
   if tag=='a':self.href=dict(attrs).get('href');self.tmp=[]
  def handle_data(self,data):
   if self.href is not None:self.tmp.append(data)
  def handle_endtag(self,tag):
   if tag=='a' and self.href is not None:self.items.append((self.href,''.join(self.tmp).strip()));self.href=None
 p=Links();p.feed(pdf_index_html.decode('utf-8','replace') if isinstance(pdf_index_html,bytes) else pdf_index_html)
 ymd=date.replace('-',''); venue=VENUE_EN.get(course)
 if not venue:raise IntakeError(f'競馬場が不正：{course}')
 results=[]
 for href,label in p.items:
  full=urljoin(INDEX_URL,href)
  try:allowed_url(full,'pdf')
  except IntakeError:continue
  name=Path(urlparse(full).path).name.lower()
  if name.startswith(ymd+'-') and re.search(r'\d+'+re.escape(venue)+r'\d+',name):results.append({'url':full,'label':label,'filename':name})
 return results

def verify_pdf_identity(pdf_path,date,course):
 name=Path(pdf_path).name.lower();ymd=date.replace('-','');v=VENUE_EN[course]
 # JRA filenames: 20261107-05tokyo01.pdf; provenance must be checked separately for manually renamed files.
 if not (name.startswith(ymd+'-') and re.search(r'\d+'+re.escape(v)+r'\d+',name)):
  raise IntakeError('PDFファイル名と開催日・競馬場が一致しません。元のJRAファイル名のまま保存してください')

def _panel_spans(page,race):
 """Four race columns on each page; return spatial text spans for selected race."""
 page_no=(int(race)-1)//4; col=(int(race)-1)%4
 if page_no>=page.parent.page_count:raise IntakeError(f'PDFページ数不足：{race}Rは{page_no+1}ページ目が必要です')
 # True PDF page can have bleed/margins. Four equal editorial columns.
 width=page.rect.width/4
 xlo=col*width; xhi=(col+1)*width
 spans=[]
 for blk in page.get_text('dict')['blocks']:
  if blk.get('type')!=0:continue
  for line in blk.get('lines',[]):
   for span in line.get('spans',[]):
    x0,y0,x1,y1=span['bbox'];mid=(x0+x1)/2
    if xlo<=mid<xhi:
     spans.append({'text':span['text'].strip(),'x0':x0-xlo,'x1':x1-xlo,'y0':y0,'y1':y1,'size':span['size']})
 return spans,width

def _find_race_header(spans,race):
 # Text stream may split R numeral and R; use rough search near upper 20%.
 text=' '.join(z['text'] for z in spans if z['y0']<130)
 return bool(re.search(r'(?<!\d)'+str(int(race))+r'\s*R\b',text,re.I)) or bool(re.search(r'(?<!\d)'+str(int(race))+r'\s*Ｒ',text))

def _group_rows(spans,width):
 """Candidate extraction anchored to font-size prominence and horse-number gutters.
 This intentionally prefers rejection over silently corrupting horse identities.
 """
 # Main table in JRA rpdf: x within each panel: number gutter ~6-15%; name ~16-50%; weight 52-61%, jockey 64-83%.
 # Each horse block is several text lines. Detect horse name on largest Japanese script span in name corridor.
 # Anchor headers and footer are excluded using vertical position and panel relative size.
 japanese=re.compile(r'[\u3040-\u30ff\u3400-\u9fffー]{2,}')
 no_control=lambda x:''.join(c for c in x if ord(c)>=32 and ord(c)!=127)
 candidates=[]
 for z in spans:
  s=no_control(z['text']).strip();xm=(z['x0']+z['x1'])/2/width
  if z['y0']<65 or xm<.14 or xm>.53:continue
  if not japanese.search(s) or len(s)>24:continue
  if any(t in s for t in ('未勝利','歳以上','競馬場','生産','競走','頭','発走','本賞','父','母','牡','牝')):continue
  # Exclude small pedigree/trainer text with font size threshold relative to local text spans.
  candidates.append({**z,'name':s})
 return candidates

def _pdf_parse_core(pdf_bytes,race:int,date:str,course:str):
 try:doc=fitz.open(stream=pdf_bytes,filetype='pdf')
 except Exception as e:raise IntakeError(f'PDFを開けません：{e}')
 page_idx=(race-1)//4
 if page_idx>=len(doc):raise IntakeError(f'{race}RがPDF内にありません（{len(doc)}ページ）')
 spans,width=_panel_spans(doc[page_idx],race)
 candidates=_group_rows(spans,width)
 preview={'race':race,'page':page_idx+1,'column':(race-1)%4+1,'pdf_pages':len(doc),
          'span_count':len(spans),'race_heading_detected':_find_race_header(spans,race),
          'name_candidates':len(candidates),'name_examples':[c['name'] for c in candidates[:30]],
          'note':'Extraction is REVIEW ONLY until every runner/field has been verified.'}
 return doc,spans,width,candidates,preview

def _create_review_draft(spans,candidates,width,date,course,race):
 """Best-effort extraction; NO record is pre-approved. Gutter IDs and names are provisional."""
 keys=['race_date','course','race_number','horse_number','horse_name','surface','distance',
       'carried_weight','jockey','trainer','track_condition','win_odds','place_odds','odds_timestamp','verified']
 if not candidates:return pd.DataFrame(columns=keys)
 # A runner name normally uses a larger font than pedigree or owner notes.
 sizes=sorted(c['size'] for c in candidates)
 threshold=max(5.0,sizes[int(len(sizes)*.75)]*.82)
 prominents=sorted([c for c in candidates if c['size']>=threshold],key=lambda x:x['y0'])
 # Remove duplicate spans for one printed horse name without altering the original source PDF.
 selected=[]
 for c in prominents:
  if selected and abs(c['y0']-selected[-1]['y0'])<5:continue
  if not any(re.search(r'[ァ-ヴー]{2,}',c['name']) for _ in [0]):continue
  selected.append(c)
 rows=[]
 for cand in selected:
  cy=(cand['y0']+cand['y1'])/2
  # Race panel number gutter contains runner numbers. Never infer by row ordering alone.
  near=[z for z in spans if z['x0']/width<.20 and abs((z['y0']+z['y1'])/2-cy)<10 and re.fullmatch(r'\s*(?:[1-9]|1[0-8])\s*',z['text'])]
  number=str(min(near,key=lambda z:abs((z['y0']+z['y1'])/2-cy))['text']).strip() if near else ''
  # Weight appears to the right of the horse name, but the exact coordinates vary with publication.
  weights=[z for z in spans if .49<=z['x0']/width<=.78 and abs((z['y0']+z['y1'])/2-cy)<12 and re.fullmatch(r'(?:4[5-9]|5\d|6[0-5])(?:\.\d)?',z['text'])]
  weight=weights[0]['text'] if len(weights)==1 else ''
  rows.append({'race_date':date,'course':course,'race_number':str(race),'horse_number':number,
    'horse_name':cand['name'],'surface':'','distance':'','carried_weight':weight,
    'jockey':'','trainer':'','track_condition':'','win_odds':'','place_odds':'','odds_timestamp':'','verified':'NO'})
 return pd.DataFrame(rows,columns=keys)

def analyze_pdf(pdf_path,date,course,race,out_dir,strict_filename=True):
 path=Path(pdf_path);out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
 if strict_filename:verify_pdf_identity(path,date,course)
 data=path.read_bytes()
 if not data.startswith(b'%PDF-'):raise IntakeError('PDF形式ではありません')
 doc,spans,width,candidates,preview=_pdf_parse_core(data,race,date,course)
 draft=_create_review_draft(spans,candidates,width,date,course,race)
 draft.to_csv(out/'review_draft.csv',index=False,encoding='utf-8-sig')
 preview['draft_rows']=len(draft)
 preview.update({'source_file':path.name,'sha256':hashlib.sha256(data).hexdigest(), 'race_date':date,'course':course})
 pd.DataFrame(spans).to_csv(out/'pdf_spans.csv',index=False,encoding='utf-8-sig')
 pd.DataFrame(candidates).to_csv(out/'name_candidates.csv',index=False,encoding='utf-8-sig')
 # Crop selected race from source; never write a complete unreviewed racecard CSV.
 pidx=(race-1)//4; x0=((race-1)%4)*width
 page=doc[pidx];rect=fitz.Rect(x0,0,x0+width,page.rect.height)
 pm=page.get_pixmap(matrix=fitz.Matrix(1.5,1.5),clip=rect,alpha=False)
 pm.save(str(out/'race_panel.png'))
 (out/'diagnostics.json').write_text(json.dumps(preview,ensure_ascii=False,indent=2),encoding='utf-8')
 return preview

def check_and_publish(review_csv,date,course,race,output_dir,expected_runners=None):
 """Publish ONLY fully reviewed complete-card CSV with all mandatory fields; no guessed values."""
 f=Path(review_csv);df=pd.read_csv(f,encoding='utf-8-sig',dtype=str,keep_default_na=False)
 required=['race_date','course','race_number','horse_number','horse_name','surface','distance','carried_weight','jockey','trainer','verified']
 missing=[c for c in required if c not in df.columns]
 if missing:raise IntakeError('レビューCSV不足列: '+','.join(missing))
 if len(df)<5 or len(df)>18:raise IntakeError('出走頭数が学習対象外です（5〜18頭）')
 if expected_runners is None:raise IntakeError('PDF原本の出走頭数が指定されていません。原本を見て頭数を確認してください')
 if len(df)!=int(expected_runners):raise IntakeError(f'原本出走頭数 {expected_runners} と確認CSV {len(df)} が一致しません')
 if any((df[c].astype(str).str.strip()=='').any() for c in required):raise IntakeError('必須列に未入力があります')
 if not df['verified'].str.upper().eq('YES').all():raise IntakeError('未確認の馬がいます。すべてYESのときだけ登録します')
 if not df['race_date'].eq(date).all() or not df['course'].eq(course).all() or not df['race_number'].str.replace('R','',regex=False).eq(str(race)).all():
  raise IntakeError('指定レースとの不一致')
 nums=pd.to_numeric(df.horse_number,errors='coerce')
 if nums.isna().any() or nums.duplicated().any() or not nums.between(1,18).all():raise IntakeError('馬番が不正・重複')
 if df.horse_name.duplicated().any():raise IntakeError('馬名重複')
 w=pd.to_numeric(df.carried_weight,errors='coerce');ds=pd.to_numeric(df.distance,errors='coerce')
 if w.isna().any() or not w.between(45,65).all() or ds.isna().any() or not ds.between(800,4000).all():raise IntakeError('斤量または距離が不正')
 if not df.surface.isin(['芝','ダート','障害']).all() or df.surface.eq('障害').any():raise IntakeError('障害競走は対象外です')
 if any(df[c].nunique()!=1 for c in ['surface','distance']):raise IntakeError('同一レース内で距離・種別が不一致')
 if any(df[c].str.contains(r'[\x00-\x1f\x7f]',regex=True).any() for c in ['horse_name','jockey','trainer']):raise IntakeError('制御文字を検出')
 # No odds invented: preserve only actual source-recorded odds.
 for name in ['win_odds','place_odds','odds_timestamp','track_condition']:
  if name not in df:df[name]=''
 target_dir=Path(output_dir);target_dir.mkdir(parents=True,exist_ok=True)
 dest=target_dir/f'jra_pdf_{date.replace("-", "")}_{VENUE_EN[course]}_{race:02d}.csv'
 # Atomic replace: write temp and then replace, never empty existing CSV on failed validation.
 with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8-sig',suffix='.csv',dir=target_dir,delete=False,newline='') as t:
  tmp=Path(t.name);df.drop(columns=['verified']).to_csv(t,index=False)
 tmp.replace(dest)
 return {'file':str(dest),'runners':len(df)}

def export_review_template(path,date,course,race,n=0):
 cols=['race_date','course','race_number','horse_number','horse_name','surface','distance','carried_weight','jockey','trainer','track_condition','win_odds','place_odds','odds_timestamp','verified']
 df=pd.DataFrame([{c:'' for c in cols} for _ in range(n)],columns=cols)
 if n:
  df['race_date']=date;df['course']=course;df['race_number']=str(race);df['verified']='NO'
 Path(path).parent.mkdir(parents=True,exist_ok=True)
 df.to_csv(path,index=False,encoding='utf-8-sig')
 return str(path)

def main():
 p=argparse.ArgumentParser(description='JRA official PDF single-race research intake')
 p.add_argument('--date',required=True);p.add_argument('--course',choices=list(VENUE_EN),required=True);p.add_argument('--race',type=int,required=True)
 p.add_argument('--pdf',help='JRA PDF saved in browser');p.add_argument('--discover',action='store_true');p.add_argument('--fetch',action='store_true');p.add_argument('--confirm-permission',action='store_true')
 p.add_argument('--out',default='output/v31');p.add_argument('--publish-review');p.add_argument('--expected-runners',type=int);p.add_argument('--racecards',default='input/racecards')
 a=p.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 try:
  if not 1<=a.race<=12:raise IntakeError('レースは1-12')
  if a.publish_review:
   print(json.dumps(check_and_publish(a.publish_review,a.date,a.course,a.race,a.racecards,a.expected_runners),ensure_ascii=False,indent=2));return
  pdf=a.pdf
  if a.discover or a.fetch:
   html=_read_url(INDEX_URL,'index',2_000_000)
   options=discover_rpdf(html,a.date,a.course)
   print(json.dumps(options,ensure_ascii=False,indent=2))
   if not a.fetch:return
   if not a.confirm_permission:raise IntakeError('単発PDF取得の利用条件を確認し、--confirm-permission を指定してください')
   if len(options)!=1:raise IntakeError('対象PDFは1件に確定できません。JRA公式ページで手動保存してください')
   pdf_url=options[0]['url'];raw=_read_url(pdf_url,'pdf');folder=Path('input/jra_pdf_racecards');folder.mkdir(parents=True,exist_ok=True)
   fp=folder/options[0]['filename'];fp.write_bytes(raw);pdf=str(fp)
  if not pdf:raise IntakeError('--pdf または --discover/--fetch を指定してください')
  result=analyze_pdf(pdf,a.date,a.course,a.race,out)
  print(json.dumps(result,ensure_ascii=False,indent=2))
  print('REVIEW ONLY: race_panel.png と pdf_spans.csv を確認してください。出走表CSVは自動確定していません。')
 except (IntakeError,FileNotFoundError) as exc:
  print(f'INTAKE STOPPED: {exc}',file=sys.stderr);sys.exit(2)
if __name__=='__main__':main()
