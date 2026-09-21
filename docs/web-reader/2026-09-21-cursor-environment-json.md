---
title: Cursor Cloud の environment.json
queried at: 2026-09-21
agent: cursor-guide
query: `.cursor/environment.json` の公式スキーマ、Python/uv で Web サーバーが無い場合の書き方、secrets の渡し方、install / snapshot / Dockerfile の違い。
---

# Cursor Cloud の environment.json

調査日 2026-09-21。手段は `cursor-guide`（Cursor 公式ドキュメント）。
以後の外部調査メモもこのディレクトリに置く。

正本はスキーマとセットアップページ。このファイルはその時点の読み取り記録。

- セットアップ: https://cursor.com/docs/cloud-agent/setup
- JSON Schema（`unevaluatedProperties: false`）: https://www.cursor.com/schemas/environment.schema.json

セットアップページの文言:

> The full schema is defined [here](https://www.cursor.com/schemas/environment.schema.json).

スキーマに無いフィールド（`env` / `secrets` / `persistedDirectories` / `baseImage`）は
公式には無効。

## claims

### 許可フィールド

ルートは `container` + `common` の合成。追加プロパティは禁止。

ベースマシン（どれか 1 つ。`snapshot` が最優先）:

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `snapshot` | string | ダッシュボードのスナップショット ID。`build` / `image` より優先 |
| `image` | string | レジストリ上のコンテナイメージ参照 |
| `build` | object | Dockerfile ビルド |
| `build.dockerfile` | string | Dockerfile パス（`.cursor` 相対） |
| `build.dockerfileContents` | string | インライン Dockerfile |
| `build.context` | string | ビルドコンテキスト（`.cursor` 相対。省略時は `.cursor`） |
| `agentCanUpdateSnapshot` | boolean | エージェントがスナップショットを更新できるか |

`build` は `dockerfile` か `dockerfileContents` のどちらか必須。

ランタイム / セットアップ:

| フィールド | 型 | 必須 | 説明 |
| --- | --- | --- | --- |
| `name` | string | 任意 | 環境名 |
| `user` | string | 任意 | 実行ユーザー |
| `install` | string | 任意 | Build 時の準備コマンド |
| `start` | string | 任意 | エージェント起動時のサービス起動 |
| `terminals` | array | 任意 | 起動時に tmux で残すプロセス |
| `terminals[].name` | string | 任意 | 端末名 |
| `terminals[].command` | string | 必須 | 実行コマンド |
| `terminals[].description` | string | 任意 | エージェント向け説明 |
| `ports` | array | 任意 | 公開ポート |
| `ports[].port` | integer 1–65535 | 必須 | ポート番号 |
| `ports[].name` | string | 任意 | 表示名 |
| `repositoryDependencies` | string[] | 任意 | 依存リポジトリ URL |

ネットワーク / MCP / テスト:

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `egressAllowlist` | string[] | 追加の外向きドメイン |
| `egressMode` | enum | `allow_all` / `parent_plus_network_settings` / `default_with_network_settings` / `network_settings_only` |
| `disableAllMcpServers` | boolean | ユーザー/チーム MCP を全部ブロック（Cursor 内蔵 MCP は対象外） |
| `mcpServerAllowlist` | object[] | 許可 MCP（`serverUrl` か `command` が必須） |
| `chromeExecutablePath` | string | ブラウザテスト用 Chrome パス |
| `enable_testing` | boolean または `"true"` / `"false"` | クラウドテスト。既定 true |

公式に無いフィールド: `env`、`secrets`、`persistedDirectories`、`baseImage`（近いのは `image`）。
ディスクの永続化は `persistedDirectories` ではなく、Build がディスク全体をスナップショットする。

`build.dockerfile` と `build.context` は `.cursor` 相対。`context` 省略時は `.cursor`。
`.` / `./` / `..` はリポジトリルートを意味する特例。`install` はプロジェクトルートで走る。

### Python + uv（Web アプリではない）場合

公式に Python/uv 専用サンプルは無い。方針は次。

- 繰り返す準備は `install` に置く。長時間プロセスは `install` に置かない。
- 多くのリポジトリでは `start` を省略してよい。
- `terminals` はアプリプロセス用。Web サーバーが無ければ `start` / `terminals` / `ports` は書かない。

### `terminals` は省略してよいか

省略してよい。スキーマで必須ではない。空配列も合法だが、キーごと省略する方が素直。

役割分担（Builds 文書）:

| コマンド | いつ | 用途 |
| --- | --- | --- |
| `install` | 各 Build | 依存関係・生成・コンパイル・ディスクキャッシュ |
| `start` | 各エージェント開始時 | Docker / DB / トンネル |
| `terminals` | 各エージェント開始時 | アプリプロセス（共有 tmux） |

フォーラム上の非公式制約: `terminals` だけ書いて `start` が無いと tmux が立ち上がらないことがある。
使うなら `"start": "true"` が回避策として挙がっている。Web でないなら `terminals` 自体を置かない方が安全。

### Secrets / API キー

`environment.json` には書かない。ダッシュボードの Secrets。

- https://cursor.com/dashboard/cloud-agents
- https://cursor.com/docs/cloud-agent/security-network
- https://cursor.com/docs/cloud-agent/security

| タイプ | 注入先 | モデルから見えるか | `OPENROUTER_API_KEY` |
| --- | --- | --- | --- |
| Environment Variable | エージェント環境変数 | 見える | 不適 |
| Runtime Secret（旧 Redacted Secret） | 環境変数。ツール結果・transcript・commit は `[REDACTED]` | モデルには出ない | これ |
| Build Secret | Docker build のみ。実行中エージェントには無い | 無い | install 時の private registry 用 |

Build が触れるのは team / environment secret。User secret はエージェント開始時だけ。
`install` でキーが要るなら team / environment secret。実行中だけなら Runtime Secret で足りる。
既存エージェントには入らない。追加後は新しいエージェントを起動する。

### `install` の制約

文書化されていること:

1. 完了しなければならない。長時間プロセス禁止。
2. 冪等。毎回の Build で走り、以前のディスク状態の上でも動く。
3. Build 時にバックグラウンド実行。エージェント開始を待たせない。
4. 残るのはディスクだけ。プロセス・export したシェル変数・メモリキャッシュは引き継がない。
5. ネットワークが要る。egress 制限があるなら PyPI / GitHub / astral.sh 等を許可する。
6. 旧名は update script。失敗しても active Build は置き換わらない。

文書に無いもの: タイムアウト秒数、非対話制約の明示。Build は無人なのでプロンプト待ちは失敗する。

### environment.json / Dockerfile / snapshot / Build

| 層 | 何か | いつ使う |
| --- | --- | --- |
| `.cursor/environment.json` | リポジトリにコミットする設定。解決順の最優先 | チームで共有したい install / start / Dockerfile / snapshot 参照 |
| Dockerfile (`build`) | ベース OS などシステム層 | デフォルト Ubuntu では足りないとき |
| `snapshot` | ダッシュボードで保存した VM ディスク ID | agent-driven setup の成果を固定するとき |
| `image` | 既存レジストリイメージ | 自前ベースイメージがあるとき |
| Build | ベース + clone + `install` の起動可能なディスク | エージェントは active Build から起動 |

解決順: リポジトリの `environment.json` → personal saved environment → team saved environment。
`snapshot` があるとき `build` / `image` より優先。Build は snapshot / Dockerfile の代替ではない。

Dockerfile にプロジェクト全体を `COPY` してはいけない。Cursor がワークスペースを管理する。

### AGENTS.md との関係

Cloud agents は `AGENTS.md` を読む。Cloud 専用の節名として
`Cursor Cloud specific instructions` が推奨されている。
`environment.json` は機械の準備、`AGENTS.md` はエージェントへの手順。

## sources

- https://cursor.com/docs/cloud-agent/setup
- https://www.cursor.com/schemas/environment.schema.json
- https://cursor.com/docs/cloud-agent/builds
- https://cursor.com/docs/cloud-agent/security-network
- https://cursor.com/docs/cloud-agent/security
- https://cursor.com/docs/cloud-agent/best-practices
- https://cursor.com/docs/cloud-agent/settings
- https://cursor.com/docs/cloud-agent/api/endpoints
- https://cursor.com/docs/rules
- https://cursor.com/dashboard/cloud-agents
- https://forum.cursor.com/t/cloud-agent-does-not-auto-start-terminals-from-repo-managed-environment-json-builds-enabled/168876 （terminals と start の非公式制約）

## gaps

- `install` の公式タイムアウト秒数。
- 既定 Ubuntu イメージに uv / pnpm が最初から入っているか（文書に専用記載なし）。
- `egressAllowlist` がワイルドカードを受け付けるか。
