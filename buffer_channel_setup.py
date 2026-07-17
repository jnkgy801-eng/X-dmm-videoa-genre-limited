"""
🔎 Buffer チャンネルID確認用ヘルパースクリプト

dmm_x_post_generator.py で POST_METHOD=buffer を使う際に必要な
BUFFER_CHANNEL_ID（投稿先のXチャンネルのID）を確認するためのスクリプトです。

【事前準備】
1. Bufferにログイン → 左メニュー「API」設定ページ
   https://publish.buffer.com/settings/api
   から Personal API Key を発行する
2. Bufferの管理画面で、投稿したいXアカウントをチャンネルとして接続しておく

【使い方】
    export BUFFER_API_KEY=xxxxxxxx
    python buffer_channel_setup.py

organizationId と、service=twitter のチャンネルの id が表示されます。
表示された channel の id を BUFFER_CHANNEL_ID として使ってください。
"""

import os
import sys
import requests

BUFFER_API_KEY = os.environ.get('BUFFER_API_KEY', '')

if not BUFFER_API_KEY:
    print('❌ 環境変数 BUFFER_API_KEY が設定されていません。')
    print('   https://publish.buffer.com/settings/api で発行したPersonal API Keyを設定してください。')
    sys.exit(1)

BUFFER_API_ENDPOINT = 'https://api.buffer.com'


def graphql(query, variables=None):
    resp = requests.post(
        BUFFER_API_ENDPOINT,
        json={'query': query, 'variables': variables or {}},
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {BUFFER_API_KEY}',
        },
        timeout=30,
    )
    data = resp.json()
    if data.get('errors'):
        for err in data['errors']:
            print(f"  ❌ APIエラー: {err.get('message', err)}")
        sys.exit(1)
    return data.get('data', {})


print('🔎 Organization一覧を取得中...')
org_data = graphql("""
query GetOrganizations {
  account {
    organizations {
      id
      name
    }
  }
}
""")

orgs = (org_data.get('account') or {}).get('organizations') or []
if not orgs:
    print('❌ Organizationが見つかりませんでした。Bufferアカウントの設定を確認してください。')
    sys.exit(1)

for org in orgs:
    org_id = org.get('id')
    org_name = org.get('name', '(名称不明)')
    print(f"\n🏢 Organization: {org_name}")
    print(f"   organizationId = {org_id}")

    ch_data = graphql("""
    query GetChannels($organizationId: OrganizationId!) {
      channels(input: { organizationId: $organizationId }) {
        id
        name
        displayName
        service
        isQueuePaused
      }
    }
    """, {'organizationId': org_id})

    channels = ch_data.get('channels') or []
    if not channels:
        print('   （このOrganizationにはチャンネルがありません）')
        continue

    for ch in channels:
        marker = '👉' if ch.get('service') == 'twitter' else '  '
        paused = '（キュー停止中）' if ch.get('isQueuePaused') else ''
        print(f"   {marker} [{ch.get('service')}] {ch.get('displayName') or ch.get('name')} {paused}")
        print(f"        channelId = {ch.get('id')}")

print('\n✅ 完了。X（twitter）のチャンネルの channelId を BUFFER_CHANNEL_ID として使ってください。')
