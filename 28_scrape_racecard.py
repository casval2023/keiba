# -*- coding: utf-8 -*-
"""v2.8: Parse a locally saved Japanese racecard HTML, optionally fetch a permitted URL.

Does NOT bypass access controls or fetch hidden odds APIs. Odds timestamp stays blank.
Validates the complete card using v2.7's strict sanitize and atomic store.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
import requests

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location('fetch_v27',HERE/'27_racecard_fetch.py')
fetch=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch)

AGENT='KeibaPersonalResearch/2.8 (one-race, user-requested; respects robots.txt)'
VENUES=fetch.VENUES

def clean(text):return re.sub(r'\s+',' ',str(text or '')).strip()

def class_matches(el,word):
 return bool(el and any(word.lower() in c.lower() for c in (el.get('class') or [])))

def td_match(tr,*fragments):
 for td in tr.find_all('td',recursive=False):
  if any(class_matches(td,f) for f in fragments):return td
 return None

def links(tr,frag):
 return tr.select('a[href*="'+frag+'"]')

def cell_text(tr,*frags):
 el=td_match(tr,*frags)
 return clean(el.get_text(' ',strip=True)) if el else ''

def numerical(text,low,high,integer=False):
 text=clean(text).replace(',','')
 if integer:
  m=re.search(r'(?<!\d)(\d{1,4})(?!\d)',text)
 else:
  m=re.search(r'(?<!\d)(\d{1,3}(?:\.\d+)?)(?!\d)',text)
 if not m:return ''
 v=float(m.group(1))
 if not low<=v<=high:return ''
 return str(int(v)) if integer else str(v)

def header_fields(soup):
 # RaceData01 usually holds '芝2000m'; avoid guessing if not present.
 candidates=[]
 for sel in ('.RaceData01','.RaceData02','.RaceName','.RaceList_NameBox'):
  candidates.extend(e.get_text(' ',strip=True) for e in soup.select(sel)[:3])
 h=' '.join(candidates)
 m=re.search(r'(芝|ダート|ダ)[^0-9]{0,8}(\d{3,4})\s*m',h,re.I)
 if not m:
  m=re.search(r'(芝|ダート|ダ)\s*(\d{3,4})',h)
 if not m:raise ValueError('Surface/distance missing from race header: no made-up distance')
 return ('芝' if m.group(1)=='芝' else 'ダート'),int(m.group(2))

def candidate_races(soup):
 for t in soup.select('table.RaceTable01, table.Shutuba_Table, table[class*="RaceTable"]'):
  rows=[r for r in t.find_all('tr') if links(r,'/horse/')]
  if len(rows)>=5:return rows
 # Page can contain non-race tables; require >=5 horse detail links.
 rows=[r for r in soup.select('tr.HorseList') if links(r,'/horse/')]
 if len(rows)>=5:return rows
 raise ValueError('No complete runner table (horse links absent, JS/login/markup changed?)')

def infer_number(tr):
 for td in tr.find_all('td',recursive=False):
  if class_matches(td,'Umaban') or class_matches(td,'HorseNum'):
   s=numerical(td.get_text(' ',strip=True),1,18,True)
   if s:return s
 raise ValueError('Missing horse number; does not infer from row order')

def parse_html(raw,date,course,race,source):
 if not raw:raise ValueError('Empty HTML')
 soup=BeautifulSoup(raw,'html.parser')
 title=clean(soup.title.get_text(' ',strip=True)) if soup.title else ''
 if any(s in title for s in ('ログインしてください','アクセス制限','Access Denied')):
  raise ValueError('Restricted or login HTML: not a race card')
 if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date):raise ValueError('Invalid date format')
 # For known URLs/title, avoid accepting a different race as valid.
 source_id=re.search(r'race_id=(\d{12})',source)
 if source_id and int(source_id.group(1)[-2:])!=int(race):raise ValueError('URL race ID and requested race number differ')
 mdate=re.search(r'(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日',title)
 if mdate and f'{int(mdate.group(1)):04d}-{int(mdate.group(2)):02d}-{int(mdate.group(3)):02d}'!=date:
  raise ValueError('Requested date does not match HTML title date')
 mr=re.search(r'(?:^|\s|[・|])(?:'+ '|'.join(VENUES) +r')(\d{1,2})R',title)
 if mr and int(mr.group(1))!=int(race):raise ValueError('HTML title race number does not match')
 if course not in title and re.search(r'(?:東京|京都|中山|阪神|中京|新潟|小倉|福島|札幌|函館)\s*\d{1,2}R',title):
  raise ValueError('HTML title venue differs from requested venue')
 surface,distance=header_fields(soup)
 rows=candidate_races(soup)
 result=[]
 for tr in rows:
  horse_links=links(tr,'/horse/')
  if not horse_links:continue
  name=clean(horse_links[0].get_text(' ',strip=True))
  if not name:raise ValueError('Horse name absent')
  horse_num=infer_number(tr)
  weight=cell_text(tr,'Kinryo','Weight','Futan')
  w=numerical(weight,40,70)
  if not w:raise ValueError(f'Horse {horse_num} has no valid carried weight')
  jlinks=links(tr,'/jockey/')
  tlinks=links(tr,'/trainer/')
  jockey=clean(jlinks[0].get_text(' ',strip=True)) if jlinks else cell_text(tr,'Jockey')
  trainer=clean(tlinks[0].get_text(' ',strip=True)) if tlinks else cell_text(tr,'Trainer','Chokyoshi')
  odds_td=td_match(tr,'Odds','Tansho')
  odds=''
  if odds_td:
   odds=numerical(odds_td.get_text(' ',strip=True),1.01,999.9)
  status=cell_text(tr,'Result','Status')
  full=clean(tr.get_text(' ',strip=True))
  if '出走取消' in full or '競走除外' in full or '取消'==status:status='取消'
  result.append({'race_date':date,'course':course,'race_number':str(race),
   'horse_number':horse_num,'horse_name':name,'surface':surface,'distance':str(distance),
   'carried_weight':w,'jockey':jockey,'trainer':trainer,'track_condition':'',
   'win_odds':odds,'place_odds':'','odds_timestamp':'','runner_status':status})
 if not result:raise ValueError('No runners parsed')
 return result,{'source_title':title,'surface':surface,'distance':distance,
   'runner_rows':len(result),'odds_rows_without_proven_timestamp':sum(bool(x['win_odds']) for x in result),
   'note':'Odds are unverified as-of time; NOT real-time odds. No HTML odds timestamp is inferred.'}

def download(url,consent):
 if not consent:raise PermissionError('Online fetch requires --confirm-permission after checking site terms')
 # Use the OS trust store (Windows CryptoAPI) while retaining certificate verification.
 # Import and inject only for the network request; local HTML parsing needs no truststore.
 try:
  import truststore
 except ImportError as exc:
  raise RuntimeError('HTTPS証明書検証用 truststore が必要です。PowerShellで python -m pip install truststore を実行してください') from exc
 truststore.inject_into_ssl()
 p=urlparse(url)
 if p.scheme!='https' or not p.hostname:raise ValueError('HTTPS URL required')
 if p.username or p.password or p.fragment:raise ValueError('Disallowed URL')
 # Limit v2.8 to an explicitly requested ordinary page; no hidden APIs, login or paid data.
 if p.hostname not in {'race.netkeiba.com','www.jra.go.jp','jra.go.jp'}:raise ValueError('Only listed public racecard domains supported')
 robots=RobotFileParser();robots.set_url(f'https://{p.hostname}/robots.txt')
 try:robots.read()
 except Exception as exc:raise RuntimeError(f'robots.txt not verifiable: {exc}')
 if not robots.mtime() or not robots.can_fetch(AGENT,url):raise PermissionError('robots.txt prohibits this request or could not verify permission')
 resp=requests.get(url,headers={'User-Agent':AGENT,'Accept':'text/html'},timeout=15,allow_redirects=False)
 if resp.status_code in (401,403,429):raise PermissionError(f'Access restricted HTTP {resp.status_code}: do not retry automatically')
 resp.raise_for_status()
 if not resp.headers.get('content-type','').lower().startswith('text/html'):
  raise ValueError('Response is not HTML')
 if len(resp.content)>3000000:raise ValueError('HTML too large')
 return resp.content

def run(args):
 if args.html:
  p=Path(args.html)
  if not p.is_file():raise FileNotFoundError(p)
  raw=p.read_bytes();source=args.source_url or str(p.resolve())
 else:
  if not args.url:raise ValueError('Supply --html or --url')
  raw=download(args.url,args.confirm_permission);source=args.url
 rows,meta=parse_html(raw,args.date,args.course,args.race,source)
 now=datetime.now(timezone.utc)
 normalized=fetch.sanitize(rows,args.date,args.course,args.race,'html_racecard_unverified',now)
 if args.dry_run:
  result={'status':'DRY_RUN_NO_FILES','runners':len(normalized)}
 else:
  result=fetch.store(args.out,args.date,args.course,args.race,normalized,raw,source,now)
 result['quality']='PARSER_VALIDATED_NOT_SOURCE_VERIFIED'
 result.update(meta)
 if args.report:
  dest=Path(args.report);dest.parent.mkdir(parents=True,exist_ok=True)
  dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 return result

if __name__=='__main__':
 ap=argparse.ArgumentParser()
 g=ap.add_mutually_exclusive_group(required=True)
 g.add_argument('--html',help='Locally saved original racecard HTML, no network access')
 g.add_argument('--url',help='Exact racecard URL; optional live test only when permitted')
 ap.add_argument('--date',required=True);ap.add_argument('--course',required=True,choices=sorted(VENUES))
 ap.add_argument('--race',required=True,type=int,choices=range(1,13))
 ap.add_argument('--source-url',default='');ap.add_argument('--out',default='input/racecards')
 ap.add_argument('--report',default='output/v28/scrape_report.json')
 ap.add_argument('--confirm-permission',action='store_true');ap.add_argument('--dry-run',action='store_true')
 a=ap.parse_args()
 try:print(json.dumps(run(a),ensure_ascii=False,indent=2))
 except Exception as exc:
  print(f'ERROR (existing CSV preserved): {type(exc).__name__}: {exc}',file=sys.stderr)
  sys.exit(2)
