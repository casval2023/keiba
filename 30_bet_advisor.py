# -*- coding: utf-8 -*-
"""Ver.3.0: transparent, conservative win/place betting research aid.
Not a bookmaker, not automated betting, and never treats unverified odds as live.
"""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
import math
import pandas as pd
import numpy as np

JST = ZoneInfo('Asia/Tokyo')


def _ts(value):
    if value is None or str(value).strip() in ('', 'nan', 'NaT', 'None'):
        return None
    try:
        t = pd.Timestamp(value)
        if pd.isna(t):
            return None
        if t.tzinfo is None:
            t = t.tz_localize('Asia/Tokyo', ambiguous='NaT', nonexistent='NaT')
        return t.tz_convert('Asia/Tokyo') if not pd.isna(t) else None
    except (ValueError, TypeError):
        return None


def evaluate(predictions: pd.DataFrame, *, now=None, min_ev=0.10, max_age_minutes=30,
             budget_yen=1000, stake_yen=100, require_champion=True,
             require_history=True, prob_sums_check=True):
    """Return (all_markets, recommendations, summary). Strict market gating.

    Odds are assumed decimal payout INCLUDING the principal, for a 100-yen stake.
    Place odds (when supplied) must be the conservative LOWER bound, not the upper.
    Only singles are recommended; multiple bets may all lose.  No purchase action.
    """
    if not 0 <= min_ev <= 100: raise ValueError('min_ev must be 0..100')
    if stake_yen < 100 or stake_yen % 100: raise ValueError('stake_yen must be a 100-yen multiple')
    if budget_yen < 0 or budget_yen % 100: raise ValueError('budget_yen must be a 100-yen multiple')
    if max_age_minutes <= 0: raise ValueError('max_age_minutes must be positive')
    now = _ts(now) if now is not None else pd.Timestamp.now(tz='Asia/Tokyo')
    if now is None: raise ValueError('Invalid evaluation timestamp')
    needed = ['horse_number','horse_name','p_win','p_place','win_odds','place_odds',
              'odds_timestamp','model_win_status','model_place_status','history_coverage_warning']
    missing = [x for x in needed if x not in predictions.columns]
    if missing: raise ValueError(f'Missing prediction fields: {missing}')
    if predictions.empty: return pd.DataFrame(),pd.DataFrame(),{'candidates':0,'eligible':0,'selected':0,'budget_yen':budget_yen}
    if predictions.horse_number.duplicated().any():raise ValueError('Duplicated horse numbers in one race')
    pwin = pd.to_numeric(predictions.p_win,errors='coerce')
    pplace = pd.to_numeric(predictions.p_place,errors='coerce')
    n = len(predictions)
    # Intentionally conservative probability integrity flags; these are not automatic normalization.
    win_sum=float(pwin.sum())
    place_sum=float(pplace.sum())
    # Actual place slots can be 2 or 3 ordinarily; one slot short in unusually tiny fields.
    typical_places = 2 if n <= 7 else 3
    inconsistent = not (0.8 <= win_sum <= 1.2 and (typical_places*.8) <= place_sum <= (typical_places*1.2))
    rows=[]
    for _,r in predictions.iterrows():
        for market,prob_col,odds_col,status_col in [('単勝','p_win','win_odds','model_win_status'),('複勝','p_place','place_odds','model_place_status')]:
            reasons=[]
            try:prob=float(r[prob_col])
            except (ValueError,TypeError):prob=float('nan')
            try:odds=float(r[odds_col])
            except (ValueError,TypeError):odds=float('nan')
            if not math.isfinite(prob) or not 0<=prob<=1:reasons.append('予測確率が無効')
            if not math.isfinite(odds) or odds<=1:reasons.append('オッズ未取得・無効')
            ts=_ts(r['odds_timestamp'])
            age_minutes=float('nan')
            if ts is None:reasons.append('オッズ時刻が未確認')
            else:
                age_minutes=(now-ts).total_seconds()/60
                if age_minutes < -1: reasons.append('未来時刻のオッズ')
                if age_minutes > max_age_minutes:reasons.append('オッズが古い')
            if require_champion and str(r[status_col])!='champion':reasons.append('モデル未承認')
            if require_history and bool(r['history_coverage_warning']):reasons.append('過去走情報なし')
            if prob_sums_check and inconsistent:reasons.append('レース確率合計に不整合')
            ev=prob*odds-1 if math.isfinite(prob) and math.isfinite(odds) and odds>1 else np.nan
            if pd.notna(ev) and ev<min_ev: reasons.append('期待値が購入基準未満')
            rows.append({'horse_number':int(r.horse_number),'horse_name':str(r.horse_name),
                         'market':market,'probability':prob,'odds':odds,
                         'expected_roi':ev,'expected_profit_per_100':(100*ev if pd.notna(ev) else np.nan),
                         'odds_timestamp':str(ts) if ts is not None else '',
                         'odds_age_minutes':age_minutes,
                         'eligible':len(reasons)==0,'reason':'; '.join(reasons)})
    all_bets=pd.DataFrame(rows).sort_values(['eligible','expected_roi'],ascending=[False,False],na_position='last').reset_index(drop=True)
    slots=min(int(budget_yen//stake_yen),len(all_bets))
    selected=all_bets[all_bets.eligible].head(slots).copy()
    selected['stake_yen']=int(stake_yen)
    selected['estimated_profit_if_win']=((selected.odds-1)*stake_yen).round(0)
    selected['estimated_loss_if_lose']=-stake_yen
    summary={'candidates':int(len(all_bets)), 'eligible':int(all_bets.eligible.sum()),
             'selected':int(len(selected)), 'budget_yen':int(budget_yen),
             'planned_stake_yen':int(len(selected)*stake_yen),
             'unused_budget_yen':int(budget_yen-len(selected)*stake_yen),
             'win_probability_sum':win_sum,'place_probability_sum':place_sum,
             'probability_integrity_warning':bool(inconsistent),
             'as_of':now.isoformat(), 'note':'確率モデル・オッズ情報の品質に依存。利益を保証しません。'}
    return all_bets,selected,summary
