# JRA競馬予想AI — Streamlit Community Cloud対応版 (Ver.3.2 Cloud package)

## デプロイ方法
1. GitHubで**Private**リポジトリを作成（権限に注意）。ZIPを解凍した**中身**をリポジトリ直下にアップロードします（ZIPそのものを置くだけでは起動しません）。
2. https://share.streamlit.io/ へアクセスし、GitHubアカウントでログインして **Create app**。
3. Repositoryと`main`ブランチを選択し、**Main file path**に `app.py` と入力します。
4. Advanced settingsでPython `3.12`（利用可能なら）を選択してDeployします。
5. 初回起動後、開催日・競馬場・レースを指定し、公式出馬表PDFへのアクセスが許可されるか確認します。不可ならブラウザ保存した公式PDFをファイルアップロードしてください。

## 含まれるもの
- `app.py` Streamlit Cloud起動ファイル（Main file path）。`26_app.py` が本体
- `26_mvp_core.py` 履歴特徴量・モデル読込・確率算出
- `27_racecard_fetch.py` 許可済みCSV/JSON提供元からの取得
- `28_scrape_racecard.py` URL取込（利用条件とrobots確認必須）
- `29_sources.py` 各サイト参照リンク
- `30_bet_advisor.py` オッズ鮮度・予算制限付き単勝/複勝候補（自動投票なし）
- `31_jra_rpdf.py` 公式出馬表PDFの検索・抽出・レビュー
- `models/model_win_2017.txt` と `models/model_place_2017.txt` : 2010〜17学習済みLightGBM基準モデル（**本番承認前**）
- `requirements.txt`, `.streamlit/config.toml`, `.gitignore`, `test_*.py`。

## 重要な制約
**職場ネットワークのFortiGuardによるJRA遮断は、業務ネットワークの利用制限です。** クラウド配置は環境切替のための技術検証であり、所属組織の利用規程を回避する目的では使用しないでください。会社の承認が必要な場合は管理者に確認してください。

- Streamlit CloudからJRAへアクセスできるかは**未検証**。Cloudからもrobots・規約・サイトアクセス制限は尊重します。
- `keiba_master.sqlite` は**意図的に同梱していません**。大きなDBやデータの公開は避けてください。Cloudの「履歴DBを一時的に利用」アップロードは許可されたデータを、**非公開アプリで**一時的に使う用途のみ推奨します（サーバーメモリ・再起動による消失に注意）。DBが無い場合、予測は停止します。
- モデル2本は検証用ベースラインです。Champion認証なしのため、**購入推奨は自動的に停止**します。
- 出馬表PDFに時点オッズはありません。オッズがなければEVは計算できません。
- PDFの自動抽出は実JRA PDFで全頭検証されていません。人によるレビューが必須です。
- Cloudは24時間稼働・データ永続保存・タスクスケジューラを保証しません。月次学習の安定運用は別途設計が必要です。
- ライブラリはCloud実行に必要なものだけ指定し、XGBoost/CatBoostの**学習機能はこのCloudパッケージのrequirementsでは導入しません**。ローカルの学習用環境は別管理としてください。
- `.gitignore` は新規のGit追加を抑止しますが、既にGitで追跡済みのファイルを削除しません。DB、オッズCSV、パスワード等を絶対に公開しないでください。

## ローカル起動とテスト
```
python -m pip install -r requirements.txt
python test_v31.py
python -m streamlit run 26_app.py
```

## 将来の拡張
- 更新済み・許諾済み履歴データの永続ストレージ
- 事前オッズの正規提供元
- 2022〜2026年の独立評価、モデル自動更新・自動選抜のバッチ（Cloud画面とは別で定期実行）
