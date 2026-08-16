"""
💰🐦 DMM人気出演者アフィリエイトURL → X投稿ジェネレーター

【このスクリプトの目的】
ActressSearch APIには「人気順」ソートが存在しないため、代わりに
ItemList（商品検索）の sort=rank（人気順）で人気作品を大量取得し、
そこに出演している女優の出現回数を集計することで「今人気の出演者」を
間接的に推定する。

上位3名について、個別作品ではなく「出演者名の作品一覧ページ」への
アフィリエイトURL（ActressSearchのlistURL.digital）を使ってX投稿文を
作成する。

【なぜ出演者一覧URLを使うのか】
個別作品URLは1本にしか遷移しないが、一覧URLならユーザーが自分の
好みの作品を選べるため、取りこぼしを減らせる（コンバージョン機会の増加）。

【AUTO_POST_TO_X=true にすると】
dmm_x_post_generator.py と同じBuffer（GraphQL API）経由でXに予約投稿する。
未設定時はテキストファイル保存のみで完全無料で動作する。
"""

import os
import sys
import json
import datetime
import requests
import time
from pathlib import Path
from collections import Counter

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

FLOOR_SERVICE_MAP = {
    'videoa':  ('digital', 'videoa'),
    'videoc':  ('digital', 'videoc'),
    'anime':   ('digital', 'anime'),
    'doujin':  ('doujin',  'digital_doujin'),
    'comic':   ('ebook',   'comic'),
    'goods':   ('mono',    'goods'),
    'digital': ('digital', 'videoa'),
}

# ----------------------------------------------------------------
# 🔢 人気ランキング集計に使う「人気作品」の取得件数
#    多いほど集計精度は上がるが、DMM APIへの問い合わせ回数・時間が増える
# ----------------------------------------------------------------
RANK_SAMPLE_SIZE = int(os.environ.get('RANK_SAMPLE_SIZE', '200'))

# ----------------------------------------------------------------
# 🏆 上位何名の出演者を投稿対象にするか
# ----------------------------------------------------------------
TOP_ACTRESS_COUNT = int(os.environ.get('TOP_ACTRESS_COUNT', '3'))

DMM_API_BASE = 'https://api.dmm.com/affiliate/v3'
DMM_MAX_RETRIES    = int(os.environ.get('DMM_MAX_RETRIES', '10'))
DMM_RETRY_WAIT_SEC = float(os.environ.get('DMM_RETRY_WAIT_SEC', '3'))

# ----------------------------------------------------------------
# 🐦 X（Twitter）自動投稿設定（Buffer経由のみ対応）
# ----------------------------------------------------------------
AUTO_POST_TO_X = os.environ.get('AUTO_POST_TO_X', 'true').strip().lower() == 'true'
BUFFER_API_KEY    = os.environ.get('BUFFER_API_KEY', '')
BUFFER_CHANNEL_ID = os.environ.get('BUFFER_CHANNEL_ID', '')
BUFFER_INITIAL_DELAY_MIN = float(os.environ.get('BUFFER_INITIAL_DELAY_MIN', '2'))
BUFFER_POST_INTERVAL_MIN = float(os.environ.get('BUFFER_POST_INTERVAL_MIN', '12'))

if AUTO_POST_TO_X and (not BUFFER_API_KEY or not BUFFER_CHANNEL_ID):
    print('⚠️  AUTO_POST_TO_X=true ですが BUFFER_API_KEY / BUFFER_CHANNEL_ID が未設定です。')
    print('   自動投稿はスキップし、テキストファイル保存のみ行います。')
    AUTO_POST_TO_X = False

HASHTAGS_BY_FLOOR = {
    'videoa': '#アダルト動画 #FANZA #PR',
    'videoc': '#素人動画 #FANZA #個人撮影 #PR',
    'anime':  '#エロアニメ #FANZA #PR',
    'doujin': '#同人誌 #FANZA #PR',
    'comic':  '#エロ漫画 #FANZA #PR',
    'goods':  '#大人グッズ #FANZA #PR',
}


# ================================================================
# 🔧 DMM API 呼び出し
# ================================================================

def fetch_popular_items(hits, offset=1):
    """人気順（sort=rank）で作品を取得する。"""
    service, floor_name = FLOOR_SERVICE_MAP.get(DMM_FLOOR, ('digital', 'videoa'))
    params = {
        'api_id':       DMM_API_ID,
        'affiliate_id': DMM_AFFILIATE_ID,
        'site':         'FANZA',
        'service':      service,
        'floor':        floor_name,
        'hits':         min(hits, 100),  # DMM APIの1回あたり最大取得件数は100件
        'offset':       offset,
        'sort':         'rank',
        'output':       'json',
    }
    for attempt in range(1, DMM_MAX_RETRIES + 1):
        try:
            resp = requests.get(f'{DMM_API_BASE}/ItemList', params=params, timeout=15)
            data = resp.json()
            result = data.get('result', {})
            status = result.get('status')
            if status is not None and str(status) != '200':
                message = result.get('message') or data.get('message') or '不明なエラー'
                raise RuntimeError(f'DMM APIエラー応答 status={status} message={message}')
            items = result.get('items', [])
            if isinstance(items, dict):
                items = [items]
            return items
        except Exception as e:
            print(f'  ⚠️  取得失敗（{attempt}/{DMM_MAX_RETRIES}回目）: {e}')
            if attempt < DMM_MAX_RETRIES:
                time.sleep(DMM_RETRY_WAIT_SEC)
    return []


def fetch_popular_items_bulk(total):
    """人気順の作品をtotal件になるまでoffsetをずらしながら取得する。"""
    all_items = []
    offset = 1
    while len(all_items) < total:
        hits = min(100, total - len(all_items))
        print(f'  📦 人気作品取得中... offset={offset} hits={hits}')
        items = fetch_popular_items(hits=hits, offset=offset)
        if not items:
            print('  ⚠️  これ以上取得できる人気作品がありません。')
            break
        all_items.extend(items)
        offset += hits
    return all_items


def count_actress_appearances(items):
    """人気作品リストから出演女優の出現回数を集計する。"""
    counter = Counter()
    for item in items:
        actresses = (item.get('iteminfo', {}) or {}).get('actress') or []
        for a in actresses:
            name = a.get('name', '').strip()
            if name:
                counter[name] += 1
    return counter


def search_actress_by_name(name):
    """ActressSearch APIで名前から女優情報（idやlistURL含む）を取得する。"""
    params = {
        'api_id':       DMM_API_ID,
        'affiliate_id': DMM_AFFILIATE_ID,
        'keyword':      name,
        'hits':         1,
        'output':       'json',
    }
    for attempt in range(1, DMM_MAX_RETRIES + 1):
        try:
            resp = requests.get(f'{DMM_API_BASE}/ActressSearch', params=params, timeout=15)
            data = resp.json()
            result = data.get('result', {})
            actresses = result.get('actress', [])
            if isinstance(actresses, dict):
                actresses = [actresses]
            if actresses:
                return actresses[0]
            return None
        except Exception as e:
            print(f'  ⚠️  女優検索失敗（{attempt}/{DMM_MAX_RETRIES}回目・{name}）: {e}')
            if attempt < DMM_MAX_RETRIES:
                time.sleep(DMM_RETRY_WAIT_SEC)
    return None


# ================================================================
# 📝 投稿文の生成
# ================================================================

def build_actress_post(rank, name, appearance_count, list_url):
    """出演者一覧URLを使ったX投稿文を1件生成する。"""
    hashtags = HASHTAGS_BY_FLOOR.get(DMM_FLOOR, '#FANZA #PR')
    rank_emoji = {1: '🥇', 2: '🥈', 3: '🥉'}.get(rank, f'{rank}位')
    # 女優名をハッシュタグ化（スペース除去。dmm_x_post_generator.pyのactor_tagsと同じ形式）
    name_tag = '#' + name.replace(' ', '').replace('　', '')

    lead_variants = [
        f'{rank_emoji} 今、人気の出演者 第{rank}位は「{name_tag}」さん！',
        f'{rank_emoji} 直近の人気作品ランキングで{rank}位に多数ランクイン中の「{name_tag}」さん。',
        f'{rank_emoji} 見放題・単品ともに勢いのある「{name_tag}」さん、人気作品ランキング{rank}位です。',
    ]
    lead = lead_variants[(rank - 1) % len(lead_variants)]

    body = f'人気作品ランキング上位に{appearance_count}作品ランクイン中🔥\n作品一覧はこちら👇'

    text = f'{lead}\n\n{body}\n{list_url}\n\n{hashtags}'
    return text


def x_text_length(text):
    """Xの文字数カウント（URLは短縮扱いで概算23文字とする簡易版）。"""
    import re as _re
    url_pattern = _re.compile(r'https?://\S+')
    urls = url_pattern.findall(text)
    stripped = url_pattern.sub('', text)
    return len(stripped) + len(urls) * 23


# ================================================================
# 🐦 Buffer経由のX自動投稿（dmm_x_post_generator.pyと同じ仕組みを流用）
# ================================================================

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


def buffer_create_single_post(post_text, post_index=0):
    """Bufferで1件投稿を予約する（動画なし・出演者一覧URLをそのまま本文に含める）。"""
    input_obj = {
        'text': post_text,
        'channelId': BUFFER_CHANNEL_ID,
        'schedulingType': 'automatic',
        'mode': 'customScheduled',
        'dueAt': (
            datetime.datetime.utcnow()
            + datetime.timedelta(minutes=BUFFER_INITIAL_DELAY_MIN + post_index * BUFFER_POST_INTERVAL_MIN)
        ).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
    }

    data, err = buffer_graphql_request(_BUFFER_CREATE_POST_MUTATION, {'input': input_obj})
    if err:
        return False, err

    result = (data or {}).get('createPost') or {}
    if result.get('message'):
        return False, result['message']
    if result.get('post'):
        due = result['post'].get('dueAt', '')
        print(f'  📅 Buffer予約日時: {due}' if due else '  📅 Bufferのキューに追加しました')
        return True, None

    return False, '不明なエラー（createPostの応答にpostが含まれません）'


# ================================================================
# 💾 保存
# ================================================================

def get_save_dir():
    save_to_repo = os.environ.get('SAVE_TO_REPO', 'false').strip().lower() == 'true'
    if save_to_repo:
        out_dir = Path('outputs')
    else:
        out_dir = Path.home() / 'Desktop'
        if not out_dir.exists():
            out_dir = Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def save_result(entries):
    out_dir = get_save_dir()
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = out_dir / f'top_actress_posts_{ts}.txt'

    lines = []
    lines.append('# 人気出演者TOP投稿 一覧')
    lines.append(f'# フロア: {DMM_FLOOR} / 集計対象人気作品数: {RANK_SAMPLE_SIZE}')
    lines.append(f'# 生成日時: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    lines.append('')
    for i, e in enumerate(entries, 1):
        lines.append(f'--- {i}位: {e["name"]}（出現{e["count"]}作品）---')
        lines.append(e['post_text'])
        lines.append(f'[文字数: {x_text_length(e["post_text"])}]')
        lines.append('')

    out_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f'💾 保存しました: {out_path}')
    return out_path


# ================================================================
# 🚀 メイン処理
# ================================================================

def main():
    print(f'🛍️  人気作品を{RANK_SAMPLE_SIZE}件取得します（フロア: {DMM_FLOOR}）...')
    items = fetch_popular_items_bulk(RANK_SAMPLE_SIZE)
    if not items:
        print('❌ 人気作品を取得できませんでした。終了します。')
        sys.exit(1)
    print(f'✅ {len(items)}件の人気作品を取得しました。')

    print('🔢 出演者の出現回数を集計中...')
    counter = count_actress_appearances(items)
    if not counter:
        print('❌ 出演者情報が1件も見つかりませんでした。終了します。')
        sys.exit(1)

    top_actresses = counter.most_common(TOP_ACTRESS_COUNT)
    print(f'🏆 人気出演者TOP{TOP_ACTRESS_COUNT}:')
    for name, count in top_actresses:
        print(f'   {name}: {count}作品')

    entries = []
    for rank, (name, count) in enumerate(top_actresses, start=1):
        print(f'\n🔍 [{rank}位] {name} のアフィリエイトURLを検索中...')
        actress_info = search_actress_by_name(name)
        if not actress_info:
            print(f'  ⚠️  {name} の女優情報が見つかりませんでした。スキップします。')
            continue
        list_url = (actress_info.get('listURL') or {}).get('digital', '')
        if not list_url:
            print(f'  ⚠️  {name} の一覧URLが取得できませんでした。スキップします。')
            continue
        post_text = build_actress_post(rank, name, count, list_url)
        entries.append({
            'rank': rank,
            'name': name,
            'count': count,
            'actress_id': actress_info.get('id'),
            'list_url': list_url,
            'post_text': post_text,
        })
        print(f'  ✅ [{x_text_length(post_text)}文字] 投稿文を作成しました。')

    if not entries:
        print('❌ 投稿対象の出演者情報を1件も作成できませんでした。終了します。')
        sys.exit(1)

    save_result(entries)

    if AUTO_POST_TO_X:
        print('\n' + '=' * 60)
        print(f'🐦 X自動投稿を開始します（Buffer経由 / {len(entries)}件）')
        print('=' * 60)
        posted_count = 0
        for i, e in enumerate(entries):
            print(f"\n--- 投稿 {i + 1}/{len(entries)} ---")
            print(f"出演者: {e['name']}（{e['rank']}位・出現{e['count']}作品）")
            ok, err = buffer_create_single_post(e['post_text'], post_index=i)
            if ok:
                posted_count += 1
                print('  ✅ Buffer経由で投稿を予約しました。')
            else:
                print(f'  ❌ 投稿失敗: {err}')
            if i < len(entries) - 1:
                time.sleep(2)
        print(f'\n🐦 自動投稿完了: {posted_count}/{len(entries)} 件成功（Buffer経由）')
    else:
        print('\nテキストファイルを開いてXに手動投稿してください。')
        print('（Buffer経由での自動投稿を行うには AUTO_POST_TO_X=true と BUFFER_API_KEY / BUFFER_CHANNEL_ID を設定してください）')


if __name__ == '__main__':
    main()
