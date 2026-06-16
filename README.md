# gps-another

Windows 向けの個人開発・検証用 iPhone 位置情報シミュレーション MVP です。

この初期実装は Python + PySide6 で作成しています。iPhone への実送信部分は `LocationSender` で抽象化し、MVP ではモック送信として 1 秒ごとに送信予定の緯度経度をコンソールへ出力します。

## 対象

- Windows 10/11
- iPhone 12 mini / iOS 16.0.2
- Developer Mode 有効化済み
- 初回 USB 接続、以後は同一 Wi-Fi 接続へ差し替え可能な設計

## セットアップ

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:ORS_API_KEY="your-openrouteservice-api-key"
python app.py
```

OpenRouteService を第一候補として使用します。GraphHopper は `GRAPHHOPPER_API_KEY` を設定した場合のみ代替候補になります。

環境変数の代わりに、リポジトリ直下の `.env` に以下の形式で保存することもできます。`.env` は Git 管理対象外です。

```powershell
ORS_API_KEY=your-openrouteservice-api-key
```

## MVP 機能

- Leaflet + OpenStreetMap タイルによる地図表示
- 地図クリックで最大 4 点まで指定
- 緯度・経度の直接入力
- 指定ポイント一覧表示
- 速度 1km/h から 40km/h のスライダー
- 速度に応じた移動モード自動選択
  - 1-6km/h: 徒歩
  - 7-29km/h: 自転車
  - 30-40km/h: 車
- 車ルートでは OpenRouteService に高速道路回避を指定
- 取得ルートを速度に応じて補間
- Start / Pause / Resume / Stop
- Stop 時に `LocationSender.clear()` を呼び、疑似位置解除に差し替え可能

## 構成

- `app.py`: 起動ファイル
- `config.py`: API キー、設定値
- `device_manager.py`: iPhone 検出、接続状態確認
- `location_sender.py`: iPhone への疑似位置送信抽象化
- `main_window.py`: GUI
- `route_interpolator.py`: ルート座標補間、速度計算
- `route_service.py`: OpenRouteService / GraphHopper / OSRM ルート取得

## iPhone 実送信への差し替え方

`location_sender.py` の `LocationSender` インターフェースを維持したまま、`MockLocationSender` の代わりに以下のような実装を追加します。

- `pymobiledevice3` を使う実装
- `libimobiledevice` 系 CLI を呼び出す実装
- `idevicesetlocation` 相当の CLI を呼び出す実装

GUI 側は `send(latitude, longitude)` と `clear()` のみを呼ぶため、送信方式は差し替え可能です。

## テスト

```powershell
python -m unittest
```

## 注意

このアプリは所有端末に対する開発・検証用途のみを想定しています。App Store 公開や第三者端末操作を前提にしていません。
