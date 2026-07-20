"""
💰🐦 DMMアフィリエイト → X（Twitter）投稿文ジェネレーター
DMMから商品情報を取得し、X投稿用テキストをデスクトップまたは指定フォルダに保存します。

【v3: 報酬ゼロ対策・サービス新規報酬獲得を重視した改善】

■ 問題の原因分析
- クリック数はあるが報酬ゼロ → FANZAの「ダイレクト報酬」「カテゴリ報酬」が発生していない
- 最も稼ぎやすい「サービス新規報酬」（新規会員登録）が全くゼロ
- 原因: 投稿文がFANZA既存会員向けになっており、未登録者に響いていなかった

■ v3の主な変更点
- FANZA未登録者への「無料会員登録」訴求コピーを追加（サービス新規報酬を狙う）
- ポスト1にアフィリエイトURLも掲載（サンプルURL + 作品ページURL の両立）
- ハッシュタグを #AV #FANZAおすすめ から #アダルト動画 #無料サンプルあり 等に変更
  （既存会員ではなく未登録ユーザーへのリーチを優先）
- ヘッダー文に「無料で見られる」「FANZAのサンプル」など発見訴求を追加

■ v8の変更点
- サンプル動画は実際には会員登録なしで視聴できるため、
  「サンプルを見るのに登録が必要」という誤解を与えていたコピーを全て修正。
  会員登録の訴求は「購入するとき」に必要なものとして、訴求順序を後ろに整理した。
- 未使用だった旧スレッド投稿用関数（build_x_post/build_x_thread）とREGISTRATION_HOOKSを削除。

■ v9の変更点（報酬ゼロ対策・続き）
- Xは本文に外部リンクが含まれる投稿の表示を抑制する傾向があるとされるため、
  投稿を「1件目＝本文＋動画（URLなし）」「2件目＝リプライでURL＋タグ」の
  2ツイートのスレッドに分割（Buffer側のthread機能を利用）。
- FANZA_TV_AFFILIATE_URL を設定すると、月額見放題サービス（FANZA TV等）の
  併用訴求を一定確率（FANZA_TV_PROMO_RATE、デフォルト25%）でリプライに追加し、
  サービス新規報酬の獲得チャンスを広げる。

AUTO_POST_TO_X=true を設定すると、SNS管理ツール「Buffer」のGraphQL API経由で
Xへ1投稿（build_x_single_post生成のテキスト＋可能ならサンプル動画クリップ）を予約投稿します
（Bufferの無料プランで動作し、X公式APIの投稿課金は発生しません）。
  要：BUFFER_API_KEY / BUFFER_CHANNEL_ID（buffer_channel_setup.py参照）。
未設定時は従来どおりテキストファイル保存のみで完全無料で動作します。
"""

import os
import sys
import json
import datetime
import requests
import random
import re
import subprocess
import tempfile
import time
from pathlib import Path

# ================================================================
# ⚙️  設定（環境変数から読み込み）
# ================================================================

DMM_API_ID       = os.environ.get('DMM_API_ID', '')
DMM_AFFILIATE_ID = os.environ.get('DMM_AFFILIATE_ID', '')

if not DMM_API_ID or not DMM_AFFILIATE_ID:
    print('❌ 環境変数 DMM_API_ID / DMM_AFFILIATE_ID が設定されていません。')
    sys.exit(1)

print('✅ 認証情報を読み込みました。')

DMM_FLOOR = os.environ.get('DMM_FLOOR', 'videoa')

# ----------------------------------------------------------------
# 📌 ソートモード設定（作品リストの取得順。切り替え可能）
#    DMM_SORT_MODE=date（デフォルト）→ 新着順のみ。自動投稿のデフォルト動作と一致
#    DMM_SORT_MODE=both              → 新着 ＋ 人気 の両方を1ファイルに保存
#    DMM_SORT_MODE=rank              → 人気順のみ
#    ※自動投稿（AUTO_POST_TO_X=true）は取得した候補を常に配信日の新しい順に
#      並べ替えてから投稿するため、rank/bothを選んでも投稿順は新着優先になる。
# ----------------------------------------------------------------
DMM_SORT_MODE = os.environ.get('DMM_SORT_MODE', 'date').lower()

SORT_TARGETS = {
    'both': [('date', '新着順'), ('rank', '人気順')],
    'date': [('date', '新着順')],
    'rank': [('rank', '人気順')],
}
SORT_LIST = SORT_TARGETS.get(DMM_SORT_MODE, SORT_TARGETS['date'])

# ----------------------------------------------------------------
# 🔢 処理件数の上限（速度優先のため、1回の実行で処理する商品数の合計を制限する）
#    DMM_SORT_MODE=both のように複数ソートを使う場合は、合計でこの件数に収まるよう
#    各ソートの取得件数を自動的に按分する。
# ----------------------------------------------------------------
MAX_PROCESS_COUNT = int(os.environ.get('MAX_PROCESS_COUNT', '100'))
print(f'🔢 処理件数の上限: 合計 {MAX_PROCESS_COUNT} 件（ソート {len(SORT_LIST)} 種類）')

# ----------------------------------------------------------------
# 🔽 価格フィルター使用時の最低保証件数
#    価格フィルターで絞り込んだ後も、この件数に達するまで追加取得を繰り返す。
#    MIN_PROCESS_COUNT=0 で無効化（従来の動作に戻る）
# ----------------------------------------------------------------
MIN_PROCESS_COUNT = int(os.environ.get('MIN_PROCESS_COUNT', '40'))

# ----------------------------------------------------------------
# 🎲 取得開始位置（環境変数未設定時はランダム: 1〜480）
#    ただし新着順（-date）で取得する場合、空欄（未指定）なら「最新のデータ」から
#    検索したいので、その場合は開始位置を1固定にする（POST_START_INDEX_EXPLICITで判定）。
# ----------------------------------------------------------------
_raw_start = os.environ.get('POST_START_INDEX', '')
POST_START_INDEX_EXPLICIT = _raw_start.strip().isdigit()
if POST_START_INDEX_EXPLICIT:
    POST_START_INDEX = int(_raw_start.strip())
    print(f'📌 指定された取得開始番号: {POST_START_INDEX}')
else:
    POST_START_INDEX = random.randint(1, 480)
    print(f'🎲 ランダム取得開始番号: {POST_START_INDEX}（新着順検索では未指定時は1件目＝最新データから検索します）')

FETCH_COUNT = MAX_PROCESS_COUNT if len(SORT_LIST) == 1 else max(1, -(-MAX_PROCESS_COUNT // len(SORT_LIST)))  # 単一ソートは全件、複数ソートは切り上げ按分（例: 30件÷2ソート=15件ずつ）
DMM_OFFSET  = POST_START_INDEX
DMM_HITS    = FETCH_COUNT

# ----------------------------------------------------------------
# 🔁 FANZA/DMM API リトライ設定
#    通信エラーやAPI側のエラー応答（一時的なレート制限等）が発生した場合、
#    すぐに諦めず、FANZA APIの問い合わせ上限（DMM_MAX_RETRIES回）まで
#    間隔を空けながらリトライする。
# ----------------------------------------------------------------
DMM_MAX_RETRIES    = int(os.environ.get('DMM_MAX_RETRIES', '10'))
DMM_RETRY_WAIT_SEC = float(os.environ.get('DMM_RETRY_WAIT_SEC', '3'))

# ----------------------------------------------------------------
# 💰 価格フィルター設定
#    DMM_PRICE_RANGE=all（デフォルト）→ 価格による絞り込みなし
#    その他の指定例:
#      "0-999"    → 0円〜999円
#      "1000-1999"→ 1000円〜1999円
#      "2000-2999"→ 2000円〜2999円
#      "3000-4999"→ 3000円〜4999円
#      "5000-"    → 5000円以上
# ----------------------------------------------------------------
DMM_PRICE_RANGE = os.environ.get('DMM_PRICE_RANGE', 'all').strip().lower()

# ----------------------------------------------------------------
# 🎯 ジャンル特化フィルター（DMM ItemList APIのarticle/article_id）
#    DMM_ARTICLE     : 絞り込み種別。例 "genre"（ジャンル）"actress"（女優）"director"（監督）"series"（シリーズ）"maker"（メーカー）
#    DMM_ARTICLE_ID   : 上記種別に対応するID（1件のみ。DMM APIの GenreSearch/ActressSearch 等で事前に調べる）
#    どちらか一方でも空欄なら絞り込みなし（従来どおり全ジャンルを対象にする）。
# ----------------------------------------------------------------
DMM_ARTICLE    = os.environ.get('DMM_ARTICLE', '').strip().lower()
DMM_ARTICLE_ID = os.environ.get('DMM_ARTICLE_ID', '').strip()
GENRE_FILTER_ENABLED = bool(DMM_ARTICLE and DMM_ARTICLE_ID)
if GENRE_FILTER_ENABLED:
    print(f'🎯 ジャンル特化フィルター: 有効（article={DMM_ARTICLE} / article_id={DMM_ARTICLE_ID}）')
else:
    print('🎯 ジャンル特化フィルター: なし（全ジャンル対象）')

# NTR（寝取り・寝取られ）ジャンル特化時は、投稿文の煽り文・見出しをNTR向けの
# 訴求内容に寄せる。DMM_ARTICLE_IDでジャンルを判定する（genresearch.py参照）。
NTR_GENRE_IDS = {'4111'}
IS_NTR_FOCUSED = (
    GENRE_FILTER_ENABLED and DMM_ARTICLE == 'genre' and DMM_ARTICLE_ID in NTR_GENRE_IDS
)

def parse_price_range(range_str):
    """価格範囲文字列を (min, max) のタプルに変換する。max=Noneは上限なし。"""
    if not range_str or range_str == 'all':
        return None
    range_str = range_str.replace('円', '').replace(',', '').strip()
    if '-' not in range_str:
        return None
    min_part, max_part = range_str.split('-', 1)
    min_part = min_part.strip()
    max_part = max_part.strip()
    try:
        price_min = int(min_part) if min_part else 0
    except ValueError:
        price_min = 0
    if max_part:
        try:
            price_max = int(max_part)
        except ValueError:
            price_max = None
    else:
        price_max = None
    return (price_min, price_max)

PRICE_RANGE_BOUNDS = parse_price_range(DMM_PRICE_RANGE)
if PRICE_RANGE_BOUNDS:
    _pmin, _pmax = PRICE_RANGE_BOUNDS
    _pmax_label = f'{_pmax:,}円' if _pmax is not None else '上限なし'
    print(f'💰 価格フィルター: {_pmin:,}円 〜 {_pmax_label}')
else:
    print('💰 価格フィルター: なし（すべての価格を対象）')

# ----------------------------------------------------------------
# 📺 FANZA TV（DMMプレミアム）併用訴求設定
#    単品作品だけでなく、月額見放題サービスも一緒に紹介すると成約率が上がりやすいとされるため、
#    設定時は一定確率でリプライ欄に併用訴求を追加する（サービス新規報酬の獲得を狙う）。
#    FANZA_TV_AFFILIATE_URL 未設定時はこの機能自体が無効になる。
# ----------------------------------------------------------------
FANZA_TV_AFFILIATE_URL = os.environ.get('FANZA_TV_AFFILIATE_URL', '').strip()
FANZA_TV_PROMO_RATE = float(os.environ.get('FANZA_TV_PROMO_RATE', '0.25'))
FANZA_TV_PROMO_LINES = [
    "📺 ちなみに月額550円の「FANZA TV」ならアダルト見放題対象になってることも多いです👇",
    "📺 見放題の「FANZA TV」に入ってれば追加料金なしで見られるかも👇",
    "📺 単品もいいけど、月550円のFANZA TV（見放題）も地味にコスパ良いです👇",
]
if FANZA_TV_AFFILIATE_URL:
    print(f'📺 FANZA TV併用訴求: 有効（出現率 {FANZA_TV_PROMO_RATE:.0%}）')

# ----------------------------------------------------------------
# 🐦 X（Twitter）自動投稿設定（Buffer経由のみ対応・デフォルトでON）
#    AUTO_POST_TO_X=true（デフォルト）: Buffer経由でXにスレッド投稿（予約投稿）を作成する。
#    AUTO_POST_TO_X=false             : テキスト生成のみ（投稿はしない）。
# ----------------------------------------------------------------
AUTO_POST_TO_X = os.environ.get('AUTO_POST_TO_X', 'true').strip().lower() == 'true'

# --- Buffer方式の認証情報 ---
# BUFFER_API_KEY    : Buffer管理画面の「API」設定ページで発行するPersonal API Key
# BUFFER_CHANNEL_ID : 投稿先のXチャンネルID（buffer_channel_setup.py で確認可能）
BUFFER_API_KEY    = os.environ.get('BUFFER_API_KEY', '')
BUFFER_CHANNEL_ID = os.environ.get('BUFFER_CHANNEL_ID', '')

# Bufferの予約方法
#   addToQueue     : Buffer側にあらかじめ設定した投稿スケジュール枠に自動で割り当てる
#   customScheduled: dueAtで指定した日時ちょうどに予約する（デフォルト）
BUFFER_SCHEDULING_MODE   = os.environ.get('BUFFER_SCHEDULING_MODE', 'customScheduled').strip()
# customScheduled時、1件目を「今から何分後」に予約するか
BUFFER_INITIAL_DELAY_MIN = float(os.environ.get('BUFFER_INITIAL_DELAY_MIN', '2'))
# customScheduled時、2件目以降を何分間隔で予約するか（Bot的な一斉投稿に見えないようにする）
# デフォルト12分 × 5件 = 2,14,26,38,50分後 と、1時間以内に収まる間隔にしている
# （1時間ごとに5作品投稿するデフォルト運用を想定）
BUFFER_POST_INTERVAL_MIN = float(os.environ.get('BUFFER_POST_INTERVAL_MIN', '12'))

# 1回の実行で実際に投稿する最大件数（Buffer側のレート制限・キュー溢れを防ぐため必ず上限を設ける）
# デフォルト5件（1時間ごとに実行する想定で「1時間ごとに5作品」のペースになる）
X_POST_LIMIT = int(os.environ.get('X_POST_LIMIT', '5'))

# --- 投稿スケジュール戦略（customScheduled時のみ有効） ---
#   interval      : 今から一定間隔で機械的に予約（従来どおり。BUFFER_POST_INTERVAL_MIN間隔）
#   optimal_hours : 反応が良いとされる時間帯に絞って予約する
BUFFER_SCHEDULE_STRATEGY = os.environ.get('BUFFER_SCHEDULE_STRATEGY', 'interval').strip()

# optimal_hours時に使う「反応が良い」とされる時間帯（開始時, 終了時）のリスト。
# デフォルトは一般的に反応が良いとされる朝・昼・夜の3枠（JST・24時間表記）。
# 環境変数でJSON文字列として上書き可能（例: '[[7,9],[12,13],[19,23]]'）。
_DEFAULT_OPTIMAL_WINDOWS = [(7, 8), (12, 13), (20, 23)]
try:
    _optimal_windows_env = os.environ.get('BUFFER_OPTIMAL_WINDOWS', '').strip()
    OPTIMAL_TIME_WINDOWS = (
        [tuple(w) for w in json.loads(_optimal_windows_env)] if _optimal_windows_env else _DEFAULT_OPTIMAL_WINDOWS
    )
except Exception:
    print('⚠️  BUFFER_OPTIMAL_WINDOWSの形式が不正なため、デフォルトの時間帯を使用します。')
    OPTIMAL_TIME_WINDOWS = _DEFAULT_OPTIMAL_WINDOWS

# optimal_hours時の基準タイムゾーン（時差・時間単位）。デフォルトはJST（UTC+9）。
BUFFER_TIMEZONE_OFFSET_HOURS = float(os.environ.get('BUFFER_TIMEZONE_OFFSET_HOURS', '9'))

if AUTO_POST_TO_X:
    if not BUFFER_API_KEY or not BUFFER_CHANNEL_ID:
        print('❌ AUTO_POST_TO_X=true ですが BUFFER_API_KEY / BUFFER_CHANNEL_ID が不足しています。')
        print('   Bufferの「API」設定ページでPersonal API Keyを発行し、')
        print('   buffer_channel_setup.py でチャンネルIDを確認してください。')
        print('   （投稿せずテキスト生成だけ行いたい場合は AUTO_POST_TO_X=false を指定してください）')
        sys.exit(1)
    _schedule_desc = (
        f'反応が良い時間帯優先（{", ".join(f"{s}-{e}時" for s, e in OPTIMAL_TIME_WINDOWS)}・JST基準）'
        if BUFFER_SCHEDULE_STRATEGY == 'optimal_hours' else f'{BUFFER_POST_INTERVAL_MIN}分間隔'
    )
    print(f'🐦 自動投稿モード: ON / Buffer経由（最大 {X_POST_LIMIT} 件・予約方式: {BUFFER_SCHEDULING_MODE}・投稿間隔: {_schedule_desc}・配信日が新しい順に投稿）')
    print('   ℹ️  X公式APIの投稿課金は発生しません（Bufferの無料プランで利用可）。')
    print('   ⚠️  ただしBufferなどSNS管理ツール側の利用規約・アダルトコンテンツに関するポリシーは')
    print('       別途ご自身でご確認ください（規約に反する場合、Buffer側のアカウント停止リスクがあります）。')
else:
    print('🐦 自動投稿モード: OFF（テキストファイル保存のみ・無料）')

DMM_API_BASE = 'https://api.dmm.com/affiliate/v3'



FLOOR_SERVICE_MAP = {
    'videoa':  ('digital', 'videoa'),
    'videoc':  ('digital', 'videoc'),
    'anime':   ('digital', 'anime'),
    'doujin':  ('doujin',  'digital_doujin'),
    'comic':   ('ebook',   'comic'),
    'goods':   ('mono',    'goods'),
    'digital': ('digital', 'videoa'),
}

HASHTAG_MAP = {
    # 【v3改善】非会員ユーザーにリーチしやすいタグ構成
    # #AV や #FANZAおすすめ は既存会員ばかりに届く傾向があるため変更
    # 一般エンタメ・動画系タグで間口を広げ、FANZA未登録層にアプローチ
    'videoa': '#アダルト動画 #FANZA ',
    'videoc': '#素人動画 #FANZA #個人撮影 ',
    'anime':  '#エロアニメ #FANZA #アニメ好き ',
    'doujin': '#同人誌 #FANZA #エロ同人 ',
    'comic':  '#エロ漫画 #FANZA #電子書籍 ',
    'goods':  '#大人グッズ #FANZA ',
    'default': '#FANZA #アダルト動画 ',
}

# ジャンル別の追加ハッシュタグ（genre_tagsで使うジャンル名に加えて付与する）
# ※ 未成年を想起させる表現（JK/JC/ロリ/学生/制服/十代 等）に関連するジャンルは、
#   児童の性的対象化を助長しないという方針上、意図的にこのマップへ追加しない。
GENRE_EXTRA_HASHTAG_MAP = {
    '素人':     '#素人動画',
    '人妻':     '#人妻動画',
    '巨乳':     '#巨乳',
    '美乳':     '#美乳',
    '中出し':   '#中出し',
    '企画':     '#企画AV',
    '単体作品': '#単体女優',
    '熟女':     '#熟女好き',
    '若妻':     '#若妻',
    'OL':       '#OL好き',
    '女教師':   '#女教師',
    '痴女':     '#痴女好き',
    '巨尻':     '#巨尻',
    '美尻':     '#美尻',
    'ぽっちゃり': '#ぽっちゃり',
    'スレンダー': '#スレンダー美女',
    '3P・4P':   '#3P4P',
    '乱交':     '#乱交',
    '寝取り':   '#寝取り',
    '寝取られ': '#寝取られ',
    'NTR':      '#NTR',
    '拘束':     '#拘束プレイ',
    '露出':     '#露出プレイ',
    'コスプレ': '#コスプレエロ',
    'ナース':   '#ナース',
    '不倫':     '#不倫',
    'パイズリ': '#パイズリ',
    'フェラ':   '#フェラ',
    '手コキ':   '#手コキ',
    '潮吹き':   '#潮吹き',
}

COPY_TEMPLATES = [
    # ――― v3: 新規会員登録（サービス新規報酬）を狙ったコピーを追加 ―――
    # FANZAを使ったことがない人向けの「入口」として機能する文言を重視
    # 既存会員への購入訴求 + 未登録者への登録訴求 の両立を目指す
    # 【v8修正】サンプルは登録不要で見られるため、「登録しないとサンプルが見られない」
    # と誤解させる表現を避け、「登録不要で見られる」ことを明示する表現に統一

    # 【新規会員獲得重視】FANZA未登録者への訴求（サービス新規報酬につながる）
    "サンプルは登録なしで全部見られる。気になったらまず見てみるのがおすすめ",
    "FANZAって登録しなくてもこの手のサンプルが全作品見放題なの地味に神",
    "まだFANZA使ったことない人も、サンプルは登録なしで見られるから試してみる価値はある",
    "FANZAはサンプルなら登録不要で全部見られる。まずこのサンプルから確認してみて",

    # 【購入後押し型】既存会員向け
    "毎日FANZAチェックしてるけど、これクラスの作品は月に数本しか出ない。見逃すと後悔するやつ",
    "このクオリティでこの価格はさすがに安すぎる。FANZAの値付けがバグってると思う",
    "無料サンプルで十分と思ってたのに、本編が気になって結局ポチった。サンプルが罪すぎる",
    "レビュー評価見てから買ったけど、評価高いのには理由があった。納得の内容だった",
    "FANZAランキング上位をキープしてる理由がわかった。これは実際に見ると納得感がある",
    "サブスクにない作品だから単品購入したけど、それでも全然惜しくない出来だった",
    "FANZAって値段が変わることあるから、気になってるなら今のうちに確認しといたほうがいい",
    "映画1本分の値段で何度でも見返せるって考えたら、コスパ的にもアリだと思う",
    "缶ビール数本分の値段で今夜の時間を最高にできると思ったら安いもんだと思う",
    "動画配信サービス1ヶ月分より安い。それで手元に残るなら買わない理由がない",
    "迷ってる時間がもったいなかった。ポチってから「もっと早く買えばよかった」ってなった",
    "サンプル見て5分悩んで購入した。その5分が惜しかったくらい内容が良かった",

    # 【v5追加】「サンプルで満足→離脱」対策：続きが気になる“具体的な理由”を明示
    # サンプルはあくまで一部分であることと、続きを見る動機を言語化する
    "サンプルは核心の手前で終わる作りだった。気になる展開はそこから先にあるやつ",
    "無料サンプルに入ってる展開だけでも良かったのに、本編はその続きがずっと濃い",
    "サンプルで見れる範囲は全体のごく一部。気になった人は本編で答え合わせすると納得できる",

    # 【v6追加】ロス・アバージョン（損失回避バイアス）を意識した訴求
    # 「良い」ではなく「見ないと機会を逃す／後で気づいて損した気分になる」を言語化
    # 出典: https://studyhacker.net/whywebuy（機能訴求より「必要性の自覚」「損失回避」が購買行動を後押しする）
    "これクラスの作品を見逃して、後から気づいて悔しい思いをしたことが何度かある",
    "気になってるのに後回しにして、結局サンプルすら忘れて損した経験があるから今回は先に確認した",
    "こういうのはタイムラインで流れてくる一瞬で判断しないと、二度と辿り着けなくなることが多い",

    # 【v7追加】具体性・当事者性を強めた訴求（テンプレ感を薄め、レビューらしさを出す）
    "同じジャンルを結構見てきたけど、展開の作り込みが他とは体感で違った",
    "無料サンプルの時点で期待値がかなり上がった。本編まで見て裏切られなかったやつ",
    "レビューが伸びてる作品は当たりの確率が体感で全然違う。今回はまさにそのパターン",
    "サンプルだけ見て判断つかない人向けに言うと、本編は最初の展開がさらに続くタイプ",
]

# 【NTR特化】DMM_ARTICLE_IDがNTRジャンルの場合に通常のCOPY_TEMPLATESへ追加する専用コピー。
# 「寝取る側／寝取られる側どちらの心理も描けているか」「同意の上での関係性の変化」など、
# このジャンル特有の“ギャップ・緊張感・背徳感”を訴求軸にする。露骨な性描写ではなく、
# 作品の見どころ・引き込まれるポイントを言語化する方向で統一。
NTR_COPY_TEMPLATES = [
    "寝取られる側の心理描写がちゃんと丁寧なタイプ。ただ寝取るだけの雑な展開じゃないから引き込まれる",
    "見てる側の嫉妬心を煽ってくる作りが上手い。NTR系は結局この“揺さぶり方”で当たり外れが決まる",
    "最初は普通の関係だったのが少しずつ崩れていく過程が丁寧。一気に堕ちるタイプより刺さる人多いと思う",
    "寝取る側の余裕と、気づいていく側の焦りの対比がしっかり描かれてて没入感が違った",
    "NTRは背徳感の積み上げ方が命だと思ってるけど、これはその積み上げ方がうまい部類",
    "同じ寝取られ物でも、関係性の説明を端折らないタイプは満足度が高い。今回はまさにそれ",
    "罪悪感と快楽のバランスが極端じゃなくて、変にリアリティがあるから見入ってしまう",
    "寝取られ好きに刺さるポイントを分かってる作り。中途半端に匂わせて終わらないタイプ",
    "この手のジャンルは表情の演技力で差が出ると思ってるけど、そこがちゃんとしてた",
    "関係が壊れていく“過程”にちゃんと尺を使ってるから、結末までの説得力がある",
]


# ----------------------------------------------------------------
# ✨ おすすめポイント自動生成（DMM APIのデータから）
#    ジャンル・女優・メーカー・レビュー評価・価格などを組み合わせて、
#    商品ごとに違った訴求文を作る。固定文のランダム抽選より具体的になる。
# ----------------------------------------------------------------

_OPENERS = [
    "正直に購入した理由を言うと、",
    "迷ってる人に一言だけ言うと、",
    "お金を出す価値があると思った理由は、",
    "これを選んだ決め手は、",
]
_CLOSERS = [
    "まず無料サンプルだけ見て、気に入ったらそのまま購入できる👇",
    "サンプル確認 → 気に入ったらポチるだけ。損はしない構造になってる",
    "今の価格で買えるうちにリンクから確認してみて👇",
    "サンプルだけでも見てほしい。それで判断できると思う👇",
    # 【v6追加】ロス・アバージョン型クロージング（見送ることで損をする側面を意識させる）
    "見送ってスルーするより、サンプルだけでも確認しておいたほうが後悔しない👇",
    "気になってるなら、後回しにして忘れるより今リンクから見ておくのが吉👇",
]
_FALLBACK_PHRASES = [
    "手元に置いておきたくなる内容だった",
    "購入後に「早く買えばよかった」ってなったやつ",
    "これはレンタルじゃなくて買いだと思う",
]
_FILLER_PHRASES = [
    "無料サンプルで内容確認してから買えるから失敗しにくい",
    "購入者レビューの評価がかなり高くて安心感がある",
    "何度でも見返せるから単品購入でもコスパはいい",
    "FANZAは決済後すぐ視聴できるのが地味に助かる",
    "毎日チェックしてる中でも特に推せると思ったやつ",
]


def build_recommend_points(product, max_len=120):
    """商品データのうち、投稿文の他の行（ジャンルタグ・価格表示）と重複しない
    『レビュー評価・出演者・メーカー』を軸におすすめポイント文を作る。
    データ項目だけで max_len に届かない場合は、商品の事実とは無関係な汎用フレーズ
    （誇張や個別の内容を断定しないもの）を追加し、Xの文字数上限近くまで使い切る。
    """
    segments = []

    if product.get('review_avg'):
        avg = product['review_avg']
        count = product.get('review_count')
        if count and count >= 30:
            # 【v6】件数がまとまってある場合は「みんな見てる」社会的証明として明示する
            segments.append(f"レビュー{count}件が集まっていて平均{avg}の高評価")
        elif count:
            segments.append(f"レビュー平均{avg}（{count}件）の高評価")
        else:
            segments.append(f"レビュー評価{avg}の高評価")

    if product.get('actors'):
        as_ = '・'.join(product['actors'][:2])
        segments.append(f"出演は{as_}")

    if product.get('maker'):
        segments.append(f"{product['maker']}制作")

    if not segments:
        segments.append(random.choice(_FALLBACK_PHRASES))

    # 汎用フレーズをランダムな順で末尾に追加候補として用意しておく
    fillers = random.sample(_FILLER_PHRASES, len(_FILLER_PHRASES))
    segments.extend(fillers)

    opener = random.choice(_OPENERS)
    closer = random.choice(_CLOSERS)

    # 入る範囲までセグメントを「、」でつなげて、文字数上限を有効活用する
    # ※ max_len はX（Twitter）の「重み付き文字数」基準（x_text_length）で渡される。
    #    日本語・絵文字は1文字=2カウントなので、ここも len() ではなく
    #    x_text_length() で判定しないと、実際の上限の約2倍も詰め込んでしまう。
    body = ''
    for i, seg in enumerate(segments):
        sep = '' if i == 0 else '、'
        candidate = body + sep + seg
        # opener + candidate + '。' + closer が収まるかチェック
        if x_text_length(opener + candidate + '。' + closer) > max_len:
            continue  # この要素は入らないが、後続のもっと短い要素が入るかもしれないので継続
        body = candidate

    if not body:
        # 1要素も入らない場合は最低限の要約を切り詰めて表示
        return truncate_to_weighted_length(opener + segments[0], max_len)

    text = f"{opener}{body}。{closer}"
    if x_text_length(text) > max_len:
        text = truncate_to_weighted_length(text, max_len)
    return text


def truncate_to_weighted_length(text, max_len):
    """重み付き文字数（x_text_length）がmax_len以下になるよう、末尾に'…'を付けて切り詰める。"""
    if x_text_length(text + '…') <= max_len:
        return text + '…'
    # 1文字ずつ削りながら収まるところまで縮める
    truncated = text
    while truncated and x_text_length(truncated + '…') > max_len:
        truncated = truncated[:-1]
    return truncated + '…' if truncated else '…'


# ----------------------------------------------------------------
# 🔗 URL確認
#    投稿文生成のたびにアフィリエイトURL・サンプル動画URLへHTTPリクエストを送って
#    生死確認する機能。結果は保存されるテキストファイルの表示（OK/NG）にしか使われず、
#    投稿するかどうかの判定には影響しない。候補が多いと大量のHTTPリクエストが
#    直列で走り処理時間が大きく伸びるため、デフォルトは無効（スキップ）にしている。
#    ENABLE_URL_CHECK=true で有効化できる。
# ----------------------------------------------------------------
ENABLE_URL_CHECK = os.environ.get('ENABLE_URL_CHECK', 'false').strip().lower() in ('1', 'true', 'yes')


def check_url(url, timeout=8):
    """URLが実際にアクセス可能かHEADリクエストで確認する。結果はTrue/False/None(未確認)。"""
    if not url:
        return None
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True,
                              headers={'User-Agent': 'Mozilla/5.0'})
        if resp.status_code >= 400:
            # HEADを許可していないサーバーもあるためGETで再確認
            resp = requests.get(url, timeout=timeout, stream=True,
                                 headers={'User-Agent': 'Mozilla/5.0'})
        return resp.status_code < 400
    except Exception:
        return None


# ================================================================
# 🔧 DMM API 関数
# ================================================================

def fetch_dmm_products(sort_key, sort_label, offset=None, hits=None):
    service, floor_name = FLOOR_SERVICE_MAP.get(DMM_FLOOR, ('digital', 'videoa'))
    _offset = offset if offset is not None else DMM_OFFSET
    _hits   = hits   if hits   is not None else DMM_HITS
    params = {
        'api_id':       DMM_API_ID,
        'affiliate_id': DMM_AFFILIATE_ID,
        'site':         'FANZA',
        'service':      service,
        'floor':        floor_name,
        'hits':         _hits,
        'offset':       _offset,
        'sort':         sort_key,
        'output':       'json',
    }
    if GENRE_FILTER_ENABLED:
        params['article']    = DMM_ARTICLE
        params['article_id'] = DMM_ARTICLE_ID

    genre_label = f' / ジャンル特化: {DMM_ARTICLE}={DMM_ARTICLE_ID}' if GENRE_FILTER_ENABLED else ''
    print(f'\n  [{sort_label}] 取得範囲: {_offset}件目〜{_offset + _hits - 1}件目{genre_label}')

    for attempt in range(1, DMM_MAX_RETRIES + 1):
        try:
            resp = requests.get(f'{DMM_API_BASE}/ItemList', params=params, timeout=15)
            data = resp.json()
            result = data.get('result', {})

            # DMM APIがエラー応答を返した場合（レート制限・一時的な問い合わせ上限超過など）
            status = result.get('status')
            if status is not None and str(status) != '200':
                message = result.get('message') or data.get('message') or '不明なエラー'
                raise RuntimeError(f'DMM APIエラー応答 status={status} message={message}')

            items = result.get('items', [])
            if isinstance(items, dict):
                items = items.get('item', [])
            if items:
                url_str = items[0].get('affiliateURL', '')
                print(f"  URLの総文字数: {len(url_str)} / 末尾10文字: {url_str[-10:]}")
            print(f'  ✅ {len(items)} 件取得しました。')
            return items
        except Exception as e:
            if attempt >= DMM_MAX_RETRIES:
                print(f'  ❌ DMM APIエラー（{attempt}/{DMM_MAX_RETRIES}回でリトライ上限に到達）: {e}')
                return []
            wait_sec = DMM_RETRY_WAIT_SEC * attempt  # 試行のたびに待機時間を延ばす（簡易バックオフ）
            print(f'  ⚠️  DMM APIエラー（{attempt}/{DMM_MAX_RETRIES}回目）: {e}')
            print(f'  ⏳ {wait_sec:.1f}秒待機してリトライします...')
            time.sleep(wait_sec)

    return []


def parse_product(item):
    title         = item.get('title', '')
    affiliate_url = item.get('affiliateURL', '') or item.get('URL', '')
    prices        = item.get('prices', {})
    price_str     = ''
    price_num     = None
    if prices:
        price_val = prices.get('price') or prices.get('list_price') or ''
        if price_val:
            digits = ''.join(c for c in str(price_val) if c.isdigit())
            if digits:
                price_num = int(digits)
                price_str = f'\u00a5{price_num:,}'
    actors = [a.get('name', '') for a in (item.get('iteminfo', {}).get('actress') or [])][:3]
    # 【表示除外】「ハイビジョン」「無料サンプルあり」はジャンルタグとして意味が薄いため非表示にする
    EXCLUDED_GENRES = {'ハイビジョン', '無料サンプルあり'}
    genres = [
        g.get('name', '')
        for g in (item.get('iteminfo', {}).get('genre') or [])
        if g.get('name', '') not in EXCLUDED_GENRES
    ][:3]
    maker  = ((item.get('iteminfo', {}).get('maker') or [{}])[0]).get('name', '')

    sample_movie_url = ''
    smv = item.get('sampleMovieURL', {})
    if smv:
        for key in ['size_720_480', 'size_644_414', 'size_560_360', 'size_476_306']:
            val = smv.get(key, '')
            if val:
                sample_movie_url = val.strip()
                break

    content_id = item.get('content_id', '') or item.get('product_id', '')

    # レビュー情報（平均評価・件数）。商品によっては存在しない。
    review_info  = item.get('review', {}) or {}
    review_avg   = review_info.get('average', '')
    review_count = review_info.get('count', '')
    try:
        review_avg = float(review_avg) if review_avg not in ('', None) else None
    except (TypeError, ValueError):
        review_avg = None
    try:
        review_count = int(review_count) if review_count not in ('', None) else None
    except (TypeError, ValueError):
        review_count = None

    # 配信開始日（新着訴求に使う）
    date_str = item.get('date', '')

    return {
        'title':            title,
        'affiliate_url':    affiliate_url,
        'price':            price_str,
        'price_num':        price_num,
        'actors':           actors,
        'genres':           genres,
        'maker':            maker,
        'sample_movie_url': sample_movie_url,
        'content_id':       content_id,
        'review_avg':       review_avg,
        'review_count':     review_count,
        'date':             date_str,
    }


def is_vr_product(item):
    """【VR】作品かどうかを判定する（VRゴーグル専用のため通常投稿には向かないものを除外する）。
    ジャンル名に「VR」が含まれる、またはタイトルに「VR」を含む表記（【VR】等）がある場合にTrueを返す。"""
    genres_raw = [g.get('name', '') for g in (item.get('iteminfo', {}).get('genre') or [])]
    if any('VR' in g.upper() for g in genres_raw):
        return True
    title = item.get('title', '') or ''
    if re.search(r'VR', title, re.IGNORECASE):
        return True
    return False


def product_date_sort_key(product):
    """商品の配信日を降順ソート用のキーに変換する。日付が無い商品は最も古い扱いにする。
    DMM APIの date は 'YYYY-MM-DD HH:MM:SS' 形式なのでそのまま文字列比較で新しい順に並ぶ。"""
    return product.get('date') or ''


def is_future_release(product):
    """配信日が実行時点より未来（予約商品・販売開始前など）かどうかを判定する。
    date が無い場合は「未来ではない」として扱う（除外しない）。"""
    date_str = (product.get('date') or '').strip()
    if not date_str:
        return False
    try:
        # 'YYYY-MM-DD HH:MM:SS' 形式のほか、時刻部分が無い 'YYYY-MM-DD' 形式にも対応
        fmt = '%Y-%m-%d %H:%M:%S' if len(date_str) > 10 else '%Y-%m-%d'
        dt = datetime.datetime.strptime(date_str, fmt)
        return dt > datetime.datetime.now()
    except ValueError:
        return False


def is_recent_release(product, days=3):
    """配信日が直近days日以内かどうかを判定する（実データに基づく『なぜ今か』の根拠に使う）。
    架空のセール期限などは訴求せず、確実に真実である『新着』のみを鮮度訴求の材料にする。"""
    date_str = (product.get('date') or '')[:10]
    if not date_str:
        return False
    try:
        dt = datetime.datetime.strptime(date_str, '%Y-%m-%d')
        return (datetime.datetime.now() - dt).days <= days
    except ValueError:
        return False

def clean_url(url):
    if not url:
        return ''
    url = url.strip().replace('\n', '').replace('\r', '').replace('　', '')
    if not url.startswith('http'):
        return ''
    return url


def actor_tags(actors):
    return '　'.join('#' + a.replace(' ', '').replace('　', '') for a in actors if a)


def genre_tags(genres):
    """ジャンル名（人妻・主婦、巨乳など）をハッシュタグ形式に変換する。"""
    return '　'.join('#' + g.replace(' ', '').replace('　', '') for g in genres if g)


# ハッシュタグとして使わないジャンル名（投稿文には不要なため除外する）
EXCLUDED_HASHTAG_GENRES = {'4K', '独占配信'}


def filter_hashtag_genres(genres):
    """ハッシュタグ化する前に、不要なジャンル名（#4K・#独占配信）を取り除く。"""
    return [g for g in genres if g not in EXCLUDED_HASHTAG_GENRES]


def prioritize_genres(genres):
    """GENRE_EXTRA_HASHTAG_MAPに対応する拡張タグを持つジャンルを先頭側へ寄せる。

    文字数制限でgenre_limit件に絞られる際、拡張タグ（＝検索されやすい定番ワード）を
    持つジャンルが優先的に残るようにするための並べ替え。各グループ内の相対順序は保持する。"""
    with_extra = [g for g in genres if g in GENRE_EXTRA_HASHTAG_MAP]
    without_extra = [g for g in genres if g not in GENRE_EXTRA_HASHTAG_MAP]
    return with_extra + without_extra


def dedupe_hashtag_line(line):
    """全角スペース区切りのハッシュタグ文字列から重複タグを除去する（最初の出現を優先して残す）。"""
    seen = set()
    parts = []
    for tag in line.split('　'):
        if not tag:
            continue
        if tag not in seen:
            seen.add(tag)
            parts.append(tag)
    return '　'.join(parts)


def price_in_range(product):
    """価格フィルターが設定されている場合、商品の価格が範囲内かどうかを判定する。"""
    if not PRICE_RANGE_BOUNDS:
        return True
    price_num = product.get('price_num')
    if price_num is None:
        return False
    price_min, price_max = PRICE_RANGE_BOUNDS
    if price_num < price_min:
        return False
    if price_max is not None and price_num > price_max:
        return False
    return True


# ----------------------------------------------------------------
# 📏 X（Twitter）の文字数カウント
#    旧実装は len(text) をそのまま使っていたが、これはバグだった。
#    Xは公式の重み付きカウント方式（twitter-text）を採用しており、
#    日本語・絵文字・全角記号などは「2文字分」としてカウントされる。
#    例えば見た目140文字の日本語投稿でも、Xの実カウントでは280文字相当となり
#    上限ギリギリ〜超過になる。これを反映しないと
#    「上限内のはずなのに実際は超過していた」事象が起きる。
#
#    重み付けルール（X公式 twitter-text の config を反映）:
#      - 半角英数字・一般的な記号など（コードポイント 0-4351、
#        および一部の句読点範囲）は 1文字としてカウント
#      - それ以外（ひらがな・カタカナ・漢字・絵文字・全角記号など）は
#        2文字としてカウント
#      - URL（http/https〜）は実際の文字数に関わらず、Xが自動でt.co形式に
#        短縮するため「23文字」固定としてカウント
# ----------------------------------------------------------------

# 1文字としてカウントする（重み1）コードポイント範囲
_X_LOW_WEIGHT_RANGES = [
    (0, 4351),       # 基本ラテン文字、各種記号、ギリシャ文字、キリル文字 など
    (8192, 8205),    # 一般句読点（スペース類）
    (8208, 8223),    # 一般句読点（ハイフン・ダッシュ類）
    (8242, 8247),    # プライム記号など
]

_X_URL_PATTERN = re.compile(r'https?://\S+')


def _x_char_weight(ch):
    """1文字あたりの重みを返す（半角=1、それ以外（CJK・絵文字等）=2）。"""
    cp = ord(ch)
    for lo, hi in _X_LOW_WEIGHT_RANGES:
        if lo <= cp <= hi:
            return 1
    return 2


def x_text_length(text):
    """X（Twitter）公式の重み付き文字数カウントを再現する。

    - URLはt.co短縮を見込んで23文字固定で計算
    - それ以外は文字ごとに重み（半角=1、日本語・絵文字等=2）を合計
    """
    urls = _X_URL_PATTERN.findall(text)
    text_without_urls = _X_URL_PATTERN.sub('', text)

    weighted = sum(_x_char_weight(c) for c in text_without_urls)
    weighted += len(urls) * 23

    return weighted


def build_x_single_post(product, char_limit=280):
    """1ポストで完結する投稿文を「作品名・値段・出演者・アフィリエイトURL・ハッシュタグ・
    NTR作品の概要」の6要素だけで組み立てる。見出し・CTA・一言コメントは含めない。

    文字数が厳しい場合に削る優先順位（上ほど先に削る）:
      1. NTR作品の概要（コピー文）
      2. 汎用ハッシュタグ（#アダルト動画 等）※ 
      3. タイトルの表示文字数
      4. 出演者タグを3名→1名に
      5. ジャンル・性癖系ハッシュタグを1件に
    金額・出演者最低1名・アフィリエイトURL・#PRは常に含む。
    """
    hashtags = HASHTAG_MAP.get(DMM_FLOOR, HASHTAG_MAP['default'])
    # 広告表記として必須の #FANZA も必ず残す最小構成
    minimal_disclosure_tags = '#FANZA '
    url = clean_url(product['affiliate_url'])
    sample_full = clean_url(product.get('sample_movie_url', ''))

    url_ok = check_url(url) if (url and ENABLE_URL_CHECK) else None
    if url and url_ok is False:
        print(f"    ⚠️  アフィリエイトURLにアクセスできませんでした: {url}")
    product['url_check'] = url_ok
    product['sample_check'] = check_url(sample_full) if (sample_full and ENABLE_URL_CHECK) else None

    title = product['title']

    def title_line(limit):
        t = (title[:limit] + '…') if len(title) > limit else title
        return f"📽 {t}"

    def genre_tag_line(genre_limit):
        genres = prioritize_genres(filter_hashtag_genres(product['genres']))[:genre_limit] if genre_limit else []
        filtered = filter_hashtag_genres(genres)
        parts = []
        gt = genre_tags(filtered)
        if gt:
            parts.append(gt)
        extras = [GENRE_EXTRA_HASHTAG_MAP[g] for g in filtered if g in GENRE_EXTRA_HASHTAG_MAP]
        if extras:
            parts.append('　'.join(extras))
        return dedupe_hashtag_line('　'.join(parts))

    # NTR作品の概要（NTR系ジャンルの場合はNTR特化の概要テンプレ、それ以外は汎用テンプレ）
    overview = random.choice(NTR_COPY_TEMPLATES if IS_NTR_FOCUSED else COPY_TEMPLATES)

    # 【bot感対策】毎回同じ絵文字にならないようランダムに選ぶ
    PRICE_EMOJIS = ['💰', '🪙']
    ACTOR_EMOJIS = ['👤', '🎭']
    price_emoji = random.choice(PRICE_EMOJIS)
    actor_emoji = random.choice(ACTOR_EMOJIS)

    def price_line():
        return f"{price_emoji} {product['price']}" if product.get('price') else None

    def assemble(title_limit, actor_limit, genre_limit, base_tags, include_overview, overview_text):
        actors = product['actors'][:actor_limit] if actor_limit else []
        act_tags = actor_tags(actors)

        lines = [title_line(title_limit)]
        if include_overview and overview_text:
            lines.append(f"📝 {overview_text}")
        p_line = price_line()
        if p_line:
            lines.append(p_line)
        if act_tags:
            lines.append(f"{actor_emoji} {act_tags}")

        g_line = genre_tag_line(genre_limit)
        tag_line = dedupe_hashtag_line('　'.join(t for t in [g_line, base_tags] if t))

        return '\n\n'.join(['\n'.join(lines), url, tag_line])

    # --- 段階的に情報量を落として文字数に収める ---
    title_limit = 35
    base_tags = hashtags
    actor_limit = 3
    genre_limit = 3
    include_overview = True

    text = assemble(title_limit, actor_limit, genre_limit, base_tags, include_overview, overview)

    if x_text_length(text) > char_limit:
        # 1) 概要を切り詰める
        over = x_text_length(text) - char_limit
        overview = truncate_to_weighted_length(overview, max(10, x_text_length(overview) - over))
        text = assemble(title_limit, actor_limit, genre_limit, base_tags, include_overview, overview)

    if x_text_length(text) > char_limit:
        # 2) 汎用ハッシュタグを最小限（#FANZAのみ）にする
        base_tags = minimal_disclosure_tags
        text = assemble(title_limit, actor_limit, genre_limit, base_tags, include_overview, overview)

    if x_text_length(text) > char_limit:
        # 3) 概要を丸ごと外す
        include_overview = False
        text = assemble(title_limit, actor_limit, genre_limit, base_tags, include_overview, overview)

    if x_text_length(text) > char_limit:
        # 4) タイトルの表示文字数を縮める
        title_limit = 20
        text = assemble(title_limit, actor_limit, genre_limit, base_tags, include_overview, overview)

    if x_text_length(text) > char_limit:
        # 5) 出演者タグを3名→1名に絞る
        actor_limit = 1
        text = assemble(title_limit, actor_limit, genre_limit, base_tags, include_overview, overview)

    if x_text_length(text) > char_limit:
        # 6) ジャンル・性癖系タグを3件→1件に絞る
        genre_limit = 1
        text = assemble(title_limit, actor_limit, genre_limit, base_tags, include_overview, overview)

    if x_text_length(text) > char_limit:
        # 7) 最終手段：タイトルの表示文字数をさらに縮める
        over = x_text_length(text) - char_limit
        title_limit = max(5, title_limit - over)
        text = assemble(title_limit, actor_limit, genre_limit, base_tags, include_overview, overview)

    assert x_text_length(text) <= char_limit, (
        f"⚠️ 投稿文字数超過: {x_text_length(text)} > {char_limit}\n{text}"
    )

    # 今回は1ツイートで完結するため、スレッド分割は行わない（reply側は空）
    product['_thread_main'] = text
    product['_thread_reply'] = ''

    return text


# ================================================================
# 🎬 サンプル動画URLの解決（Buffer投稿で使用）
# ================================================================

_SAMPLE_HTTP_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://www.dmm.co.jp/',
}
# DMM/FANZAは年齢確認を済ませていないとサンプル動画ページが
# 年齢確認画面にリダイレクトされ、動画情報が一切含まれなくなる。
_SAMPLE_HTTP_COOKIES = {
    'age_check_done': '1',
}


def _clean_content_id(content_id):
    return re.sub(r'[^0-9a-zA-Z]', '', content_id or '')


def build_direct_cdn_candidates(content_id):
    """
    content_id から、FANZA動画でよく使われる直リンクの命名規則を組み立てる。
    例: https://cc3001.dmm.co.jp/litevideo/freepv/r/rb/rbd00185/rbd00185_mhb_w.mp4
    実在しない場合もあるため、複数パターン・複数サフィックスを候補として返す。
    """
    cid = _clean_content_id(content_id)
    if not cid:
        return []

    suffixes = ['mhb_w', 'dmb_w', 'sm_w', 'mhb_s', 'dmb_s', 'sm_s']
    hosts = ['cc3001.dmm.co.jp', 'cc3001.dmm.com']
    candidates = []
    for host in hosts:
        for suf in suffixes:
            candidates.append(
                f'https://{host}/litevideo/freepv/{cid[0]}/{cid[0:3]}/{cid}/{cid}_{suf}.mp4'
            )
    return candidates


def resolve_litevideo_mp4_url(page_url, content_id=''):
    """
    DMM/FANZAの 'litevideo' URL (.../litevideo/-/part/=/cid=.../size=.../)は
    動画ファイルそのものではなく、プレイヤーを埋め込んだHTMLページのURL。
    1. まずcontent_idから直リンクの命名規則を推測して存在確認（速くて確実）
    2. ダメならHTMLページを取得して中から実際の.mp4 URLを抜き出す
    既に.mp4で終わるURLが渡された場合はそのまま返す。
    """
    if not page_url:
        return ''
    if page_url.lower().endswith('.mp4'):
        return page_url

    # --- 方式1: 命名規則からの直接推測 ---
    for cand in build_direct_cdn_candidates(content_id):
        try:
            r = requests.head(
                cand, timeout=8, allow_redirects=True,
                headers=_SAMPLE_HTTP_HEADERS, cookies=_SAMPLE_HTTP_COOKIES,
            )
            if r.status_code == 200 and int(r.headers.get('Content-Length', '0') or 0) > 10000:
                return cand
        except Exception:
            continue

    # --- 方式2: litevideoページをスクレイピングして中の.mp4 URLを抜く ---
    try:
        resp = requests.get(
            page_url, timeout=15,
            headers=_SAMPLE_HTTP_HEADERS, cookies=_SAMPLE_HTTP_COOKIES,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f'  ❌ litevideoページの取得に失敗: {e}')
        return ''

    # JSON内などでは "https:\/\/..." のようにスラッシュがエスケープされているため、
    # 正規表現にかける前に元に戻しておく。
    body = resp.text.replace('\\/', '/')
    candidates = re.findall(r'https?://[^\s\'"<>]+\.mp4', body)
    if not candidates:
        # 【診断ログ】原因切り分け用。年齢確認ページに飛ばされているのか、
        # ページ構造が変わって.mp4が見つからないだけなのかを判別する。
        final_url = resp.url
        looks_age_gate = (
            'age_check' in final_url
            or 'age_check' in body[:3000]
            or '18歳未満' in body[:3000]
            or '年齢確認' in body[:3000]
        )
        print(
            '  ⚠️  litevideoページ内に.mp4のURLが見つかりませんでした。'
            f'[診断] status={resp.status_code} 最終URL={final_url} '
            f'年齢確認ページの可能性={"あり" if looks_age_gate else "なし"} '
            f'本文冒頭300字={body[:300]!r}'
        )
        return ''
    return candidates[0]
# ================================================================
# 🎬 サンプル動画クリップ生成（シャドウバン対策）
# ================================================================
#
# 外部の実例調査により、DMMのサンプル動画（本編に近い過激なシーンを含む）を
# そのままXに投稿すると、シャドウバン（インプレッションが伸びなくなる）の
# リスクが高いことが分かっている。対策として、サンプル動画の冒頭など
# 比較的おだやかな数秒だけを切り出して投稿する。
#
# 切り出した動画はBufferに「公開URL」として渡す必要があるため、
# GitHubリポジトリ（outputs/clips/配下）にコミット＆pushし、
# raw.githubusercontent.com のURLを利用する。
# ⚠️ 前提: このリポジトリは public であること（raw.githubusercontent.com は
#    publicリポジトリでないと外部からアクセスできない）。
# ⚠️ アダルト系動画ファイルをGitHubリポジトリに保存することは、
#    GitHubの利用規約（Acceptable Use Policies）に抵触するリスクがある。
#    ユーザー側でリスクを許容した上での運用を前提とする。

ENABLE_VIDEO_CLIP  = os.environ.get('ENABLE_VIDEO_CLIP', 'true').strip().lower() == 'true'
CLIP_START_SEC     = float(os.environ.get('CLIP_START_SEC', '0'))
CLIP_DURATION_SEC  = float(os.environ.get('CLIP_DURATION_SEC', '6'))
# push後、raw.githubusercontent.com に反映されるまでの猶予（CDN伝播待ち・要調整）
CLIP_PUSH_WAIT_SEC = float(os.environ.get('CLIP_PUSH_WAIT_SEC', '15'))
CLIP_DIR           = 'outputs/clips'

# 【重要】DMMのサンプル動画CDN・litevideoページは、日本国内IP以外からのアクセスを
# ブロックしている（GitHub Actions等の海外サーバーからは special.dmm.co.jp の
# 地域制限ページにリダイレクトされ、常に取得失敗する）。
# 日本国内IPのプロキシ／セルフホストランナーを用意していない場合は、
# ENABLE_SAMPLE_VIDEO=false のままにして、動画取得を試みず最初からリンクのみの
# 投稿にする（無駄なリクエスト・待ち時間・ログを削減する）。
ENABLE_SAMPLE_VIDEO = os.environ.get('ENABLE_SAMPLE_VIDEO', 'false').strip().lower() == 'true'


def _download_file(url, dest_path, timeout=30):
    try:
        with requests.get(
            url, stream=True, timeout=timeout,
            headers=_SAMPLE_HTTP_HEADERS, cookies=_SAMPLE_HTTP_COOKIES,
        ) as r:
            r.raise_for_status()
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        return True
    except Exception as e:
        print(f'  ❌ 動画のダウンロードに失敗: {e}')
        return False


def _run_ffmpeg_clip(src_path, dest_path, start_sec, duration_sec):
    """ffmpegで src_path の [start_sec, start_sec+duration_sec) を切り出す。
    まず高速な -c copy（再エンコードなし）を試し、失敗したら再エンコードにフォールバック。"""
    base_cmd = ['ffmpeg', '-y', '-ss', str(start_sec), '-i', src_path, '-t', str(duration_sec)]

    # 1) 再エンコードなし（速いがキーフレーム境界に丸められるため多少ズレることがある）
    try:
        result = subprocess.run(
            base_cmd + ['-c', 'copy', dest_path],
            capture_output=True, timeout=60,
        )
        if result.returncode == 0 and os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
            return True
    except Exception as e:
        print(f'  ⚠️  ffmpeg(-c copy)に失敗: {e}')

    # 2) 再エンコード（確実だが遅い）
    try:
        result = subprocess.run(
            base_cmd + ['-c:v', 'libx264', '-c:a', 'aac', '-preset', 'veryfast', dest_path],
            capture_output=True, timeout=120,
        )
        if result.returncode == 0 and os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
            return True
        print(f'  ❌ ffmpeg再エンコードに失敗: {result.stderr.decode(errors="ignore")[-500:]}')
    except Exception as e:
        print(f'  ❌ ffmpeg実行エラー: {e}')

    return False


def _git(*args, timeout=30):
    result = subprocess.run(['git'] + list(args), capture_output=True, timeout=timeout)
    return result.returncode == 0, result.stdout.decode(errors='ignore') + result.stderr.decode(errors='ignore')


def _push_clip_and_get_raw_url(local_clip_path, content_id):
    """クリップをリポジトリにコミット＆pushし、raw.githubusercontent.com のURLを返す。
    失敗時はNoneを返す。"""
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    branch = os.environ.get('GITHUB_REF_NAME', 'main')
    if not repo:
        print('  ⚠️  GITHUB_REPOSITORY が取得できないため、クリップのpushをスキップします。')
        return None

    ok, msg = _git('add', local_clip_path)
    if not ok:
        print(f'  ❌ git add 失敗: {msg}')
        return None

    ok, msg = _git('commit', '-m', f'🎬 sample clip: {content_id}')
    if not ok and 'nothing to commit' not in msg.lower():
        print(f'  ❌ git commit 失敗: {msg}')
        return None

    ok, msg = _git('push')
    if not ok:
        print(f'  ❌ git push 失敗: {msg}')
        return None

    if CLIP_PUSH_WAIT_SEC > 0:
        time.sleep(CLIP_PUSH_WAIT_SEC)

    return f'https://raw.githubusercontent.com/{repo}/{branch}/{local_clip_path}'


def build_sample_clip_url(sample_page_url, content_id, mp4_url=None):
    """サンプル動画から冒頭の数秒（CLIP_START_SEC 〜 +CLIP_DURATION_SEC）を切り出し、
    GitHubにpushしてraw URLを返す。どこかの工程で失敗したらNoneを返す
    （呼び出し側で「クリップなし」や「フル動画」へのフォールバックを行うこと）。
    mp4_url をあらかじめ渡した場合は、resolve_litevideo_mp4_url の再呼び出しを省略する
    （呼び出し側で既に解決済みの場合の二重リクエスト防止）。"""
    if not ENABLE_VIDEO_CLIP:
        return None

    if not mp4_url:
        mp4_url = resolve_litevideo_mp4_url(sample_page_url, content_id)
    if not mp4_url:
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = os.path.join(tmpdir, 'source.mp4')
        if not _download_file(mp4_url, src_path):
            return None

        cid = _clean_content_id(content_id) or 'clip'
        Path(CLIP_DIR).mkdir(parents=True, exist_ok=True)
        dest_path = f'{CLIP_DIR}/{cid}.mp4'

        if not _run_ffmpeg_clip(src_path, dest_path, CLIP_START_SEC, CLIP_DURATION_SEC):
            return None

    raw_url = _push_clip_and_get_raw_url(dest_path, cid)
    if raw_url:
        print(f'  ✅ サンプルクリップを生成・push しました: {raw_url}')
    return raw_url



#
# Bufferは2026年よりFreeプランでもGraphQL APIが利用可能（Personal API Key方式）。
# X公式APIの投稿課金は発生しないが、レート制限（15分100件・24時間100件・30日3000件／Free）
# がある点と、Buffer自体の利用規約・アダルトコンテンツに関するポリシーは別途確認が必要。
#
# 動画は「ファイルアップロード」ではなく「公開URLを渡す」方式のため、DMMのサンプル動画の
# 直リンクURL（resolve_litevideo_mp4_url）をそのままBufferに渡す。Buffer側のサーバーが
# そのURLに正常にアクセスできない場合（年齢確認Cookie等でブロックされた場合）は、
# 動画なしのテキストのみのスレッド投稿にフォールバックする。

BUFFER_API_ENDPOINT = 'https://api.buffer.com'

_BUFFER_CREATE_POST_MUTATION = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess {
      post {
        id
        status
        dueAt
      }
    }
    ... on MutationError {
      message
    }
  }
}
"""


def buffer_graphql_request(query, variables=None, timeout=30):
    """Buffer GraphQL APIへリクエストを送る。戻り値は (data, error_message)。"""
    try:
        resp = requests.post(
            BUFFER_API_ENDPOINT,
            json={'query': query, 'variables': variables or {}},
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {BUFFER_API_KEY}',
            },
            timeout=timeout,
        )
        data = resp.json()
    except Exception as e:
        return None, f'通信エラー: {e}'

    if data.get('errors'):
        messages = '; '.join(err.get('message', str(err)) for err in data['errors'])
        return None, messages

    return data.get('data'), None


def _compute_optimal_due_at(post_index, interval_min):
    """反応が良いとされる時間帯（OPTIMAL_TIME_WINDOWS・現地時間基準）の枠に
    post_index番目の投稿を割り当て、UTCのdatetimeを返す。

    枠内はinterval_min間隔で候補時刻を敷き詰め、枠が埋まったら次の枠（翌日にまたがる場合も含む）
    へ送る。過去の時刻は候補から除外する。"""
    local_now = datetime.datetime.utcnow() + datetime.timedelta(hours=BUFFER_TIMEZONE_OFFSET_HOURS)
    slots = []
    day_offset = 0
    while len(slots) <= post_index and day_offset <= 14:  # 安全弁：最大2週間先まで
        base_day = local_now.date() + datetime.timedelta(days=day_offset)
        for start_h, end_h in OPTIMAL_TIME_WINDOWS:
            window_start = datetime.datetime.combine(base_day, datetime.time(hour=start_h))
            window_end = datetime.datetime.combine(base_day, datetime.time(hour=end_h))
            t = window_start
            while t <= window_end:
                if t > local_now:
                    slots.append(t)
                t += datetime.timedelta(minutes=interval_min)
        day_offset += 1

    if not slots:
        # 万一枠が計算できなかった場合は従来方式（一定間隔）にフォールバック
        return datetime.datetime.utcnow() + datetime.timedelta(
            minutes=BUFFER_INITIAL_DELAY_MIN + post_index * interval_min
        )

    local_due = slots[min(post_index, len(slots) - 1)]
    return local_due - datetime.timedelta(hours=BUFFER_TIMEZONE_OFFSET_HOURS)


def buffer_create_single_post(post_text, video_url=None, post_index=0, reply_text=None):
    """BufferのcreatePostで投稿を作成する。
    reply_text を渡した場合は、Buffer側のスレッド機能（metadata.twitter.thread）を
    2要素で使い、「1件目＝本文＋動画（URLなし）」「2件目＝リプライでURL＋タグ」の
    スレッド投稿にする（Xは本文に外部リンクがあると表示が抑制されやすいための対策）。
    reply_text 未指定時は従来通り1件のみの投稿。
    成功時 (True, None)、失敗時 (False, エラー文言)。"""
    item = {'text': post_text}
    if video_url:
        item['assets'] = [{'video': {'url': video_url}}]

    thread = [item]
    if reply_text:
        thread.append({'text': reply_text})

    input_obj = {
        'text': post_text,
        'channelId': BUFFER_CHANNEL_ID,
        'schedulingType': 'automatic',
        'metadata': {'twitter': {'thread': thread}},
    }

    if BUFFER_SCHEDULING_MODE == 'addToQueue':
        input_obj['mode'] = 'addToQueue'
    else:
        if BUFFER_SCHEDULE_STRATEGY == 'optimal_hours':
            due_at = _compute_optimal_due_at(post_index, BUFFER_POST_INTERVAL_MIN)
        else:
            due_at = datetime.datetime.utcnow() + datetime.timedelta(
                minutes=BUFFER_INITIAL_DELAY_MIN + post_index * BUFFER_POST_INTERVAL_MIN
            )
        input_obj['mode'] = 'customScheduled'
        input_obj['dueAt'] = due_at.strftime('%Y-%m-%dT%H:%M:%S.000Z')

    data, err = buffer_graphql_request(_BUFFER_CREATE_POST_MUTATION, {'input': input_obj})
    if err:
        return False, err

    result = (data or {}).get('createPost') or {}
    if result.get('message'):  # MutationError
        return False, result['message']
    if result.get('post'):
        due = result['post'].get('dueAt', '')
        print(f'  📅 Buffer予約日時: {due}' if due else '  📅 Bufferのキューに追加しました')
        return True, None

    return False, '不明なエラー（createPostの応答にpostが含まれません）'


def post_to_x_buffer(product, post_text, post_index=0):
    """【Buffer方式】BufferのAPIで投稿を作成する。
    本文にはURLを含めず（Xの表示抑制対策）、URL＋タグはリプライ（スレッド2件目）に回す。
    優先順位: ①シャドウバン対策済みの短いクリップ（冒頭数秒）
              ②クリップ生成に失敗した場合はサンプル動画をフル添付（従来動作）
              ③どちらも失敗した場合は動画なし（リンクのみ）"""
    sample_url = clean_url(product.get('sample_movie_url', ''))
    content_id = product.get('content_id', '')

    # build_x_single_postで分割済みの「本文（URLなし）」「リプライ（URL＋タグ）」を使う。
    # 何らかの理由で分割情報がない場合は、従来通り1件のみの投稿にフォールバックする。
    main_text = product.get('_thread_main') or post_text
    reply_text = product.get('_thread_reply') or None

    # mp4_url の解決は1回だけ行い、クリップ生成とフル動画フォールバックの両方で使い回す
    # （以前はそれぞれが個別に解決していたため、失敗時の警告ログが二重に出ていた）
    # 【地域制限対応】ENABLE_SAMPLE_VIDEO=false（デフォルト）の場合は、
    # DMMの地域制限で常に失敗することが分かっているため、そもそも試行しない。
    mp4_url = ''
    if ENABLE_SAMPLE_VIDEO and sample_url:
        mp4_url = resolve_litevideo_mp4_url(sample_url, content_id)

    clip_url = ''
    if mp4_url:
        try:
            clip_url = build_sample_clip_url(sample_url, content_id, mp4_url=mp4_url) or ''
        except Exception as e:
            print(f'  ⚠️  クリップ生成中にエラー: {e}')

    if clip_url:
        ok, err = buffer_create_single_post(main_text, video_url=clip_url, post_index=post_index, reply_text=reply_text)
        if ok:
            print('  ✅ Buffer経由で短いサンプルクリップ付き投稿を作成しました（URLはリプライ側）')
            return True
        print(f'  ⚠️  クリップ付き投稿に失敗（{err}）。フル動画にフォールバックします。')

    if mp4_url:
        ok, err = buffer_create_single_post(main_text, video_url=mp4_url, post_index=post_index, reply_text=reply_text)
        if ok:
            print('  ✅ Buffer経由で動画付き投稿を作成しました（フル動画・URLはリプライ側）')
            return True
        print(f'  ⚠️  動画付き投稿に失敗（{err}）。動画なしの投稿にフォールバックします。')

    ok, err = buffer_create_single_post(main_text, video_url=None, post_index=post_index, reply_text=reply_text)
    if ok:
        print('  ✅ Buffer経由で投稿を作成しました（動画なし・URLはリプライ側）')
        return True

    print(f'  ❌ Buffer投稿失敗: {err}')
    return False



# ================================================================
# 💾 保存先を決定
# ================================================================

def get_history_file():
    """過去に生成済みの品番（content_id）を記録するJSONファイルのパスを返す。
    HISTORY_FILE環境変数で明示指定可能。未指定時は保存先フォルダ（get_save_dirと同じ場所）に置く。
    """
    explicit = os.environ.get('HISTORY_FILE', '').strip()
    if explicit:
        return explicit
    return os.path.join(get_save_dir(), 'dmm_posted_history.json')


def load_posted_history():
    """過去に生成済みの品番一覧を読み込む。ファイルがなければ空集合を返す。"""
    path = get_history_file()
    if not os.path.exists(path):
        return set()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return set(data)
        if isinstance(data, dict):
            return set(data.get('content_ids', []))
    except Exception as e:
        print(f'⚠️  履歴ファイルの読み込みに失敗しました（{path}）: {e}')
    return set()


def save_posted_history(content_ids):
    """品番一覧を履歴ファイルに保存する（既存の履歴に追記）。"""
    path = get_history_file()
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(sorted(content_ids), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'⚠️  履歴ファイルの保存に失敗しました（{path}）: {e}')


def get_save_dir():
    """
    保存先の優先順位:
    1. 環境変数 SAVE_DIR で明示指定されたパス
    2. GitHub Actions 環境 (SAVE_TO_REPO=true) → カレントディレクトリ（後でoutputsへ移動）
    3. デスクトップ（ローカル実行時）
       - ~/Desktop
       - ~/OneDrive/Desktop
       - ~/OneDrive/デスクトップ
       - ~/デスクトップ
    4. カレントディレクトリ（フォールバック）
    """
    # 環境変数で明示指定
    explicit = os.environ.get('SAVE_DIR', '').strip()
    if explicit:
        Path(explicit).mkdir(parents=True, exist_ok=True)
        return explicit

    # GitHub Actions上での実行（outputs/フォルダに保存）
    if os.environ.get('SAVE_TO_REPO', '').lower() == 'true':
        out = Path('outputs')
        out.mkdir(exist_ok=True)
        return str(out)

    # ローカル実行時はデスクトップを探す
    try:
        home = Path.home()
        for path in [
            home / "Desktop",
            home / "OneDrive" / "Desktop",
            home / "OneDrive" / "デスクトップ",
            home / "デスクトップ",
        ]:
            if path.exists():
                return str(path)
    except Exception:
        pass

    return '.'


def save_posts(all_sections, x_candidates=None):
    """
    x_candidates: 実際のBuffer自動投稿(AUTO_POST_TO_X=true)と全く同じ選定ロジック
                  （サンプル動画あり・配信日が新しい順）でソート済みの (product, post_text) の
                  全候補リスト。AUTO_POST_TO_X=false でも渡すことで、
                  「もしtrueにしたらどれが投稿されるか」をtxt上で確認できるようにする。
    """
    save_dir  = get_save_dir()
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename  = f'dmm_x_posts_{timestamp}.txt'
    filepath  = os.path.join(save_dir, filename)

    total = sum(len(posts) for _, posts in all_sections)

    # 品番 → 配信日順の順位（サンプル動画ありの候補内のみ）
    rank_map = {}
    if x_candidates:
        for i, (product, _) in enumerate(x_candidates, 1):
            cid = product.get('content_id')
            if cid:
                rank_map[cid] = i

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"# DMMアフィリエイト X投稿文（単一ポスト形式）\n")
        f.write(f"# 生成日時: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# フロア: {DMM_FLOOR} / モード: {DMM_SORT_MODE}\n")
        f.write(f"# 価格フィルター: {DMM_PRICE_RANGE}\n")
        f.write(f"# 取得開始: {DMM_OFFSET}件目 / 各ソート{FETCH_COUNT}件\n")
        f.write(f"# 総投稿数: {total}件（1商品＝1ポスト構成）\n")
        f.write(f"# AUTO_POST_TO_X: {'true（実際にBufferへ投稿されます）' if AUTO_POST_TO_X else 'false（投稿は行われません。テキスト生成のみ）'}\n")
        f.write("=" * 60 + "\n\n")

        if x_candidates is not None:
            f.write("=" * 60 + "\n")
            f.write(f"🐦 Xへの投稿見込み一覧（配信日が新しい順・AUTO_POST_TO_X=trueなら以下の最大{X_POST_LIMIT}件が投稿されます）\n")
            f.write(f"   ※投稿は上から順に試行され、失敗した場合は下位（{X_POST_LIMIT + 1}位以降）が繰り上がります\n")
            f.write("=" * 60 + "\n")
            if x_candidates:
                for i, (product, _) in enumerate(x_candidates[:X_POST_LIMIT], 1):
                    f.write(f"  {i}. {product['title'][:40]}（配信日: {product.get('date') or '不明'} / 品番: {product.get('content_id', '-')}）\n")
            else:
                f.write("  （投稿対象がありませんでした）\n")
            f.write("\n")

        for sort_label, posts in all_sections:
            f.write(f"{'=' * 60}\n")
            f.write(f"【{sort_label}】{len(posts)}件\n")
            f.write(f"{'=' * 60}\n\n")

            for i, (product, post_text) in enumerate(posts, 1):
                f.write(f"--- {sort_label} {i}/{len(posts)} ---\n")
                f.write(f"商品名: {product['title']}\n")
                f.write(f"文字数: {x_text_length(post_text)}（上限280文字）\n")

                if x_candidates is not None:
                    cid = product.get('content_id')
                    if cid in rank_map and rank_map[cid] <= X_POST_LIMIT:
                        f.write(f"📮 投稿対象: ○（配信日順 {rank_map[cid]}位 / 上限{X_POST_LIMIT}件以内）\n")
                    elif cid in rank_map:
                        f.write(f"📮 投稿対象: ✕（配信日順 {rank_map[cid]}位 / 上限{X_POST_LIMIT}件を超過）\n")
                    else:
                        f.write("📮 投稿対象: 不明（品番未取得のため判定不可）\n")

                url_status = {True: 'OK', False: 'NG（要確認）', None: '未確認'}.get(product.get('url_check'))
                f.write(f"URL確認: {product['affiliate_url']} [{url_status}]\n")

                if product.get('sample_movie_url'):
                    sample_status = {True: 'OK', False: 'NG（要確認）', None: '未確認'}.get(product.get('sample_check'))
                    f.write(f"サンプル動画: {product['sample_movie_url']} [{sample_status}]\n")

                f.write("-" * 40 + "\n")
                f.write(post_text)
                f.write("\n\n")

                thread_main = product.get('_thread_main')
                thread_reply = product.get('_thread_reply')
                if thread_main is not None:
                    f.write("－－－ 実際の投稿形式（スレッド分割後プレビュー） －－－\n")
                    f.write(f"【1件目・本文】（{x_text_length(thread_main)}文字）\n{thread_main}\n\n")
                    if thread_reply:
                        f.write(f"【2件目・リプライ】（{x_text_length(thread_reply)}文字）\n{thread_reply}\n")
                    f.write("\n")

    print(f'\n💾 保存完了！')
    print(f'📄 ファイル: {filepath}')
    return filepath

# ================================================================
# 🚀 メイン実行
# ================================================================

print(f'🛍️  DMMから商品情報を取得中（フロア: {DMM_FLOOR} / モード: {DMM_SORT_MODE}）...')

POSTED_HISTORY = load_posted_history()
print(f'📚 過去に生成済みの品番: {len(POSTED_HISTORY)}件（重複はスキップします）')
generated_ids = set()  # このランでテキスト生成の対象になった品番（AUTO_POST_TO_X=false時の重複防止用）

all_sections = []
processed_total = 0

for sort_key, sort_label in SORT_LIST:
    if processed_total >= MAX_PROCESS_COUNT:
        print(f'  ⏹  処理件数の上限（{MAX_PROCESS_COUNT}件）に達したため、以降のソートはスキップします。')
        break

    # ----------------------------------------------------------------
    # 価格フィルター使用時: MIN_PROCESS_COUNT に達するまで追加取得を繰り返す
    # ----------------------------------------------------------------
    remaining_quota = MAX_PROCESS_COUNT - processed_total
    # このソートで目指す件数（上限 and 最低保証の両方を考慮）
    sort_target = min(remaining_quota, MAX_PROCESS_COUNT // len(SORT_LIST) if len(SORT_LIST) > 1 else MAX_PROCESS_COUNT)
    # 最低保証件数：価格フィルターの有無にかかわらず常に適用
    # （サンプルURLなしスキップも含め、フィルターで大きく件数が落ちることに対応）
    # 【重要】自動投稿(AUTO_POST_TO_X=true)時は、最低でも投稿予定数(X_POST_LIMIT)分の
    # 候補を確保できるまで、100件ずつ次のページを検索し続ける。
    _base_min = MIN_PROCESS_COUNT if MIN_PROCESS_COUNT > 0 else 0
    _need_for_post = X_POST_LIMIT if AUTO_POST_TO_X else 0
    min_target = min(remaining_quota, max(_base_min, _need_for_post))

    products      = []
    # 新着順（-date）で開始番号が未指定（空欄）の場合は、ランダム開始位置ではなく
    # 1件目（＝最新データ）から検索する
    if sort_key == 'date' and not POST_START_INDEX_EXPLICIT:
        fetch_offset = 1
        print(f'  🆕 [{sort_label}] 開始番号が未指定のため、最新データ（1件目）から検索します。')
    else:
        fetch_offset = DMM_OFFSET
    fetch_hits    = DMM_HITS
    seen_ids      = set()
    MAX_FETCH_ROUNDS = 20  # 無限ループ防止: 最大20回まで追加取得（20件確保のため増量）

    # 価格フィルター・サンプルフィルター両方を考慮して最低件数まで追加取得を続ける
    effective_min = min_target if min_target > 0 else 0

    for _round in range(MAX_FETCH_ROUNDS):
        raw_items = fetch_dmm_products(sort_key, sort_label, offset=fetch_offset, hits=fetch_hits)
        if not raw_items:
            print(f'  ⚠️  [{sort_label}] 商品が取得できませんでした。')
            break

        for item in raw_items:
            cid = item.get('content_id') or item.get('product_id') or item.get('affiliateURL', '')
            if cid and cid in seen_ids:
                continue
            if cid:
                seen_ids.add(cid)
            if is_vr_product(item):
                print(f"    ⏭ VR作品のためスキップ: [{cid}] {item.get('title','')[:30]}")
                continue
            p = parse_product(item)
            if p.get('content_id') and p['content_id'] in POSTED_HISTORY:
                print(f"    ⏭ 過去に生成済みのためスキップ: [{p['content_id']}] {p['title'][:30]}")
                continue
            if PRICE_RANGE_BOUNDS and not price_in_range(p):
                continue
            # 配信日が実行時点より未来（予約商品・販売開始前）の場合はまだ投稿しない
            if is_future_release(p):
                print(f"    ⏭ 配信日が未来のためスキップ: [{p.get('content_id','')}] {p['title'][:30]}（配信日: {p.get('date') or '不明'}）")
                continue
            products.append(p)
            # 価格フィルターなし or min_target未達の場合は remaining_quota で止める
            # 価格フィルターあり & min_target 未達の場合は、まず min_target まで収集を続ける
            hard_limit = max(remaining_quota, effective_min) if effective_min > 0 else remaining_quota
            if len(products) >= hard_limit:
                break

        collected = len(products)
        # 価格フィルター・サンプルフィルター・未来配信日どれでスキップされた場合も、
        # 目標件数（min_target：MIN_PROCESS_COUNTとX_POST_LIMITの大きい方）に届くまで
        # 次の100件（offsetを進めたページ）を検索し続ける。
        # sortパラメータを正しい'date'に修正済みのため、ページを進めても日付の並びは
        # 正しく続き（新しい→古いの順で途切れない）、古い作品で不当に埋め合わされる
        # 心配はない。
        need_more = min_target > 0 and collected < min_target
        print(f'  📦 [{sort_label}] 累計確保: {collected}件 / 目標最低: {min_target}件')

        if not need_more or len(raw_items) < fetch_hits:
            # 目標達成 or これ以上取得できるデータがない
            if len(raw_items) < fetch_hits and need_more:
                print(f'  ⚠️  [{sort_label}] DMM APIの取得可能件数の上限に達しました（{collected}件で終了）。')
            break

        # 取得範囲をずらして追加取得
        fetch_offset += fetch_hits
        print(f'  🔄 [{sort_label}] {min_target}件未満（{collected}件）のため、次の{fetch_hits}件（offset={fetch_offset}〜）を追加取得します...')

    if PRICE_RANGE_BOUNDS:
        print(f'  💰 価格フィルター適用済み: 合計 {len(products)} 件確保')

    # 合計処理件数の上限を適用
    # min_target を優先：フィルターで件数が落ちた場合は min_target まで確保した分を守る
    if min_target > 0:
        effective_cap = max(remaining_quota, min(min_target, len(products)))
    else:
        effective_cap = remaining_quota
    if len(products) > effective_cap:
        products = products[:effective_cap]

    if not products:
        print(f'  ⚠️  [{sort_label}] 価格条件に合う商品がありませんでした。スキップします。')
        continue

    print(f'  📝 [{sort_label}] 投稿文を生成中...')

    posts = []
    for p in products:
        post_text = build_x_single_post(p)
        posts.append((p, post_text))
        if p.get('content_id'):
            generated_ids.add(p['content_id'])
        print(f"    ✅ [{x_text_length(post_text)}文字] {p['title'][:30]}...")

    processed_total += len(posts)
    all_sections.append((sort_label, posts))

if not all_sections:
    # 新着順モードでの「遡り取得なし」化により、直近に新着が無く候補が0件になるのは
    # 正常なケース（＝今は投稿すべき新しい作品がまだ無いだけ）。
    # ここでエラー終了(exit 1)にするとGitHub Actions上で失敗扱いになってしまうため、
    # 正常終了(exit 0)にして次回の定期実行に委ねる。
    print('ℹ️  今回は条件に合う新着商品がありませんでした（投稿済み、または価格/サンプル条件に合致する新着なし）。')
    print('   次回の定期実行で新着が見つかり次第、投稿されます。')
    sys.exit(0)

first_label, first_posts = all_sections[0]
print('\n' + '=' * 60)
print(f'📋 投稿文プレビュー（{first_label} 1件目）')
print('=' * 60)
print(first_posts[0][1])
print('=' * 60)

# 実際の自動投稿(post_to_x_buffer)と全く同じ選定ロジックで候補を並べておく。
# AUTO_POST_TO_X=falseでもこのリストをsave_postsに渡すことで、
# 「もしtrueにしたら何が投稿されるか」をtxt上で確認できるようにする。
x_candidates = [
    (product, post_text)
    for _, posts in all_sections
    for product, post_text in posts
]
x_candidates.sort(key=lambda pt: product_date_sort_key(pt[0]), reverse=True)

save_posts(all_sections, x_candidates)

total = sum(len(p) for _, p in all_sections)
print(f'\n✅ 完了！合計 {total} 件の投稿文を保存しました。')

if AUTO_POST_TO_X:
    print('\n' + '=' * 60)
    print(f'🐦 X自動投稿を開始します（Buffer経由 / 最大 {X_POST_LIMIT} 件・配信日が新しい順）')
    print('=' * 60)

    # DMM_SORT_MODE=rank/both を選んでいても、実際にBufferへ投稿する順番は
    # 常に配信日（date）が新しいものを優先する（x_candidatesは上で計算済み）。
    flat_posts = x_candidates

    posted_count = 0
    posted_ids = set()  # 実際にBufferへの投稿に成功した品番のみを記録する（重複投稿防止用）

    for product, post_text in flat_posts:
        if posted_count >= X_POST_LIMIT:
            break
        print(f"\n--- 投稿 {posted_count + 1}/{X_POST_LIMIT} ---")
        print(f"商品名: {product['title'][:40]}（配信日: {product.get('date') or '不明'}）")
        success = post_to_x_buffer(product, post_text, post_index=posted_count)
        if success:
            posted_count += 1
            if product.get('content_id'):
                posted_ids.add(product['content_id'])
            # customScheduled時はdueAtで間隔をずらしているため、ここでの待機は
            # Buffer APIのレート制限（15分100件）対策として短めでよい。
            if posted_count < X_POST_LIMIT:
                time.sleep(2)

    print(f'\n🐦 自動投稿完了: {posted_count}/{X_POST_LIMIT} 件成功（Buffer経由）')

    # 【重複投稿防止】実際にBufferへ投稿できた品番だけを履歴に記録する。
    # テキストだけ生成されてBuffer投稿されなかった品番（X_POST_LIMIT超過分など）は
    # 履歴に残さないことで、次回以降の実行でも引き続き投稿候補になる。
    if posted_ids:
        save_posted_history(POSTED_HISTORY | posted_ids)
        print(f'📚 投稿済み履歴を更新しました（今回 +{len(posted_ids)}件 / 累計 {len(POSTED_HISTORY | posted_ids)}件）: {get_history_file()}')
else:
    # テキスト生成のみのモードでは、生成した品番を履歴に記録して次回以降の重複生成を防ぐ
    if generated_ids:
        save_posted_history(POSTED_HISTORY | generated_ids)
        print(f'📚 履歴を更新しました（今回 +{len(generated_ids)}件 / 累計 {len(POSTED_HISTORY | generated_ids)}件）: {get_history_file()}')
    print('テキストファイルを開いてXに手動投稿してください。')
    print(f'（ファイル冒頭に「Xへの投稿見込み一覧」として、AUTO_POST_TO_X=trueにした場合に投稿される{X_POST_LIMIT}件が表示されています）')
    print('（Buffer経由での自動投稿を行うには AUTO_POST_TO_X=true を設定してください）')
