from importlib.machinery import SourceFileLoader
from pathlib import Path
import tempfile,sqlite3,sys
import pandas as pd
import numpy as np
p=Path(__file__).parent
core=SourceFileLoader('mvp_core',str(p/'26_mvp_core.py')).load_module()

def run():
 with tempfile.TemporaryDirectory() as t:
  t=Path(t);folder=t/'cards';folder.mkdir()
  core.export_race_template(folder/'example.csv')
  cards,errors=core.load_cards(folder)
  assert len(cards)==1 and not errors,(len(cards),errors)
  src=pd.DataFrame([{'entry_id':f'E{i}','race_id':f'R{i}','race_date':d,'horse_name':'サンプル馬',
    'horse_number':1,'finish_num':f,'distance':d2,'last3f':35.1+i,'surface':'芝',
    'carried_weight':57} for i,(d,f,d2) in enumerate([
     ('2025-01-01',3,2200),('2025-07-01',1,2400),('2026-06-01',2,2600)])])
  db=t/'master.sqlite'
  with sqlite3.connect(db) as conn:src.to_sql('race_results',conn,index=False)
  card=cards.copy();card['race_date']='2026-11-29'
  features=core.build_live_features(card,db)
  assert features.past_races.iloc[0]==3 and features.prev_finish.iloc[0]==2
  assert features.days_since_last.iloc[0]==181
  assert features.distance_change.iloc[0]==-200
  # last known 3+ years gap resets history
  card['race_date']='2030-01-01'
  features=core.build_live_features(card,db)
  assert features.past_races.iloc[0]==0
  # duplicate runner keys block whole race
  two=pd.concat([cards,cards]);two.to_csv(folder/'extra.csv',index=False)
  data,errors=core.load_cards(folder)
  assert data.empty and errors
  print('TEST OK: CSV, duplicate blocking, prior-date features, 1095-day cohort')

if __name__=='__main__':run()
