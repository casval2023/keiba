# -*- coding: utf-8 -*-
"""Ver 2.7 racecard source adapter. Provider must be configured and permitted.
Source: authorized HTTPS CSV/JSON or a local directory auto-populated by an external licensed provider.
No JRA scraping. Never fabricates odds / timestamps / horses.
"""
from __future__ import annotations
import argparse, csv, hashlib, io, json, os, re, sys, tempfile, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

REQUIRED=['race_date','course','race_number','horse_number','horse_name','surface','distance','carried_weight']
OPTIONAL=['jockey','trainer','track_condition','win_odds','place_odds','odds_timestamp','race_id','race_start','runner_status']
ALIASES={
'race_date':['date','日付','開催日'],'course':['venue','競馬場','競馬場名'],
'race_number':['race','race_no','R','レース番号'],'horse_number':['horse_no','umaban','馬番'],
'horse_name':['horse','bamei','馬名'],'surface':['芝ダート','馬場種別'],
'distance':['distance_m','距離','距離(m)'],'carried_weight':['weight','斤量','負担重量'],
'jockey':['騎手'],'trainer':['調教師'],'track_condition':['馬場状態'],
'win_odds':['単勝オッズ'],'place_odds':['複勝オッズ'],
'odds_timestamp':['オッズ取得時刻'],'runner_status':['status','出走状態']}
VENUES={'札幌','函館','福島','新潟','東京','中山','中京','京都','阪神','小倉'}

def slug(d,c,r):return f'{d}_{c}_{int(r):02d}R'

def decode(b):
 for encoding in ('utf-8-sig','cp932'):
  try:return b.decode(encoding)
  except UnicodeDecodeError:pass
 raise ValueError('Input encoding unsupported (utf-8 / cp932 required)')

def parse_payload(raw,fmt):
 if fmt=='csv':return list(csv.DictReader(io.StringIO(decode(raw))))
 obj=json.loads(decode(raw))
 if isinstance(obj,dict):
  for key in ('runners','entries','rows','data'):
   if isinstance(obj.get(key),list):return obj[key]
  raise ValueError('JSON requires top-level array or runners/entries/rows/data array')
 if isinstance(obj,list):return obj
 raise ValueError('Invalid JSON structure')

def num(value,integer=False):
 try:
  v=float(str(value).strip())
  if not (v==v and abs(v)!=float('inf')):raise ValueError()
  if integer and (v!=int(v)):raise ValueError()
  return int(v) if integer else v
 except Exception:raise ValueError(f'Not a valid numeric value: {value}')

def field(row,key):
 for name in [key]+ALIASES.get(key,[]):
  if name in row and str(row[name]).strip():return str(row[name]).strip()
 return ''

def sanitize(rows,d,c,r,source, fetched_utc):
 if not isinstance(rows,list) or not rows:raise ValueError('Source returned no runners')
 output=[];seen=set();errors=[]
 for idx,row in enumerate(rows,1):
  if not isinstance(row,dict):raise ValueError(f'row {idx}: not an object')
  row={str(k).strip():v for k,v in row.items()}
  x={k:field(row,k) for k in REQUIRED+OPTIONAL}
  # Provider can omit race-identifying fields only when exactly one race is requested.
  x['race_date']=x['race_date'] or d;x['course']=x['course'] or c;x['race_number']=x['race_number'] or str(r)
  if x['race_date']!=d or x['course']!=c or num(x['race_number'],True)!=int(r):
   raise ValueError(f'row {idx}: wrong race identity; refusing mixed race payload')
  if x['course'] not in VENUES:raise ValueError(f'row {idx}: unsupported venue')
  h=num(x['horse_number'],True)
  if not (1<=h<=18):raise ValueError(f'row {idx}: horse_number outside 1..18')
  if h in seen:raise ValueError(f'Duplicate horse_number: {h}')
  seen.add(h)
  if not x['horse_name'] or any(ord(ch)<32 for ch in x['horse_name']):raise ValueError(f'row {idx}: missing or malformed horse name')
  if x['surface'] not in ('芝','ダート'):raise ValueError(f'row {idx}: unsupported surface {x["surface"]}')
  dist=num(x['distance'],True)
  if not (800<=dist<=4000):raise ValueError(f'row {idx}: invalid distance')
  weight=num(x['carried_weight'])
  if not (40<=weight<=70):raise ValueError(f'row {idx}: abnormal weight')
  x['horse_number']=str(h);x['race_number']=str(int(r));x['distance']=str(dist);x['carried_weight']=str(weight)
  for odds in ('win_odds','place_odds'):
   if x[odds]:
    z=num(x[odds]);
    if z<=1:raise ValueError(f'row {idx}: {odds} must exceed 1')
    x[odds]=str(z)
  # No guessed odds observation time; a download time is NOT an odds timestamp.
  if x['odds_timestamp']:
   try:
    ts=datetime.fromisoformat(x['odds_timestamp'].replace('Z','+00:00'))
    if ts.tzinfo is None:raise ValueError()
    if ts.astimezone(timezone.utc)>fetched_utc.replace(microsecond=0):raise ValueError()
   except Exception:raise ValueError(f'row {idx}: odds_timestamp must be timezone-aware ISO8601 and not in the future')
  x['source_provider']=source;x['fetched_at_utc']=fetched_utc.isoformat()
  output.append(x)
 if len(output)<5:raise ValueError('Less than 5 runners: incomplete/unsupported card')
 if len({(x['surface'],x['distance']) for x in output})!=1:raise ValueError('Inconsistent race surface/distance')
 # No fabricated runner state; only explicit scratch/non-runner statuses are blocked.
 statuses={x['runner_status'].lower() for x in output}
 if any(s in statuses for s in ('取消','除外','中止','scratched','withdrawn')):
  raise ValueError('Explicit scratch/withdrawal found; please provide a confirmed active-runner feed')
 return sorted(output,key=lambda x:int(x['horse_number']))

def load_config(path):
 p=Path(path)
 if not p.is_file():raise FileNotFoundError(f'Provider not configured: {p}')
 conf=json.loads(p.read_text(encoding='utf-8'))
 if conf.get('provider_type') not in ('https_template','local_export'):
  raise ValueError('provider_type must be https_template or local_export')
 if conf.get('authorized') is not True:raise ValueError('Set authorized=true only after verifying source permission')
 if conf.get('format') not in ('csv','json'):raise ValueError('format must be csv or json')
 return conf

def acquire(conf,d,c,r):
 mapping={'date':d,'date_compact':d.replace('-',''),'course':c,'race':str(int(r)),'race2':f'{int(r):02d}'}
 ext=conf['format']
 if conf['provider_type']=='local_export':
  directory=Path(conf['directory']).expanduser()
  name=conf.get('filename_template','{date}_{course}_{race2}R.'+ext).format_map(mapping)
  path=(directory/name).resolve()
  if directory.resolve() not in path.parents:raise ValueError('Invalid filename path')
  if not path.is_file():raise FileNotFoundError(f'No authorized export yet: {path}')
  return path.read_bytes(),str(path)
 url=conf.get('url_template','').format_map({k:urllib.parse.quote(v,safe='') for k,v in mapping.items()})
 parsed=urllib.parse.urlparse(url)
 if parsed.scheme!='https' or not parsed.hostname:raise ValueError('HTTPS source required')
 if conf.get('allowed_hosts') and parsed.hostname not in conf['allowed_hosts']:raise ValueError('Host not on allowlist')
 if parsed.username or parsed.password or parsed.fragment:raise ValueError('Invalid provider URL')
 req=urllib.request.Request(url,headers={'User-Agent':'KeibaMVP/2.7 (authorized data consumer)','Accept':'text/csv,application/json'})
 with urllib.request.urlopen(req,timeout=int(conf.get('timeout_seconds',15))) as response:
  if urllib.parse.urlparse(response.url).hostname != parsed.hostname:raise ValueError('Provider redirected to different host')
  raw=response.read(int(conf.get('max_bytes',2000000))+1)
 if len(raw)>int(conf.get('max_bytes',2000000)):raise ValueError('Payload too large')
 return raw,url

def store(outdir,d,c,r,normalized,raw,source,now):
 outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=True)
 key=slug(d,c,r);dest=outdir/f'{key}.csv';log=outdir/'fetch_history.jsonl'
 payload_sha=hashlib.sha256(raw).hexdigest()
 if dest.is_file() and log.is_file():
  for line in reversed(log.read_text(encoding='utf-8').splitlines()):
   try: prev=json.loads(line)
   except (json.JSONDecodeError,TypeError):continue
   if prev.get('race')==key:
    if prev.get('sha256_payload')==payload_sha and hashlib.sha256(dest.read_bytes()).hexdigest()==prev.get('sha256_csv'):
     return dict(prev, status='UNCHANGED')
    break
 cols=REQUIRED+OPTIONAL+['source_provider','fetched_at_utc']
 buffer=io.StringIO();writer=csv.DictWriter(buffer,fieldnames=cols);writer.writeheader();writer.writerows(normalized)
 content=('\ufeff'+buffer.getvalue()).encode('utf-8');digest=hashlib.sha256(content).hexdigest()
 fd,tmp=tempfile.mkstemp(dir=outdir,prefix='.racecard_',suffix='.tmp')
 try:
  with os.fdopen(fd,'wb') as handle:handle.write(content)
  os.replace(tmp,dest)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 record={'race':key,'source':source,'fetched_at_utc':now.isoformat(),'runners':len(normalized),
 'sha256_csv':digest,'sha256_payload':hashlib.sha256(raw).hexdigest(),
 'odds_count':sum(bool(x['win_odds']) for x in normalized),
 'odds_with_timestamp':sum(bool(x['win_odds']) and bool(x['odds_timestamp']) for x in normalized),
 'status':'FETCHED_NOT_PREDICTED','output':str(dest)}
 with log.open('a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
 return record

def run(config,date,course,race,outdir):
 try:datetime.strptime(date,'%Y-%m-%d')
 except ValueError:raise ValueError('date must be YYYY-MM-DD')
 if course not in VENUES or not 1<=int(race)<=12:raise ValueError('Invalid course or race number')
 conf=load_config(config)
 raw,source=acquire(conf,date,course,race)
 now=datetime.now(timezone.utc)
 rows=sanitize(parse_payload(raw,conf['format']),date,course,race,conf.get('provider_name',conf['provider_type']),now)
 return store(outdir,date,course,race,rows,raw,source,now)

if __name__=='__main__':
 p=argparse.ArgumentParser(description='Authorized JRA racecard source auto-fetch; CSV output for v26 UI')
 p.add_argument('--config',default='racecard_provider.json');p.add_argument('--date',required=True)
 p.add_argument('--course',required=True);p.add_argument('--race',type=int,required=True)
 p.add_argument('--out',default='input/racecards');args=p.parse_args()
 try:
  result=run(args.config,args.date,args.course,args.race,args.out)
  print(json.dumps(result,ensure_ascii=False,indent=2))
 except Exception as exc:
  print(f'FETCH FAILED, NO REPLACEMENT: {type(exc).__name__}: {exc}',file=sys.stderr);sys.exit(2)
