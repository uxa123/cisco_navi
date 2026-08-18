# 経路探索API

JSON地図、メモリ上の現在位置・障害物、NetworkXを利用した1フロア向け屋内ナビゲーションAPIです。

* `app/routers/`

  * APIのURLとリクエスト受付
* `app/schemas/`

  * PydanticによるJSONの型定義
* `app/services/`

  * 経路探索やMerakiデータ変換などの処理
* `app/repositories/`

  * 地図やDBへのアクセス
* `data/`

  * 仮の施設地図
* `scripts/`

  * 座標モックおよびMeraki Scanning API v3形式のモック送信
* `test_web/`

  * 本番アプリから独立した、SVG地図付きAPI動作確認画面

## セットアップと起動

Python 3.10以上を使用します。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Swagger UIは `http://127.0.0.1:8000/docs`、ヘルスチェックは
`http://127.0.0.1:8000/api/health` で確認できます。

## Android・Meraki結合試験用の開発パネル

開発パネルが有効な場合、APIと同じサーバーの `http://127.0.0.1:8000/dev` を開くと、
メモリ上の位置、ナビセッション、通行止め、直近100件のHTTP通信を確認できます。

```bash
DEV_PANEL_ENABLED=true uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

この試作リポジトリでは既定値を`true`にしています。本番相当環境やLANへ公開する場合は、必ず
次のように無効化してください。無効時は`/dev`と`/api/dev/*`が404になります。

```bash
DEV_PANEL_ENABLED=false uvicorn app.main:app --host 0.0.0.0 --port 8000
```

開発パネルは以下を提供します。

* Backend状態、クライアント位置、Meraki/PDR/融合/マップマッチ位置の自動更新
* セッション、現在経路、残距離、次案内、sequenceの表示とセッション終了
* 既存`POST /api/mock/positions`を使うモック位置登録
* 既存`POST /api/scanning`を使うMeraki Scanning API v3風Payload送信
* 既存Movement APIを使う東西南北1mのPDR動作確認
* 既存障害物APIを使う通行止め登録・解除
* 開発用メモリ状態のリセット

状態表示用の`GET /api/dev/status`とリセット用の`POST /api/dev/reset`だけを追加しています。
その他の操作はすべて既存APIを経由し、Repositoryを画面から直接変更しません。

通信履歴は共通middlewareで収集します。`/api/navigation/sessions`系を「Android（推定）」、
`/api/scanning`を「Meraki / Scanning」、`/dev`と`/api/dev/*`を「Dev Panel」と分類します。
これはパスに基づく推定で、端末認証ではありません。ログには時刻、method、path、status、処理時間と、
パスから解決できるsession/clientだけを保存します。リクエストBody、Scanning secret、Authorization
ヘッダーは保存しません。

結合試験では、パネルからモック位置を登録し、Androidから同じclient IDでセッション開始とMovementを
送信します。その後パネルからMeraki位置を送信し、Androidの`GET /state`で`meraki_correction`が
取得できることを確認します。通信一覧にはMovement、Scanning Push、State Pollがそれぞれ表示されます。

## API使用例

### 地図と目的地候補

`GET /api/maps/{floor_id}`の各nodeには、地点種別を表す`type`と、利用者が目的地として
選択できるかを表す`selectable`が含まれます。この2項目は独立した属性です。

Androidアプリは`selectable=true`のnodeだけを目的地候補として表示し、表示名に`name`、
ナビゲーション開始時の`destination_id`に`id`を使用してください。経路計算専用の廊下や
曲がり角は`selectable=false`です。地図JSONで`selectable`を省略した場合は、既存のテスト地図との
互換性を維持するため`false`として扱われます。

```json
{
  "id": "room-b",
  "name": "教室B",
  "floor_id": "floor-1",
  "x": 15.0,
  "y": 5.0,
  "type": "room",
  "selectable": true
}
```

現在位置を登録します。

```bash
curl -X POST http://127.0.0.1:8000/api/mock/positions \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"mock-user-01","floor_id":"floor-1","x":0,"y":0,"variance":1.5,"observed_at":"2026-07-30T10:00:00+09:00"}'
```

目的地までの経路を探索します。

```bash
curl -X POST http://127.0.0.1:8000/api/routes/search \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"mock-user-01","destination_node_id":"room-b"}'
```

通路を閉鎖し、同じ検索を再実行すると別経路が選ばれます。`blocked` を
`false` にして送信すると閉鎖を解除できます。

```bash
curl -X POST http://127.0.0.1:8000/api/obstacles \
  -H 'Content-Type: application/json' \
  -d '{"edge_id":"edge-04","blocked":true,"reason":"chair","source":"mock"}'
```

利用可能なAPIは、地図取得、位置登録・取得、経路探索、障害物登録・一覧・解除です。
詳細なリクエスト・レスポンス型はSwagger UIを参照してください。状態はプロセスの再起動で初期化されます。

## ナビゲーションセッションとPDR

単発の経路探索に加え、スマートフォンから定期取得できるナビゲーションセッションAPIを利用できます。

```text
POST   /api/navigation/sessions
GET    /api/navigation/sessions/{session_id}
GET    /api/navigation/sessions/{session_id}/state
POST   /api/navigation/sessions/{session_id}/movements
DELETE /api/navigation/sessions/{session_id}
```

ナビ開始前にMeraki受信または`POST /api/mock/positions`でクライアントの絶対位置を登録します。
開始時の絶対位置がPDRの基準となり、movementの方位は`0°=北(+Y)`、`90°=東(+X)`、
`180°=南(-Y)`、`270°=西(-X)`として積算されます。

```bash
curl -X POST http://127.0.0.1:8000/api/navigation/sessions \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"mock-user-01","destination_id":"room-b"}'

curl -X POST http://127.0.0.1:8000/api/navigation/sessions/nav-xxxxxxxx/movements \
  -H 'Content-Type: application/json' \
  -d '{"sequence":1,"distance_m":0.68,"heading_deg":90,"timestamp":"2026-08-17T19:30:20+09:00"}'
```

movementは`distance_m`の代わりに`steps`と`step_length_m`も指定できます。同一または古い
`sequence`は適用済みとして扱われ、位置へ二重加算されません。状態レスポンスにはMeraki位置、
PDR位置、融合位置、マップマッチした通路、残距離、次の案内が含まれます。

新しいMeraki位置を受信すると、同じclient_idの実行中セッションだけがその絶対位置で補正され、
以後のPDR積算基準もリセットされます。推定位置は3m以内の最寄り通路へ投影され、現在ルートから
2mを超えて外れた場合は再探索します。目的地から1m以内は到着と判定します。現在ルート上の通路が
通行止めになった場合も、自動的に迂回経路を探索します。

## SVGテスト画面

テスト画面は本番FastAPIアプリには組み込まれていません。APIとは別のターミナルで、
リポジトリのルートから静的Webサーバーを起動します。

```bash
python3 -m http.server 8080 --directory test_web
```

ブラウザで `http://127.0.0.1:8080` を開いてください。初期設定では
`http://127.0.0.1:8000` のAPIへ接続します。画面上部の入力欄から接続先を変更できます。

画面では以下を確認できます。

* 地図JSONから生成したSVG施設地図
* 地図クリックまたは数値入力による現在座標の登録
* ノードクリックまたは選択欄による目的地指定
* 最短経路、合計距離、案内文の表示
* 通行止めの登録・解除と自動再探索
* 画面内の移動シミュレーターによる現在位置・経路の連続更新

### 画面から移動をシミュレーションする

テスト画面右側の「04 移動シミュレーター」で、以下を設定して「移動を開始」を押します。

* `通常移動`：入口から教室Bまで座標を順番に送信
* `経路を無視（ルート逸脱）`：廊下Bへ曲がる案内を無視して直進し、別経路へ再探索
* `停止状態`：入口の座標を繰り返し送信
* `位置取得失敗`：`locations=[]` のPayloadを送信
* `送信間隔`：0.2秒以上で変更可能
* `経路をループ`：終点到着後に入口から再開

シミュレーターは `test_web/movement_route.json` の座標を読み込み、Scanning API形式で
`POST /api/scanning` へ送信します。進捗バー、送信座標、HTTP結果を画面に表示します。
目的地と経路の `LIVE` を有効にしておくと、現在位置マーカーと経路が自動的に更新されます。
通常経路は `positions`、経路を無視する座標列は `offRoutePositions` で編集できます。

ローカル検証用として、APIは `http://127.0.0.1:8080` と
`http://localhost:8080` からのCORSリクエストのみ許可しています。

## 移動シミュレーション

API起動中に、座標列を一定間隔で送信できます。

```bash
python scripts/simulate_movement.py \
  --base-url http://127.0.0.1:8000 \
  --client-id mock-user-01 \
  --interval 2
```

## テスト

テストは一時ディレクトリに小さな専用地図を作り、本番用JSONには依存しません。

```bash
pytest -q
```

位置情報は内部で `NormalizedPosition` に正規化されます。Meraki Scanning API v3形式の
受信JSONもこの型へ変換して `PositionRepository` に保存するため、経路探索処理は入力元に依存しません。

## Meraki Scanning API v3モック

MR36実機がない期間に、MerakiのWi-Fi Payloadに近いJSONを
`POST /api/scanning` へ送信する検証機能です。実際の電波環境を再現するものではなく、
位置更新、最寄りノード、再経路探索、複数MACの識別、測位失敗時の連携確認を目的とします。

追加パッケージは不要で、通常のセットアップに含まれるFastAPI、Pydanticを使用します。
送信処理にはPython標準ライブラリを使用しています。

### 通常移動

```bash
python scripts/simulate_scanning.py \
  --scenario normal \
  --endpoint http://127.0.0.1:8000/api/scanning
```

最後まで移動した後、先頭から繰り返す場合は `--loop` を付けます。停止は `Ctrl+C` です。

```bash
python scripts/simulate_scanning.py --scenario normal --loop
```

同じ位置を繰り返し送信する停止状態と、位置を取得できない状態も再現できます。

```bash
python scripts/simulate_scanning.py --scenario stationary --interval 2
python scripts/simulate_scanning.py --scenario location-unavailable --interval 2
```

座標とvarianceへ再現可能な誤差を加える場合は、`noisy`と乱数シードを指定します。

```bash
python scripts/simulate_scanning.py --scenario noisy --seed 123
```

HTTP送信せずPayloadだけを確認する場合は `--dry-run` を使用します。

```bash
python scripts/simulate_scanning.py --scenario normal --dry-run
```

以下の引数を利用できます。

* `--endpoint`：Scanning受信URL
* `--client-mac`：端末識別用MACアドレス
* `--network-id`：MerakiネットワークID
* `--secret`：Payloadのsecret
* `--interval`：全地点の待機時間を上書き
* `--route-file`：移動経路JSON
* `--ap-file`：AP配置JSON
* `--scenario`：`normal`、`stationary`、`location-unavailable`、`noisy`
* `--loop`：繰り返し送信
* `--seed`：RSSIと測位誤差の乱数シード
* `--dry-run`：HTTP送信を行わず標準出力へ表示

`--client-mac`、`--network-id`、`--secret` は、それぞれ環境変数
`MERAKI_MOCK_CLIENT_MAC`、`MERAKI_MOCK_NETWORK_ID`、`MERAKI_MOCK_SECRET` でも変更できます。
コマンドライン引数を指定した場合は引数が優先されます。

### 経路とAP配置の編集

移動経路は `scripts/mock_data/floor_1_route.json` の `positions` に記述します。
`x`、`y`はメートル、`wait_seconds`は次の位置を送るまでの秒数です。
`floorPlanId`は `data/facility_map.json` のフロアIDと一致させてください。

AP配置は `scripts/mock_data/ap_positions.json` で編集します。各APのMACアドレス、名前、
地図上の座標を指定します。送信位置からの距離を基にRSSIを生成し、最も強いAPを
`nearestApMac`としてPayloadへ設定します。

### APIと画面での確認

Swagger UIの `POST /api/scanning` からPayloadを直接送信できます。受信後は
`GET /api/positions/{client_id}` で正規化された最新位置を確認できます。

SVGテスト画面のクライアントIDを送信スクリプトの `--client-mac` と一致させると、
最新位置を1秒間隔で取得してマーカーと探索経路を更新します。目的地欄の `LIVE` が有効な間は、
位置が変わるたびに最寄りノードから自動で再探索します。画面には更新回数、開始地点、目的地、
更新時刻が表示され、更新時には地図が緑色に点滅します。既定値はどちらも
`cc:cc:cc:11:11:11` です。

### 実機への切り替え

Meraki DashboardでScanning API v3の送信先を公開環境の `/api/scanning` に設定します。
受信したPayloadはモックと同じ処理で `NormalizedPosition` へ変換されるため、
経路探索サービスの変更は不要です。本番運用前にはHTTPS、secretの検証、送信元制限を追加してください。
