# -*- coding: utf-8 -*-
"""JRA MVP: pre-race feature construction, saved-model inference, EV calculation.
No online scraping; racecards are local CSV. Source databases are read-only.
"""
from __future__ import annotations
import hashlib, json, sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb

BASE_FEATURES = ['course','surface','distance','horse_number','carried_weight','runners','past_races',
 'prev_finish','prev_distance','prev_last3f','prev_surface','prev_carried_weight',
 'avg_finish_3','avg_finish_5','avg_last3f_3','days_since_last','distance_change',
 'carried_weight_change','prev_win']
CATS=['course','surface','prev_surface']
ENRICHED=['jockey','trainer','track_condition','jockey_prior_starts','jockey_prior_wins',
          'jockey_prior_win_rate','trainer_prior_starts','trainer_prior_wins','trainer_prior_win_rate']
CARD_COLUMNS=['race_date','course','race_number','horse_number','horse_name','surface',
              'distance','carried_weight']
ALIAS={
 'race_date':['race_date','日付','開催日'], 'course':['course','競馬場','競馬場名'],
 'race_number':['race_number','R','レース番号'], 'horse_number':['horse_number','horse_no','馬番'],
 'horse_name':['horse_name','馬名'], 'surface':['surface','芝ダート','馬場種別'],
 'distance':['distance','距離','距離(m)','distance_m'], 'carried_weight':['carried_weight','斤量','負担重量'],
 'jockey':['jockey','騎手'], 'trainer':['trainer','調教師'],
 'track_condition':['track_condition','馬場状態'], 'win_odds':['win_odds','単勝オッズ'],
 'place_odds':['place_odds','複勝オッズ'], 'odds_timestamp':['odds_timestamp','オッズ取得時刻'],
 'race_id':['race_id','レースID']}

def _read_csv(path):
 try:return pd.read_csv(path,encoding='utf-8-sig',dtype=str,keep_default_na=False)
 except UnicodeDecodeError:return pd.read_csv(path,encoding='cp932',dtype=str,keep_default_na=False)

def load_cards(folder):
 folder=Path(folder);files=sorted(folder.glob('*.csv')) if folder.is_dir() else []
 frames=[];errors=[]
 for file in files:
  try:
   raw=_read_csv(file); raw.columns=[str(c).strip() for c in raw.columns]
   match={key:next((c for c in names if c in raw.columns),None) for key,names in ALIAS.items()}
   missing=[c for c in CARD_COLUMNS if match[c] is None]
   if missing: raise ValueError('required columns missing: '+','.join(missing))
   x=pd.DataFrame({c:raw[m].str.strip() if m else '' for c,m in match.items()})
   x['source_file']=file.name
   frames.append(x)
  except Exception as e:errors.append(f'{file.name}: {e}')
 if not frames:return pd.DataFrame(columns=list(ALIAS)+['source_file']),errors
 out=pd.concat(frames,ignore_index=True)
 for c in ['distance','horse_number','carried_weight','race_number','win_odds','place_odds']:
  out[c]=pd.to_numeric(out[c].str.replace('R','',regex=False),errors='coerce')
 out['race_date']=pd.to_datetime(out.race_date,errors='coerce').dt.strftime('%Y-%m-%d')
 if out[CARD_COLUMNS].isna().any().any():errors.append('Some rows have missing required values; such races are excluded')
 out=out.dropna(subset=CARD_COLUMNS)
 out=out[(out.horse_number>=1)&(out.horse_number<=18)&(out.distance>=800)&(out.distance<=4000)]
 out['race_number']=out.race_number.astype(int);out['horse_number']=out.horse_number.astype(int)
 out['race_key']=out.race_date+'_'+out.course+'_'+out.race_number.astype(str)
 # Block conflicting duplicates; no arbitrary first-row selection.
 counts=out.groupby(['race_key','horse_number']).size()
 bad_keys=set(k for k,n in counts.items() if n>1)
 if bad_keys:
  errors.append(f'Duplicate race/horse-number keys: {len(bad_keys)}; exclude affected races')
  bad_races={r for r,_ in bad_keys}
  out=out[~out.race_key.isin(bad_races)].copy()
 return out,errors

def _readonly_connection(path):
 p=Path(path)
 if not p.is_file():raise FileNotFoundError(f'履歴DBが見つかりません: {p}')
 return sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True)

def historical_rows(master, horse_names, before_date):
 """Only historical rows with race_date < race day; never use target race outcomes."""
 names=sorted(set(str(v) for v in horse_names if str(v)))
 if not names:return pd.DataFrame()
 columns=['horse_name','race_date','race_id','entry_id','finish_num','distance','last3f','surface','carried_weight']
 frames=[]
 with _readonly_connection(master) as con:
  for i in range(0,len(names),400):
   chunk=names[i:i+400]
   sql=f"SELECT {','.join(columns)} FROM race_results WHERE horse_name IN ({','.join('?'*len(chunk))}) AND race_date < ? AND finish_num>=1 ORDER BY horse_name,race_date,race_id,entry_id"
   frames.append(pd.read_sql_query(sql,con,params=chunk+[before_date]))
 return pd.concat(frames,ignore_index=True) if frames else pd.DataFrame(columns=columns)

def build_live_features(card,master):
 """Pre-race features compatible with v13/v25. History uses same-name cohort gap >1095d.
 If horse identity is uncertain, flag; do not claim identity verified.
 """
 if card.empty:return card.copy()
 days=card.race_date.unique()
 if len(days)!=1:raise ValueError('Select one race date at a time')
 date=str(days[0]); hist=historical_rows(master,card.horse_name,date)
 hist['race_date']=pd.to_datetime(hist.race_date)
 for c in ['finish_num','distance','last3f','carried_weight']:
  hist[c]=pd.to_numeric(hist[c],errors='coerce')
 hist=hist.sort_values(['horse_name','race_date','race_id','entry_id'])
 out=card.copy()
 out['runners']=len(card)
 default={'past_races':0,'prev_finish':np.nan,'prev_distance':np.nan,'prev_last3f':np.nan,
          'prev_surface':None,'prev_carried_weight':np.nan,'avg_finish_3':np.nan,
          'avg_finish_5':np.nan,'avg_last3f_3':np.nan,'days_since_last':np.nan,
          'distance_change':np.nan,'carried_weight_change':np.nan,'prev_win':np.nan}
 for c,v in default.items():out[c]=v
 for ix,row in out.iterrows():
  h=hist[hist.horse_name==row.horse_name]
  if h.empty:continue
  gaps=h.race_date.diff().dt.days.fillna(9999)
  last_cohort=h.loc[(gaps>1095).cumsum()==(gaps>1095).cumsum().iloc[-1]]
  # If a horse has not raced for more than 1095 days it is a new cohort in v13.
  latest=last_cohort.iloc[-1]
  if (pd.Timestamp(date)-latest.race_date).days>1095:continue
  recent=last_cohort
  out.at[ix,'past_races']=len(recent)
  out.at[ix,'prev_finish']=latest.finish_num
  out.at[ix,'prev_distance']=latest.distance
  out.at[ix,'prev_last3f']=latest.last3f
  out.at[ix,'prev_surface']=latest.surface
  out.at[ix,'prev_carried_weight']=latest.carried_weight
  out.at[ix,'avg_finish_3']=recent.finish_num.tail(3).mean()
  out.at[ix,'avg_finish_5']=recent.finish_num.tail(5).mean()
  out.at[ix,'avg_last3f_3']=recent.last3f.tail(3).mean()
  out.at[ix,'days_since_last']=(pd.Timestamp(date)-latest.race_date).days
  out.at[ix,'distance_change']=float(row.distance)-latest.distance
  out.at[ix,'carried_weight_change']=float(row.carried_weight)-latest.carried_weight
  out.at[ix,'prev_win']=float(latest.finish_num==1)
 out['history_coverage_warning']= (out.past_races==0)
 return out

def find_model(folder,target):
 """Prefer explicitly deployed champion, otherwise v25 candidate; never silently deploy candidate."""
 folder=Path(folder)
 for candidate in [folder/f'champion_{target}.json',folder/f'candidate_{target}.json']:
  if candidate.is_file():
   meta=json.loads(candidate.read_text(encoding='utf-8'))
   path=Path(meta['file'])
   if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==meta.get('sha256'):
    return path,('champion' if candidate.name.startswith('champion_') else 'candidate_NOT_PROMOTED')
 # v13 fallbacks can be supplied via model directory, distinct status.
 for candidate in [folder/f'model_{target}_2017.txt',folder/f'candidate_{target}_responsive.txt']:
  if candidate.is_file():return candidate,'fallback'
 raise FileNotFoundError(f'No usable {target} model in {folder}')

def predict(card_features,models_dir):
 df=card_features.copy()
 for target in ['win','place']:
  path,status=find_model(models_dir,target)
  booster=lgb.Booster(model_file=str(path))
  features=booster.feature_name()
  missing=[x for x in features if x not in df.columns]
  if missing:raise ValueError(f'Model expects missing features {missing}; train the enriched model or use base model')
  x=df[features].copy()
  cats=booster.pandas_categorical or []
  categorical_features=[c for c in features if c in CATS+['jockey','trainer','track_condition']]
  if len(cats)!=len(categorical_features):
   raise ValueError(f'Category schema mismatch: model expects {len(cats)}, detected {len(categorical_features)}')
  for col,category_set in zip(categorical_features,cats):
   x[col]=pd.Categorical(x[col],categories=category_set)
  for col in features:
   if col not in categorical_features:x[col]=pd.to_numeric(x[col],errors='coerce')
  df['p_'+target]=booster.predict(x)
  df[f'model_{target}_status']=status
  df[f'model_{target}_name']=path.name
 # Indicative decimal odds, not final payout.
 for k,odds in [('win','win_odds'),('place','place_odds')]:
  df['ev_'+k]=np.where((df[odds]>1)&np.isfinite(df[odds]),df['p_'+k]*df[odds]-1,np.nan)
 df['odds_warning']=np.where(df.odds_timestamp.astype(str).str.strip().eq(''),'オッズ取得時刻不明','')
 return df

def export_race_template(path):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 pd.DataFrame([{'race_date':'2026-11-29','course':'東京','race_number':11,'horse_number':1,'horse_name':'サンプル馬',
  'surface':'芝','distance':2400,'carried_weight':57,'jockey':'','trainer':'','track_condition':'良',
  'win_odds':'','place_odds':'','odds_timestamp':''}]).to_csv(path,index=False,encoding='utf-8-sig')
 return path
