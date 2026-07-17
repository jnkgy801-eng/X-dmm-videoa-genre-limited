# DMM & FANZA X投稿文ジェネレーター

DMMアフィリエイトAPI（v3）を使って商品情報を自動取得し、X（Twitter）向けの**1投稿完結型の投稿文**を自動生成するツールです。  
生成した投稿文はテキストファイルに保存されます。デフォルトで `AUTO_POST_TO_X=true` になっており、SNS管理ツール「Buffer」経由でXへ自動的に予約投稿を作成します（可能であればサンプル動画の冒頭を数秒だけ切り出したクリップを添付します）。

**デフォルトの動作（GitHub Actions）**
- **1日2回自動実行**され、**新着（配信日が新しい）順に2作品**をBufferへ予約投稿します（1日合計4作品程度）
- **一度Bufferへ投稿できた作品は履歴に記録され、二度と投稿されません**（重複投稿防止）
- `DMM_ARTICLE` / `DMM_ARTICLE_ID` を設定すると、特定ジャンル・女優などに絞り込んで取得できます（ジャンル特化運用）
- 取得するフロア・価格帯・ソートモード（新着/人気/両方）は環境変数やワークフローの入力から切り替え可能です
  （ただし実際にBufferへ投稿する順番は、どのモードを選んでも常に配信日が新しいものが優先されます）

---

## 📌 投稿の構成（1投稿完結型）

1商品につき、1つの投稿として生成します。

```
これ絶対見て👇
📽 タイトル

正直期待してなかったのに、気づいたら最後まで一気見してた

🛒 気に入ったら購入。会員登録はそのときで大丈夫です👇

当たりだと思った理由を正直に言うと、レビュー平均4.5（32件）の高評価、〇〇制作。

💰 ¥990
👤 出演者名
🏷 #人妻　#巨乳

https://af.dmm.com/xxxxx

#FANZA #FANZAおすすめ #AV #PR
```

- サンプルを見て気に入った人が、投稿内の**アフィリエイトURL**から購入する導線
- サンプル動画は会員登録なしで視聴できるため、「登録しないと見られない」と誤解させる文言は使わず、
  会員登録の訴求は「購入するとき」のものとして扱っています
- **現在はデフォルトで動画なし（リンクのみ）の投稿**になっています。DMMのサンプル動画CDNが
  日本国内IP以外からのアクセスをブロックしており、GitHub Actions（海外サーバー）からは
  常に取得に失敗するためです。日本国内IPのプロキシ／セルフホストランナーを用意できる場合は、
  `ENABLE_SAMPLE_VIDEO=true` にすることで、サンプル動画の冒頭数秒を切り出したクリップの添付を
  試みる動作に切り替えられます（詳しくは後述の「サンプル動画クリップ機能」を参照）

---

## 🎬 サンプル動画クリップ機能（シャドウバン対策・現在デフォルトOFF）

> ⚠️ **既知の問題（重要）**：DMMのサンプル動画CDN・litevideoページは、**日本国内IP以外からのアクセスをブロック**しています。
> GitHub Actions（海外サーバー）から実行すると `special.dmm.co.jp/not-available-in-your-region/` に
> リダイレクトされ、常に動画の取得に失敗します。そのため現在は `ENABLE_SAMPLE_VIDEO` のデフォルトを
> `false` にし、動画取得自体を試みず最初からリンクのみの投稿にしています。
> 日本国内IPのプロキシ、または日本国内のセルフホストランナーを用意できる場合のみ、
> `ENABLE_SAMPLE_VIDEO=true` にすると以下のクリップ機能が有効になります。

サンプル動画をそのままXに投稿すると、露骨なシーンが含まれるためシャドウバン
（インプレッションが伸びなくなる）のリスクがあります。対策として、サンプル動画の
冒頭など比較的おだやかな数秒だけをffmpegで切り出して投稿します。

切り出した動画クリップはBufferに「公開URL」として渡す必要があるため、
本リポジトリの `outputs/clips/` にコミット＆pushし、`raw.githubusercontent.com` の
URLを利用します。

| 変数名 | デフォルト | 説明 |
|---|---|---|
| `ENABLE_SAMPLE_VIDEO` | `false` | `true`にすると動画取得（クリップ or フル添付）を試みる。日本国内IP経由でない場合は常に失敗するため注意 |
| `ENABLE_VIDEO_CLIP` | `true` | `ENABLE_SAMPLE_VIDEO=true`の場合のみ有効。`false`にするとクリップを作らずサンプル動画をフル添付する動作になる |
| `CLIP_START_SEC` | `0` | 切り出し開始位置（秒） |
| `CLIP_DURATION_SEC` | `6` | 切り出す長さ（秒） |
| `CLIP_PUSH_WAIT_SEC` | `15` | push後、raw.githubusercontent.com に反映されるまでの待機秒数 |

> ⚠️ **その他の注意**
> - このリポジトリが **public** であることが前提です（privateだと raw.githubusercontent.com に外部からアクセスできません）
> - アダルト系動画ファイルをGitHubリポジトリに保存することは、GitHubの利用規約（Acceptable Use Policies）に
>   抵触するリスクがあります。運用する場合はリスクを理解した上でご利用ください
> - 切り出す秒数が本当に「おだやかな範囲」かは動画次第です。実際に生成されたクリップを確認しながら
>   `CLIP_START_SEC` / `CLIP_DURATION_SEC` を調整することをおすすめします

---

## 🚀 セットアップ

### 必要なもの
- Python 3.10以上
- DMMアフィリエイトAPI ID・アフィリエイトID（[DMM アフィリエイト](https://affiliate.dmm.com/) で取得）
- Bufferアカウント（Freeプランで可。後述の「自動投稿」章を参照）

### インストール
```bash
pip install requests
```

---

## 🔑 登録するSecrets一覧（GitHub Actionsで自動実行する場合）

新しいリポジトリで、**Settings → Secrets and variables → Actions → Secrets タブ → New repository secret** から以下を1つずつ登録してください。

| Secret名 | 値の取得元 | 必須/任意 |
|---|---|---|
| `DMM_API_ID` | [DMMアフィリエイト](https://affiliate.dmm.com/) 管理画面 → API ID発行ページ | 必須 |
| `DMM_AFFILIATE_ID` | 同上。アフィリエイトID（`xxxx-990`のような形式） | 必須 |
| `BUFFER_API_KEY` | [Buffer管理画面](https://publish.buffer.com/settings/api) → 「API」ページで発行するPersonal API Key | 必須（`AUTO_POST_TO_X=true`のデフォルト時） |
| `BUFFER_CHANNEL_ID` | 同梱の `buffer_channel_setup.py` を実行して取得（下記コマンド参照） | 必須（同上） |
| `FANZA_TV_AFFILIATE_URL` | FANZA TV（月額見放題サービス）のアフィリエイトリンクを併用訴求したい場合のみ | 任意 |

`BUFFER_CHANNEL_ID` の確認コマンド：
```bash
export BUFFER_API_KEY=xxxx
python buffer_channel_setup.py
```
表示された `[twitter]` チャンネルの `channelId` をコピーして登録してください。

**ジャンル特化の設定は上記と別枠です。** Secretsではなく **Variables タブ**（同じSettings画面の隣のタブ）に、`DMM_ARTICLE` / `DMM_ARTICLE_ID` を登録してください（秘匿情報ではないため）。値の調べ方は上記「ジャンル特化フィルター」セクションを参照してください。

以上を登録すれば、追加設定なしで `schedule` トリガーにより1日2回・自動投稿が開始されます。

---

## ⚙️ 環境変数一覧

### 必須

| 変数名 | 説明 |
|---|---|
| `DMM_API_ID` | DMMアフィリエイトのAPI ID |
| `DMM_AFFILIATE_ID` | DMMアフィリエイトのアフィリエイトID |
| `BUFFER_API_KEY` | BufferのAPI設定ページで発行するPersonal API Key（`AUTO_POST_TO_X=true`のデフォルト時は必須） |
| `BUFFER_CHANNEL_ID` | 投稿先XチャンネルのID（`AUTO_POST_TO_X=true`のデフォルト時は必須。`buffer_channel_setup.py`で確認） |

### 取得する作品の切り替え（任意）

| 変数名 | デフォルト | 説明 |
|---|---|---|
| `DMM_FLOOR` | `videoa` | 取得するフロア。`videoa` / `videoc` / `anime` / `doujin` / `comic` / `goods` |
| `DMM_SORT_MODE` | `date` | `date`（新着のみ・デフォルト）/ `both`（新着＋人気）/ `rank`（人気のみ）。※実際の自動投稿順には影響しません（常に新着順） |
| `DMM_PRICE_RANGE` | `all` | 価格フィルター。例: `0-999` / `1000-1999` / `5000-`（上限なし）/ `all` |
| `POST_START_INDEX` | 空欄 | 取得開始番号。空欄かつ新着順（`-date`）の場合は常に1件目＝最新データから検索します。数値を指定するとその番号から取得（ランダム性はなくなります） |
| `MAX_PROCESS_COUNT` | `100` | 1回の実行で取得・テキスト生成する商品数の上限（実際にBufferへ投稿するのは`X_POST_LIMIT`件のみ） |
| `MIN_PROCESS_COUNT` | `40` | 価格フィルター使用時、この件数に達するまで追加取得を続ける最低保証件数 |
| `DMM_MAX_RETRIES` | `10` | FANZA/DMM APIへの問い合わせが失敗した場合のリトライ回数の上限 |
| `DMM_RETRY_WAIT_SEC` | `3` | リトライ時の待機秒数（試行のたびに延びる簡易バックオフ） |

### ジャンル特化フィルター（任意）

| 変数名 | デフォルト | 説明 |
|---|---|---|
| `DMM_ARTICLE` | 空欄 | 絞り込み種別。`genre`（ジャンル）/ `actress`（女優）/ `director`（監督）/ `series`（シリーズ）/ `maker`（メーカー）など |
| `DMM_ARTICLE_ID` | 空欄 | 上記種別に対応するID（1件のみ）。DMM APIの `GenreSearch` / `ActressSearch` 等で事前に調べる |

`DMM_ARTICLE` と `DMM_ARTICLE_ID` の両方を指定した場合のみ有効になります。片方だけ、または両方空欄なら従来どおり全ジャンル対象です。
GitHub Actionsで定期実行する場合は、リポジトリの **Settings → Secrets and variables → Actions → Variables** タブに `DMM_ARTICLE` / `DMM_ARTICLE_ID` を登録すると自動的に反映されます（Secretsではなく**Variables**でOKです。秘匿情報ではないため）。
手動実行（workflow_dispatch）の場合は、Actionsタブの実行画面から都度指定することもできます。

### 自動投稿（Buffer経由・デフォルトON）

| 変数名 | デフォルト | 説明 |
|---|---|---|
| `AUTO_POST_TO_X` | `true` | `true`（デフォルト）でBuffer経由の自動投稿ON。`false`にするとテキスト生成のみ |
| `X_POST_LIMIT` | `2` | 1回の実行で投稿する最大件数。デフォルトのスケジュール（1日2回実行）なら「1日合計4作品程度」のペースになる |
| `BUFFER_SCHEDULING_MODE` | `customScheduled` | `customScheduled`（dueAtで日時指定）/ `addToQueue`（Buffer側の予約枠に自動割当） |
| `BUFFER_INITIAL_DELAY_MIN` | `2` | `customScheduled`時、1件目を何分後に予約するか |
| `BUFFER_POST_INTERVAL_MIN` | `12` | `customScheduled`時、2件目以降の予約間隔（分）。デフォルトは5件が1時間以内（2,14,26,38,50分後）に収まる間隔 |

---

## 🐦 自動投稿モード（AUTO_POST_TO_X・デフォルトON）

デフォルトで `AUTO_POST_TO_X=true` になっており、SNS管理ツール「Buffer」のGraphQL API経由でX投稿を作成します。
X公式APIの投稿課金は発生せず、Bufferの無料プランで利用できます。テキストファイルの生成だけ行いたい場合は `AUTO_POST_TO_X=false` を指定してください。

> ℹ️ **SocialDogについて**: SocialDogは外部の開発者向けに使えるAPIを公開していないため、
> GitHub Actionsのようなスクリプトから直接自動投稿することができません（CSV一括アップロードや
> ブラウザ拡張などUI経由の操作のみに対応）。そのため本スクリプトでは、外部からプログラム的に
> 予約投稿を作成できる **Buffer** を採用しています。

#### 必要なもの
1. [Buffer](https://buffer.com/)にサインアップし、投稿したいXアカウントをチャンネルとして接続（Freeプランで3チャンネルまで）
2. Bufferの管理画面 → 設定 → 「API」ページで **Personal API Key** を発行
   （https://publish.buffer.com/settings/api ）
3. 同梱の `buffer_channel_setup.py` でチャンネルIDを確認
   ```bash
   export BUFFER_API_KEY=xxxx
   python buffer_channel_setup.py
   ```
   表示された `[twitter]` のチャンネルの `channelId` を控える

#### ローカル実行
```bash
export DMM_API_ID=xxxx
export DMM_AFFILIATE_ID=xxxx
export BUFFER_API_KEY=xxxx
export BUFFER_CHANNEL_ID=xxxx
# AUTO_POST_TO_X はデフォルトtrueなので指定不要（投稿したくない場合は export AUTO_POST_TO_X=false）

python dmm_x_post_generator.py
```

#### GitHub Actionsで実行する場合
1. リポジトリの **Settings → Secrets and variables → Actions → Secrets** タブに以下を登録（下記「🔑 登録するSecrets一覧」参照）：
   `DMM_API_ID` / `DMM_AFFILIATE_ID` / `BUFFER_API_KEY` / `BUFFER_CHANNEL_ID`
2. ジャンルを特化したい場合は、同じ画面の **Variables** タブに `DMM_ARTICLE` / `DMM_ARTICLE_ID` を登録（任意・秘匿情報ではないのでVariablesでOK）
3. これだけで**1日2回自動実行され、新着2作品ずつがBufferに予約投稿**されます（`schedule`トリガー）
4. フロア・価格帯・ソートモード・投稿件数・ジャンル指定などを変えて手動実行したい場合は、Actionsタブ →
   本ワークフロー → **Run workflow** から各項目を指定してください

#### 自動投稿の順番・重複防止の仕組み
- **投稿順**: `DMM_SORT_MODE` で新着/人気/両方のどれを選んでも、実際にBufferへ投稿する際は
  取得できた候補を配信日（`date`）が新しい順に並べ替えてから、上から `X_POST_LIMIT` 件を投稿します。
  常に「一番新しい未投稿の作品」から投稿される仕組みです。
- **重複防止**: `outputs/dmm_posted_history.json` に、**実際にBufferへの投稿に成功した品番のみ**を記録します。
  次回以降の実行では、この履歴に含まれる品番は取得候補から自動的に除外されるため、
  同じ作品が二重に投稿されることはありません。
  （`MAX_PROCESS_COUNT`件のうち`X_POST_LIMIT`件しか投稿されなかった残りの作品は、
  「投稿済み」扱いにはならず、次回以降も引き続き投稿候補として残ります）
- `AUTO_POST_TO_X=false`でテキスト生成のみ行った場合は、代わりに「生成した品番」を履歴に記録します
  （同じ内容のテキストが繰り返し生成されるのを防ぐための、従来からの重複防止用途です）。

#### 動作の仕組み・制限事項
- 動画は「ファイルアップロード」ではなく「公開URL」を渡す方式です。優先順位は
  ①切り出したサンプルクリップ（`outputs/clips/`にpush済みのraw URL）→
  ②取得に失敗した場合はサンプル動画のフル直リンク →
  ③それも失敗した場合は動画なし（サンプルURL・アフィリエイトURLをテキストに残したリンクのみ）、
  という順にフォールバックします（投稿自体は失敗させない設計）。
- 投稿は即時公開ではなく、Bufferの「予約投稿（キュー）」に追加される形になります。
  デフォルトは `BUFFER_SCHEDULING_MODE=customScheduled` で、1件目は実行から約2分後、以降は
  `BUFFER_POST_INTERVAL_MIN`（デフォルト12分）間隔で予約されます。
  Buffer側であらかじめ投稿枠（スケジュール）を設定している場合は `BUFFER_SCHEDULING_MODE=addToQueue`
  にすると、その枠に自動で割り当てられます。
- Freeプランのレート制限は15分あたり100件・24時間あたり100件・30日あたり3000件です
  （2026年時点の情報。変更される可能性があるため公式ドキュメントも確認してください）。
- **Buffer自体の利用規約・アダルトコンテンツに関するポリシーは、本ツールでは確認していません。**
  アダルトコンテンツの投稿がBufferの規約に抵触しないか、必ずご自身でBufferの利用規約をご確認の上、
  自己責任でご利用ください（規約違反時はBuffer側のアカウント停止リスクがあります）。

---

## 💾 出力ファイル

生成した投稿文は `outputs/` フォルダに `dmm_x_posts_YYYYMMDD_HHMMSS.txt` という名前で保存されます。  
1商品につき1投稿分のテキストが記録されます。

ローカル実行時はデスクトップ（`~/Desktop`）への保存を優先します。環境変数 `SAVE_DIR` で保存先を明示指定することもできます。

`outputs/dmm_posted_history.json` には、重複投稿防止のための品番一覧が記録されます（上記「重複防止の仕組み」を参照）。

---

## ⚠️ 注意事項

- アダルトコンテンツを動画付きで投稿するため、Xアカウントの設定で **「メディアにセンシティブな内容を含める」をON** にしてください。
- DMMアフィリエイト規約上、サンプル動画の他サービスへのアップロードが許可される範囲かどうかは、ご自身で[DMMアフィリエイト利用規約](https://affiliate.dmm.com/)をご確認ください。
- **Buffer自体の利用規約・アダルトコンテンツに関するポリシーは、本ツールでは確認していません。** アダルトコンテンツの投稿がBufferの規約に抵触しないか、必ずご自身でBufferの利用規約をご確認の上、自己責任でご利用ください（規約違反時はBuffer側のアカウント停止リスクがあります）。
- `X_POST_LIMIT` はBufferのキュー溢れ・レート制限に直結するため、デフォルトの `2` から始め、様子を見て増やすことを推奨します。
- 本リポジトリの `outputs/dmm_posted_history.json` に既存の記録がある場合、修正前のバージョンで
  「生成しただけで投稿はされていない品番」も混ざって記録されている可能性があります。
  気になる場合は、該当ファイルの中身を確認のうえ手動で調整してください。
