# -*- coding: utf-8 -*-
from importlib.util import spec_from_file_location,module_from_spec
from pathlib import Path
import pandas as pd
p=Path(__file__).with_name('30_bet_advisor.py')
s=spec_from_file_location('a30',p);m=module_from_spec(s);s.loader.exec_module(m)
now='2026-11-26T13:00:00+09:00'
rows=[]
for i in range(1,11):
 rows.append({'horse_number':i,'horse_name':f'馬{i}','p_win':.1,'p_place':.3,
  'win_odds':15 if i==1 else 4, 'place_odds':5 if i==2 else 2,
  'odds_timestamp':'2026-11-26T12:50:00+09:00','model_win_status':'champion',
  'model_place_status':'champion','history_coverage_warning':False})
df=pd.DataFrame(rows)
a,b,stat=m.evaluate(df,now=now,budget_yen=100,stake_yen=100,min_ev=.1)
assert len(b)==1 and b.iloc[0].horse_number in (1,2) and b.iloc[0].expected_roi==.5
assert stat['planned_stake_yen']==100
u=df.copy();u.loc[0,'odds_timestamp']='';u.loc[1,'odds_timestamp']=''
a,b,s=m.evaluate(u,now=now,budget_yen=1000)
assert not a[(a.horse_number==1)&(a.market=='単勝')].iloc[0].eligible
assert not a[(a.horse_number==2)&(a.market=='複勝')].iloc[0].eligible
u=df.copy();u.odds_timestamp='2026-11-26T10:00:00+09:00'
a,b,s=m.evaluate(u,now=now)
assert b.empty and a.reason.str.contains('オッズが古い').all()
u=df.copy();u.model_win_status='candidate_NOT_PROMOTED';u.model_place_status='fallback'
a,b,s=m.evaluate(u,now=now)
assert b.empty and a.reason.str.contains('モデル未承認').all()
u=df.copy();u.loc[0,'history_coverage_warning']=True
a,b,s=m.evaluate(u,now=now)
assert not a[a.horse_number==1].eligible.any()
u=df.copy();u.loc[0,'p_win']=.9
a,b,s=m.evaluate(u,now=now)
assert b.empty and s['probability_integrity_warning']
u=df.copy();u.loc[0,'horse_number']=2
try:m.evaluate(u,now=now)
except ValueError:pass
else:raise AssertionError('duplicate not blocked')
u=df.copy();u.loc[0,'win_odds']=float('nan')
a,b,s=m.evaluate(u,now=now)
assert not a[(a.horse_number==1)&(a.market=='単勝')].iloc[0].eligible
u=df.copy();u.odds_timestamp='2026-11-27T00:00:00+09:00'
a,b,s=m.evaluate(u,now=now)
assert b.empty and a.reason.str.contains('未来時刻').all()
print('PASS: odds filtering, EV, freshness, budget, approval, history, probability consistency, duplicate, missing and future timestamps')
