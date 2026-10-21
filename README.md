# gps-another — 位置情報シミュレーションのGUI試作

地図で指定した地点を結ぶルートを取得し、速度に応じて座標を補間する、Windows向けの個人開発・検証用アプリです。

**現在の送信処理はモックです。iPhoneの位置を実際に変更するアプリとしては完成していません。**
`MockLocationSender` が1秒ごとの送信予定座標をコンソールへ出力します。実送信は `LocationSender` インターフェースを差し替える拡張点です。

## できること

- Leaflet / OpenStreetMapによる地図表示と、最大4地点の指定。
- 緯度・経度の入力、速度1〜40km/hと移動モードの切替。
- 外部ルーティングサービスからの経路取得、移動座標の補間。
- 開始・一時停止・再開・停止と、送信予定座標のモック出力。

## セットアップ（Windows PowerShell）

Pythonと、PySide6 / Qt WebEngineが動くデスクトップ環境を用意します。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:ORS_API_KEY="自分のOpenRouteServiceキー"
.\.venv\Scripts\python.exe app.py
```

アクティベーションは不要です。キーは環境変数か、Git管理外の `.env` に設定します。

## 経路・通信の範囲

- 第一候補はOpenRouteService。`GRAPHHOPPER_API_KEY` があれば代替のGraphHopperを使います。
- 条件によりOSRMへフォールバックしますが、車の高速道路回避を保証できない経路では使用しません。
- 地図タイルや経路取得は外部通信です。「位置送信がモック」であっても、完全オフライン処理ではありません。
- iPhoneのDeveloper Modeや接続条件は、将来の実送信実装の検討事項です。現在のモックGUIを試すために実機接続は必要ありません。

## 実装の見どころ

| ファイル | 役割 |
| --- | --- |
| [main_window.py](main_window.py) | 地図・操作画面と状態管理 |
| [route_service.py](route_service.py) | 外部経路サービスと代替経路 |
| [route_interpolator.py](route_interpolator.py) | 距離・速度に応じた座標補間 |
| [location_sender.py](location_sender.py) | 送信インターフェースとモック |
| [device_manager.py](device_manager.py) | 接続状態を扱う境界 |
| [config.py](config.py) | 設定・環境変数・リソース読込 |

## テスト・Windowsパッケージ

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\build_windows.ps1 -Python ".\.venv\Scripts\python.exe"
```

[tests](tests) は経路サービス・補間の試験です。これが実端末への送信や、Windows配布物の全環境での動作を検証するものではありません。
実機送信の追加時は、所有・許可された端末を使い、停止・解除を含む挙動を確認してください。

制作・管理：**Atsushi Odajima**。実装にAI支援を利用しています。
