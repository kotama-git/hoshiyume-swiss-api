# HOSHIYUME Swiss Calculation API

HOSHIYUME本体と別リポジトリで扱う、計算専用の開発中サービスです。現時点の実装は `GET /health` と `POST /natal` のみです。`/synastry` と `/transit` は未実装です。外部サービスを有効化する前に、対応する正確なソースURL、サービス用トークン、公式天体暦を必ず設定してください。

このリポジトリは `AGPL-3.0-or-later` で公開する方針です。稼働中の全応答には `Link: <SOURCE_CODE_URL>; rel="source"` を付け、`/source` から対応ソースへ移動できます。`SOURCE_CODE_URL` は、実際にデプロイしたタグまたはコミットを指すHTTPS URLにしてください。ライセンス境界の判断はリポジトリ分離だけで確定しないため、HOSHIYUME側の密接な接続コードも別途公開対象として管理します。

## 計算の境界

- HOSHIYUME側が地名を座標とIANAタイムゾーンに変換し、既知の出生時刻をUTCへ確定します。このAPIは地名の検索やAI解釈をしません。
- ブラウザーから直接アクセスさせず、HOSHIYUMEサーバーだけが `SWISS_API_TOKEN` を使って呼びます。APIへユーザーID・氏名・施設名・夢データを送らないでください。
- 天体は太陽から冥王星までの10天体、トロピカル方式。ネイタルの主要アスペクトは合・衝8°、矩・三分6°、六分4°を境界含みで採用します。
- ハウスはPlacidus。計算失敗時はSwissの自動Porphyry結果を採用せず、Whole Signで再計算し、使用方式と理由を返します。出生時刻不明・地理的極点ではハウスを返しません。
- 出生時刻不明の場合は現地正午を**日付だけに基づく計算基準**として使用し、実際の出生時刻とは扱いません。ASC・MC・ハウス・確定アスペクトを返さず、天体位置は `date_reference_only` と明示します。
- 指定されたSwiss天体暦ファイルがない場合、別の計算方式への暗黙のフォールバックを拒否します。

## ローカル実行

Python 3.10以上を使用します。[Swiss Ephemerisの公式配布元](https://github.com/aloistr/swisseph/tree/master/ephe)から天体暦ファイルを別途入手し、リポジトリには含めません。少なくとも対象年代に対応する `sepl_*.se1` と `semo_*.se1` を `SWISS_EPHE_PATH` のディレクトリへ配置してください。現在の簡易実測テストは1800～2399年用の `_18` ファイルを使用します。その他の年代は対応ファイルとテストを追加するまで公開対象外にしてください。

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
export SWISS_EPHE_PATH=/absolute/path/to/ephe
export SWISS_API_TOKEN=replace-with-a-long-random-secret
export SOURCE_CODE_URL=https://github.com/your-account/hoshiyume-swiss-api/tree/exact-deployed-commit
uvicorn swiss_api.main:app --host 127.0.0.1 --port 8000
```

`GET /health` は、天体暦ファイル、サービス用トークン、対応ソースURLのいずれかが未設定なら `not_ready` を返します。準備完了時は計算エンジン・ラッパー・天体暦データの版も返し、HOSHIYUMEのキャッシュキーに含めます。`POST /natal` はサービス用Bearerトークンが必須です。

## コンテナ

`Dockerfile` は公式Swiss Ephemerisリポジトリの特定コミットから、1800～2399年用の惑星・月データだけを取得し、SHA-256が一致しないビルドを停止します。イメージは非rootユーザーで起動し、Cloud Runが指定する `PORT` を検証して使用します。

```sh
docker build -t hoshiyume-swiss-api .
docker run --rm -p 8080:8080 \
  -e SWISS_API_TOKEN=replace-with-a-long-random-secret \
  -e SOURCE_CODE_URL=https://github.com/your-account/hoshiyume-swiss-api/tree/exact-deployed-commit \
  hoshiyume-swiss-api
```

天体暦の固定元とチェックサムは `scripts/fetch_ephemeris.py`、第三者ソフトウェアの表示は `THIRD_PARTY_NOTICES.md` で管理します。

成功時の `POST /natal` は `schema_version`、`chart_type`、`calculation`、`bodies`、`angles`、`houses`、`aspects`、`warnings` を返します。型の正式な契約は `/openapi.json` と `swiss_api/models.py` で確認できます。`house_system_requested` と `house_system_used` を必ず区別し、切替時は `fallback_reason` と警告を返します。天体の黄経・黄緯・速度の単位はそれぞれ度・度・度/日です。`cusps_deg` は第1～第12ハウスの順です。

```json
{
  "schema_version": "1.0",
  "birth": {
    "local_date": "1994-09-08",
    "local_time": "08:30:00",
    "birth_time_known": true,
    "time_zone": "Asia/Tokyo",
    "utc_datetime": "1994-09-07T23:30:00Z",
    "latitude_deg": 35.68,
    "longitude_deg": 139.76
  },
  "options": {
    "zodiac": "tropical",
    "house_system": "placidus",
    "aspect_profile": "major_v1"
  }
}
```

## 検証・公開前の条件

`python -m pytest` で契約・例外処理を検証します。公式天体暦を設定すると実データのスモークテストも実行されます。より厳密な既知値比較、極地・歴史的タイムゾーンの境界テスト、運用上の認証・レート制限は公開前に追加します。

Swiss EphemerisにはAGPLを選択します。ただし、API分離だけでAGPLの適用範囲が確定するとは判断せず、密接な接続部分の公開範囲を継続して確認してください。
