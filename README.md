# HOSHIYUME Swiss Calculation API

HOSHIYUME本体と別リポジトリで扱う、計算専用の開発中サービスです。現時点の実装は `GET /health` と `POST /natal` のみです。`/synastry` と `/transit`、HOSHIYUME・Supabaseとの接続は未実装です。公開・デプロイはしないでください。

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
uvicorn swiss_api.main:app --host 127.0.0.1 --port 8000
```

`GET /health` は天体暦ファイル未設定時に `not_ready` を返します。`POST /natal` はサービス用Bearerトークンが必須です。開発中でも外部公開しないでください。

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

`pyswisseph` とSwiss Ephemerisのライセンス条件について、公開前にAGPLまたはProfessional Licenseの選択と適用範囲を確認してください。API分離だけでHOSHIYUME本体を非公開にできると判断しないでください。
