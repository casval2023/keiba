# -*- coding: utf-8 -*-
"""User-facing trusted navigation and URL matching. No crawling/discovery."""
from urllib.parse import urlparse

SOURCES = [
    {'label':'JRA公式（出馬表・開催情報）','url':'https://www.jra.go.jp/keiba/','domain':'www.jra.go.jp','kind':'reference','description':'レース情報確認用。現在のHTMLパーサーとの互換性は未検証'},
    {'label':'netkeiba（出馬表）','url':'https://race.netkeiba.com/','domain':'race.netkeiba.com','kind':'racecard','description':'公開出馬表を探すためのリンク。直接取得は利用条件・robots.txtの確認が必要'},
    {'label':'JRA-VAN Data Lab.','url':'https://jra-van.jp/dlb/','domain':'jra-van.jp','kind':'provider','description':'正規データ連携候補。契約・JV-Link接続は未設定'},
]

VALID_HOSTS = {'race.netkeiba.com','www.jra.go.jp','jra.go.jp'}

def validate_target_url(url):
    u=urlparse(str(url or '').strip())
    if u.scheme!='https' or (u.hostname or '').lower() not in VALID_HOSTS:
        raise ValueError('https://race.netkeiba.com または https://www.jra.go.jp の出馬表URLのみ指定できます')
    if u.username or u.password or u.fragment or u.port not in (None,443):
        raise ValueError('URLに認証情報・フラグメント・任意のポートを指定できません')
    if not u.path or u.path=='/':
        raise ValueError('サイトのトップページではなく対象レースの出馬表URLを指定してください')
    return u.geturl()
