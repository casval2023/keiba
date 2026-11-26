# -*- coding: utf-8 -*-
"""Streamlit JRA MVP. Local CSV ingestion, race selection, prediction, EV and model registry."""
import sys,json
from urllib.parse import urlparse
from pathlib import Path
from importlib.machinery import SourceFileLoader
import numpy as np
import pandas as pd
import streamlit as st

core=SourceFileLoader('mvp_core',str(Path(__file__).with_name('26_mvp_core.py'))).load_module()
fetch=SourceFileLoader('racecard_fetch',str(Path(__file__).with_name('27_racecard_fetch.py'))).load_module()
st.set_page_config(page_title='JRA 競馬予測 MVP',page_icon='🏇',layout='wide')
st.title('JRA 予測・期待値ダッシュボード')
st.caption('CSV／URL出走表からの入力・AI確率・オッズ別期待値・購入候補の研究用表示。購入は自動実行しません。')

with st.sidebar:
 st.header('入力設定')
 card_dir=st.text_input('出走表CSVフォルダ','input/racecards')
 master=st.text_input('過去レースSQLite','keiba_master.sqlite')
 models_dir=st.text_input('モデル管理フォルダ','models')
 st.markdown('CSVを更新したら「再読込」を押してください。')
 st.caption('Cloud環境の保存領域は一時的です。PCのSQLiteは自動では転送されません。')
 with st.expander('履歴DBを一時的に利用（非公開アプリ推奨）'):
  st.warning('公開アプリには個人データや利用条件不明のDBをアップロードしないでください。アップロード内容はCloudサーバーで処理されます。')
  uploaded_master=st.file_uploader('履歴SQLiteファイル',type=['sqlite','sqlite3','db'],key='history_db_upload')
  if st.button('履歴DBを一時登録',key='upload_db_button'):
   if uploaded_master is None: st.error('DBファイルを選択してください')
   else:
    import tempfile, sqlite3, os
    from pathlib import Path
    if uploaded_master.size>300*1024*1024:st.error('300MBを超えるDBには対応しません')
    else:
     data=uploaded_master.getvalue()
     if not data.startswith(b'SQLite format 3\x00'):
      st.error('SQLiteデータベースではありません')
     else:
      fd,fn=tempfile.mkstemp(suffix='.sqlite',prefix='keiba_hist_')
      try:
       with os.fdopen(fd,'wb') as f:f.write(data)
       with sqlite3.connect('file:'+Path(fn).as_uri()[7:]+'?mode=ro',uri=True) as db:
        cols={r[1] for r in db.execute('PRAGMA table_info(race_results)').fetchall()}
        req={'horse_name','race_date','race_id','entry_id','finish_num','distance','last3f','surface','carried_weight'}
        if not req.issubset(cols):raise ValueError('race_resultsテーブルの必要列が不足：'+str(sorted(req-cols)))
       st.session_state['cloud_master_path']=fn
       st.success('履歴DBを一時登録しました（セッション・サーバー再起動後は再アップロードが必要です）')
      except Exception as e:
       try:os.unlink(fn)
       except OSError:pass
       st.error(f'DB検査失敗：{e}')
 master=st.session_state.get('cloud_master_path',master)
 if Path(master).is_file():st.caption('履歴DB：利用可能')
 else:st.warning('履歴DBがありません。出馬表の表示・PDF解析は可能ですが予測はできません。')
 if not Path(models_dir).exists():st.warning('モデルフォルダが見つかりません。')

 if st.button('再読込',type='primary'):st.cache_data.clear();st.rerun()
 template=Path('input/racecards/example_template.csv')
 if st.button('CSV入力見本を作成'):
  core.export_race_template(template);st.info(f'{template} に作成。サンプル馬を実在出走馬に置き換えてください。')

@st.cache_data(show_spinner=False,ttl=60)
def cached_cards(path):return core.load_cards(path)

st.subheader('新規レース情報の自動取得')
st.caption('許可済みの配信先/連携フォルダから取得します。JRAの公開Webページを無断でスクレイピングしません。')
with st.expander('開催日・競馬場・レース番号から取得',expanded=False):
 from datetime import date as _date
 a,b,c=st.columns(3)
 with a: fdate=st.date_input('開催日',value=_date.today())
 with b: fcourse=st.selectbox('競馬場',sorted(fetch.VENUES))
 with c: frace=st.selectbox('レース',list(range(1,13)),format_func=lambda x:f'{x}R')
 provider_cfg=st.text_input('取得先設定ファイル','racecard_provider.json')
 if st.button('データ取得してレース一覧を更新'):
  try:
   result=fetch.run(provider_cfg,fdate.isoformat(),fcourse,frace,card_dir)
   st.success(f"取得完了：{result['runners']}頭。オッズ取得件数 {result['odds_count']}、うち取得時刻付き {result['odds_with_timestamp']}")
   if result['odds_count']==0:st.warning('オッズは提供されていません。期待値は算出されません。')
   elif result['odds_with_timestamp']!=result['odds_count']:st.warning('取得時刻の無いオッズがあります。確率予測と購入判断を区別してください。')
   st.cache_data.clear();st.rerun()
  except Exception as exc:
   st.error(f'データ取得失敗（既存のCSVは変更されません）：{exc}')

# v2.9: URL-first; permanent source website links. No automatic crawling.
st.subheader('Web出馬表URLから取得（Ver.2.9）')
from importlib.util import spec_from_file_location, module_from_spec
_spec=spec_from_file_location('scrape_v28',str(Path(__file__).with_name('28_scrape_racecard.py')))
_scrape=module_from_spec(_spec);_spec.loader.exec_module(_scrape)
_source_spec=spec_from_file_location('sources_v29',str(Path(__file__).with_name('29_sources.py')))
_sources=module_from_spec(_source_spec);_source_spec.loader.exec_module(_sources)

st.markdown('**出走表を探すサイト（各サイトの親ページ）**')
for _s in _sources.SOURCES:
 st.markdown(f"- [{_s['label']}]({_s['url']}) — {_s['description']}")
st.caption('上のリンクは参照先の案内です。直接取得・解析の成功や自動取得の許諾を意味しません。')
with st.form('url_racecard_form'):
 _url=st.text_input('レース出馬表のURLを貼り付け',placeholder='https://race.netkeiba.com/race/shutuba.html?race_id=...',help='レースのURLをブラウザのアドレスバーからコピーしてください')
 _x,_y,_z=st.columns(3)
 with _x:_date29=st.date_input('開催日',key='web_race_date')
 with _y:_course29=st.selectbox('競馬場',sorted(fetch.VENUES),key='web_course')
 with _z:_race29=st.selectbox('レース番号',list(range(1,13)),key='web_race',format_func=lambda n:f'{n}R')
 _consent=st.checkbox('対象サイトの利用条件を確認し、この単発取得が許可されていることを確認しました')
 _submit=st.form_submit_button('URLから出走表を取得',type='primary')
if _submit:
 try:
  _safe_url=_sources.validate_target_url(_url)
  if not _consent:raise PermissionError('取得元の利用条件の確認が必要です。許可を確認してから実行してください。')
  from types import SimpleNamespace as _NS
  _args=_NS(html='',url=_safe_url,source_url='',date=_date29.isoformat(),course=_course29,
            race=_race29,out=card_dir,report='output/v29/url_fetch_report.json',
            confirm_permission=True,dry_run=False)
  _result=_scrape.run(_args)
  st.success(f"出走表CSVを更新しました：{_result['runners']}頭")
  st.info('取得したHTMLの構造はパーサーで検査しましたが、公式原本との全頭照合は未実施です。')
  if _result['odds_rows_without_proven_timestamp']:
   st.warning('HTML内のオッズには有効な取得時刻がありません。購入時の期待値には使用しないでください。')
  st.cache_data.clear();st.rerun()
 except Exception as _exc:
  st.error(f'URL取得・解析を中止：{_exc}。既存のCSVは変更しません。')

# v3.1: JRA official racecard PDF discovery/download/review -> verified CSV -> current prediction pipeline.
st.subheader('JRA公式PDFから出馬表を取得（Ver.3.1・無料）')
st.caption('JRAの開催場別PDFから指定レースを解析します。CloudではブラウザPDFアップロードも利用できます。公式PDFに単勝・複勝の時点オッズは通常含まれません。抽出結果の確認後にのみ予測CSVへ登録します。')
st.link_button('JRA公式｜開催場別出馬表PDF一覧','https://www.jra.go.jp/keiba/rpdf/')
_rpdf_spec=spec_from_file_location('jra_rpdf_v31',str(Path(__file__).with_name('31_jra_rpdf.py')))
_rpdf=module_from_spec(_rpdf_spec);_rpdf_spec.loader.exec_module(_rpdf)
with st.expander('JRA公式PDFを検索・取得する',expanded=True):
 from datetime import date as _date31
 _a,_b,_c=st.columns(3)
 with _a: _dt31=st.date_input('開催日',value=_date31.today(),key='pdf_date')
 with _b: _venue31=st.selectbox('競馬場',list(_rpdf.VENUE_EN),key='pdf_venue')
 with _c: _race31=st.selectbox('レース',list(range(1,13)),key='pdf_race',format_func=lambda x:f'{x}R')
 _date_str31=_dt31.isoformat()
 _confirm31=st.checkbox('JRA公式サイトの利用条件を確認し、個人利用として対象PDFを単発取得します',key='pdf_permission')
 if st.button('公式PDF一覧を検索',key='pdf_discover'):
  try:
   _html31=_rpdf._read_url(_rpdf.INDEX_URL,'index',2_000_000)
   _matches31=_rpdf.discover_rpdf(_html31,_date_str31,_venue31)
   st.session_state['pdf_links31']=_matches31
   if not _matches31:st.warning('該当PDFが見つかりません。掲載期間は原則8週間です。手動保存したPDFも解析できます。')
  except Exception as exc:st.error(f'一覧の自動取得を停止：{exc}。JRAページからPDFを手動保存してください。')
 _links31=st.session_state.get('pdf_links31',[])
 if _links31:
  st.markdown('**掲載PDF候補**')
  for _l in _links31:st.markdown(f"- [{_l['label'] or _l['filename']}]({_l['url']})")
 _download_url31=st.text_input('PDFの直接URL（一覧検索の結果から選択／手動貼付）',value=_links31[0]['url'] if len(_links31)==1 else '',key='pdf_url')
 _manual31=st.text_input('または、サーバー上の公式PDFのパス（ローカル実行用）',value='',key='pdf_local_path')
 _upload31=st.file_uploader('Cloud向け：ブラウザ保存した公式PDFをアップロード',type=['pdf'],key='jra_pdf_uploaded',help='このアップロードを優先します。掲載PDFの出所と利用条件を確認してください。')
 if st.button('PDFを読み込んで指定レースを解析',type='primary',key='pdf_parse'):
  try:
   if _upload31 is not None:
    import tempfile
    _folder31=Path('input/jra_pdf_racecards');_folder31.mkdir(parents=True,exist_ok=True)
    _upload_name31=Path(_upload31.name).name
    _rpdf.verify_pdf_identity(_upload_name31,_date_str31,_venue31)
    _data31=_upload31.getvalue()
    if not _data31.startswith(b'%PDF-') or len(_data31)>12_000_000:
     raise _rpdf.IntakeError('アップロードPDFの形式またはサイズが不適切です')
    _file31=_folder31/_upload_name31
    _file31.write_bytes(_data31)
   elif _manual31.strip():
    _file31=Path(_manual31.strip());_rpdf.verify_pdf_identity(_file31,_date_str31,_venue31)
   else:
    if not _confirm31:raise _rpdf.IntakeError('単発の自動取得を実行する前に利用条件を確認してください')
    _url31=_rpdf.allowed_url(_download_url31.strip(),'pdf')
    _filename31=Path(urlparse(_url31).path).name
    _rpdf.verify_pdf_identity(_filename31,_date_str31,_venue31)
    _raw31=_rpdf._read_url(_url31,'pdf')
    _folder31=Path('input/jra_pdf_racecards');_folder31.mkdir(parents=True,exist_ok=True)
    _file31=_folder31/_filename31;_file31.write_bytes(_raw31)
   _out31=Path('output/v31')/_date_str31/(_rpdf.VENUE_EN[_venue31]+f'_{_race31:02d}')
   _diag31=_rpdf.analyze_pdf(_file31,_date_str31,_venue31,_race31,_out31)
   st.session_state['pdf_output31']=str(_out31)
   st.session_state['pdf_run_key31']=f'{_date_str31}_{_venue31}_{_race31}'
   st.success(f'PDFを解析しました：{_race31}R・{_diag31["draft_rows"]}候補行（未承認）')
  except Exception as exc:st.error(f'PDF取込を停止：{exc}。出走表CSVは変更していません。')
 _out_path31=st.session_state.get('pdf_output31','')
 _current_key31=f'{_date_str31}_{_venue31}_{_race31}'
 if _out_path31 and st.session_state.get('pdf_run_key31')==_current_key31:
  _path31=Path(_out_path31)
  st.image(str(_path31/'race_panel.png'),caption=f'{_race31}R原本画像（照合用）',use_container_width=False)
  st.warning('PDFの組版・文字化けにより名前や馬番の読み違いがあります。すべて原本と照合し、未確認データはYESに変更しないでください。')
  _draft31=pd.read_csv(_path31/'review_draft.csv',dtype=str,keep_default_na=False,encoding='utf-8-sig')
  st.caption('PDFからの候補を編集。未取得の項目（芝/ダート・距離・斤量・騎手・調教師等）は原本を見て補完してください。')
  _expected31=st.number_input('PDF原本に記載された出走頭数',min_value=5,max_value=18,value=max(5,min(18,len(_draft31))),step=1,key='pdf_expected31')
  _edited31=st.data_editor(_draft31,num_rows='dynamic',use_container_width=True,key='pdf_editor31')
  if st.button('確認済みの出走表をCSVに登録',key='pdf_publish31'):
   try:
    _review_path31=_path31/'review_checked.csv';_edited31.to_csv(_review_path31,index=False,encoding='utf-8-sig')
    _pub31=_rpdf.check_and_publish(_review_path31,_date_str31,_venue31,_race31,card_dir,_expected31)
    st.success(f'登録成功：{_pub31["runners"]}頭。左の再読込でレース一覧に反映されます。')
    st.cache_data.clear()
   except Exception as exc:st.error(f'登録停止：{exc}')

cards,errors=cached_cards(card_dir)
for error in errors:st.warning(error)
if cards.empty:
 st.info('出走表CSVがありません。サイドバーの「CSV入力見本を作成」から始められます。CSVは1行1頭です。')
 st.code('race_date,course,race_number,horse_number,horse_name,surface,distance,carried_weight,jockey,trainer,track_condition,win_odds,place_odds,odds_timestamp')
 st.stop()

races=(cards.groupby('race_key').agg(date=('race_date','first'),course=('course','first'),
    race_number=('race_number','first'),n=('horse_number','size')).sort_values(['date','course','race_number'],ascending=[False,True,True]))
options=list(races.index)
labels={k:f'{r.date} {r.course} {int(r.race_number)}R（{int(r.n)}頭）' for k,r in races.iterrows()}
key=st.selectbox('予測対象のレース',options,format_func=lambda k:labels[k])
selected=cards[cards.race_key==key].copy().sort_values('horse_number')
if selected.horse_number.duplicated().any():st.error('馬番が重複しています');st.stop()
if selected.course.nunique()!=1 or selected.surface.nunique()!=1 or selected.distance.nunique()!=1:
 st.error('競馬場・馬場種別・距離が一致しません。CSVを修正してください。');st.stop()
if len(selected)<5:st.warning('5頭未満の出走表です。学習データの対象条件と異なります。')
st.subheader('自動取込された出走情報')
st.dataframe(selected[['horse_number','horse_name','carried_weight','jockey','trainer','track_condition','win_odds','place_odds','odds_timestamp']],hide_index=True,use_container_width=True)

if st.button('このレースを予測',type='primary',disabled=not Path(master).is_file(),help='履歴DBが必要です。サイドバーから登録してください。'):
 try:
  feat=core.build_live_features(selected,master)
  predictions=core.predict(feat,models_dir)
  st.session_state['predicted']=predictions
  st.session_state['predicted_key']=key
 except Exception as e:st.error(f'予測に失敗: {e}')

if st.session_state.get('predicted_key')==key and 'predicted' in st.session_state:
 res=st.session_state.predicted.copy()
 st.subheader('AI予測と購入期待値')
 st.warning('重要：既存の学習データは2021年までです。2022〜2026年の履歴が未補完の場合、近走特徴量が欠け、現在の予測値は参考値です。')
 if (res.model_win_status!='champion').any() or (res.model_place_status!='champion').any():
  st.warning('使用モデルは本番承認されていない候補モデルです。実際の購入判断には利用しないでください。')
 if res.odds_warning.ne('').any():st.warning('オッズの取得時刻が不明です。期待値は参考値です。')
 if res.history_coverage_warning.any():st.warning(f'過去走が未取得の馬：{int(res.history_coverage_warning.sum())}頭')
 table=res[['horse_number','horse_name','p_win','p_place','win_odds','place_odds','ev_win','ev_place','past_races']].sort_values('p_win',ascending=False)
 st.dataframe(table,hide_index=True,use_container_width=True,column_config={
   'p_win':st.column_config.NumberColumn('単勝予測確率',format='%.3f',help='値は0〜1。0.1は10%を意味します。'),
   'p_place':st.column_config.NumberColumn('複勝予測確率',format='%.3f'),
   'ev_win':st.column_config.NumberColumn('単勝EV',format='%.3f'),
   'ev_place':st.column_config.NumberColumn('複勝EV',format='%.3f')})
 st.caption('単勝・複勝予測確率は0〜1。EV = 予測確率 × 表示オッズ − 1。リアルタイム最終オッズではありません。')
 st.metric('単勝確率の合計（整合性の参考）',f'{res.p_win.sum():.3f}')
 st.metric('複勝確率の合計（整合性の参考）',f'{res.p_place.sum():.3f}')
 st.download_button('予測CSVを保存',res.to_csv(index=False).encode('utf-8-sig'),file_name=f'{key}_predictions.csv',mime='text/csv')

 st.subheader('オッズに基づく購入候補（Ver.3.0・研究用）')
 st.caption('単勝・複勝のみ。オッズは払戻込みの倍率。複勝は下限倍率を入力してください。買い候補の表示は購入の自動実行ではありません。')
 from importlib.util import spec_from_file_location as _spec_from, module_from_spec as _mod_from
 _adspec=_spec_from('bet_advisor_v30',str(Path(__file__).with_name('30_bet_advisor.py')))
 _advisor=_mod_from(_adspec);_adspec.loader.exec_module(_advisor)
 cc1,cc2,cc3=st.columns(3)
 with cc1: _min_ev=st.number_input('最低期待収益率（%）',min_value=0,max_value=200,value=10,step=5,key='bet_min_ev')
 with cc2: _budget=st.number_input('1レースの上限予算（円）',min_value=0,max_value=100000,step=100,value=1000,key='bet_budget')
 with cc3: _stake=st.number_input('1点の購入額（円）',min_value=100,max_value=10000,step=100,value=100,key='bet_stake')
 _fresh=st.slider('オッズの最大経過時間（分）',min_value=1,max_value=180,value=30,step=1,key='bet_fresh')
 try:
  _all,_recommend,_summary=_advisor.evaluate(res,min_ev=_min_ev/100,max_age_minutes=_fresh,
      budget_yen=_budget,stake_yen=_stake)
  if _summary['probability_integrity_warning']:
   st.warning('予測確率のレース内合計が基準範囲外です。オッズが揃っていても買い推奨を停止します。')
  k1,k2,k3=st.columns(3)
  k1.metric('条件を満たす候補',_summary['eligible'])
  k2.metric('買い候補点数',_summary['selected'])
  k3.metric('提案購入額',f"{_summary['planned_stake_yen']:,}円")
  if _recommend.empty:
   st.info('現時点で購入条件を満たす馬券はありません。未承認モデル・時刻不明オッズ・過去走不足のときは購入提案を停止します。')
  else:
   st.markdown('**条件を満たした購入候補（自動投票はしません）**')
   st.dataframe(_recommend[['market','horse_number','horse_name','probability','odds','expected_roi','stake_yen']],
        hide_index=True,use_container_width=True)
  st.markdown('**全馬券の候補・除外理由**')
  st.dataframe(_all[['market','horse_number','horse_name','probability','odds','expected_roi','eligible','reason','odds_timestamp']],
      hide_index=True,use_container_width=True)
  st.download_button('購入候補・除外理由CSVを保存',_all.to_csv(index=False).encode('utf-8-sig'),
      file_name=f'{key}_bet_screening.csv',mime='text/csv')
 except Exception as _err:
  st.error(f'購入候補の計算に失敗：{_err}')
 st.caption('注意：予測確率には推定誤差があります。市場オッズは変化し、当日の払戻は確定値と異なる場合があります。')

st.divider()
st.subheader('モデル評価・自動更新の状況')
for filename in ['output/v25/model_ranking.csv','output/v26/ranking_v26.csv']:
 p=Path(filename)
 if p.is_file():
  st.markdown(f'**{filename}**')
  st.dataframe(pd.read_csv(p,encoding='utf-8-sig'),hide_index=True,use_container_width=True)
for fn in ['win','place']:
 p=Path(models_dir)/f'champion_{fn}.json'
 if p.is_file():
  try:st.success(f'{fn} 本番モデル：{json.loads(p.read_text(encoding="utf-8")).get("model")}')
  except Exception:st.warning(f'{fn} の管理情報を読み取れません')
 else:st.info(f'{fn}：本番自動採用はまだ行っていません。候補を比較している段階です。')
st.caption('出走情報は承認済みデータソースが設定されている場合のみ自動取込できます。結果の自動学習データ取得は未接続です。')
