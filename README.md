# Jev プロンプト実験

![CI](https://github.com/gnkm/jev-prompts/actions/workflows/ci.yml/badge.svg)

Jev に 3 つの課題を与え、精度の評価をおこなう。
課題解決にあたって、Jev にはいくつかのプロンプトを与え、プロンプトの効果を評価できるようにする。

成果物は CLI（Typer）と `results/` の markdown レポートである。結果の把握は markdown を読む。
図が必要な箇所は画像を生成してそのファイルから参照する。Web UI は提供しない。
表の処理は Polars を使う。

Python パッケージ `jev_prompts` の骨格（uv / pytest / Ruff / Typer / Polars）と、ケースネストの実験ランナーがある。集計・検定の本実装は後続。
入口は `python -m jev_prompts`（Typer）。準備は `fetch`、実行は `preflight` / `run` / `fanout` で切り分ける。ロジックは `jev_prompts` に置き、`scripts/` は薄い入口である。
パッケージは `report → stats → metrics → runners → prompts → clients → data → config` の一方向レイヤで、Import Linter が逆向きの import を止める。
ケース台帳は `case_id` / split / gold / content_hash / 抽出シードを Polars で扱う。本文は同梱しない。
`python -m jev_prompts fetch`（または `scripts/fetch_data.py`）が BANKING77 / Amazon ESCI / SMS Spam を `data/raw/` へ取得し、台帳のハッシュと照合する。
プロンプトの正本は `prompts/` の JSON である。`src/jev_prompts/prompts` はそこを読むだけで、A からの 1 軸差分を Python でその場生成しない。Choice の A は BANKING77 の 77 意図と `other`、B1 / B2 は 77 意図のみ。L2 の作成時間は `prompts/creation_time.json` に分で残す。
実験ランナーはケースごとに全条件を連続実行し、1 リクエスト 1 行を Polars で書く。`probabilities` は必須。`state_json` / `question_json` は `data/logs/` のローカルログだけに置き、公開用 `PublishedRecord` に本文キーは無い。
GitHub Actions は Biome、pytest、Ruff、Import Linter、reuse lint を `main` と pull request で実行する。ライブ API と実ネットでのデータ取得は既定の CI に載せない。

## セットアップ

Python 3.12 と [uv](https://docs.astral.sh/uv/) を使う。`uv pip` は使わない。

```bash
uv python install 3.12
uv sync
```

テストと lint:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run lint-imports
uv run reuse lint
```

## CLI

入口は `uv run python -m jev_prompts`。`--help` に System One（`systemone`）と比較用 LLM（`chat`）のモデル ID が出る。

準備と実行を混ぜない。配布元からの取得はクローン後（または台帳を変えるとき）に一度だけ行い、本ランは `data/` だけを読む。

```bash
# 準備（Hugging Face / GitHub / UCI から data/raw へ。API キーは不要）
uv run python -m jev_prompts fetch
# 同等の薄い入口: uv run python scripts/fetch_data.py

# 実行（OPENROUTER_API_KEY と本文が要る。無ければ非ゼロ終了）
uv run python -m jev_prompts preflight
uv run python -m jev_prompts run
uv run python -m jev_prompts fanout
```

- `preflight`: 決定性・トークン上限（32k）・応答のモデル版を事前確認する。失敗したら本ランに進まない。
- `run`: ケースごとに全条件を連続実行する精度比較。fan-out は含めない。
- `fanout`: A の質問群を 1 回にまとめる / 分割する別ラン。コスト・遅延・一致率だけを見る。

キーは環境変数 `OPENROUTER_API_KEY`（再現ランでは Podman secret）。本文が無い、ハッシュが台帳と一致しない、台帳が無い、または空なら実行系は失敗する。暗黙の再取得はしない。

ライブ API は既定の CI に載せない。

## プロンプト

実験条件の正本は `prompts/` にある。課題タイプ（`choice` / `score` / `noul`）ごとに A〜C、比較用 LLM は `prompts/llm/<task>/` に L1〜L3 を置く。

- B2 は A と `instructions` が同一で、`criteria` だけが違う。
- C は A と `questions` が同一で、`state` のキーだけが増える。Choice の C は約 2,000 トークン相当の規約ノイズを `terms_of_service` に置く。
- L2 作成時間は `prompts/creation_time.json` の各課題の `L2`（単位は分）。
- ランナーはカタログを読み、欠けた `questions` を A から補完しない。

読み出しは `jev_prompts.prompts.load_bundle`。中身の改訂は JSON を編集する。

## ランナーとログ

`jev_prompts.runners.run_experiment` は課題→条件→ケースではなく、**ケースごとに全条件を連続**で回す。同じケースを全条件に流し、対応のある比較にする。1 リクエスト 1 行。表の正本は Polars。

- `probabilities` は全件必須。落とすと Score の解釈ができない。
- 再集計用のフルログ（`state_json` / `question_json` を含む）は `data/logs/` に書く。gitignore 済みでコミットしない。
- 公開用の `PublishedRecord` は本文キーを持たない。`content_hash` と測定値だけを `results/` に置く。

ライブ API は既定の CI に載せない。ランナーのユニットテストは execute を差し込み、実行順とスキーマだけを固定する。

## データ

本文は同梱しない。`data/raw/` は gitignore している。Git に入るのはケース台帳
（`data/cases/` の `case_id` / split / gold / content_hash / 抽出シード）だけである。

クローン後（または別マシンで再現するとき）に、配布元から取得してハッシュを照合する。

```bash
uv run python -m jev_prompts fetch
```

`scripts/fetch_data.py` も同じ fetch の薄い入口である。
ハッシュが台帳と一致しない、台帳が無い、または空ならコマンドは失敗する。
実験ランナーは `data/` だけを読み、Hugging Face / GitHub / UCI には触れない。
本文が無ければ失敗し、暗黙の再取得はしない。

実ネットでの取得は任意で、既定の CI には含めない。ユニットテストはフィクスチャで
ハッシュ不一致と展開先を検証する。

抽出は課題あたりランダム + 境界、gold で層化した dev / test を小さなフィクスチャで再現する。
テスト用の合成本文は実行時に組み立て、データセット本文はリポジトリに置かない。
出典とライセンスは [DATA_LICENSES.md](DATA_LICENSES.md)。

## 比較用 LLM

比較用 LLM は GPT-5.6 Luna（条件 L1 / L2）と Claude Sonnet 5（条件 L3）。
評価設計書の L1 / L2 に L3 を足し、実験は 8 条件である。選定の正本は
[ADR-0002](docs/adr/competitor-llm.md)、実装上の境界は [ARCHITECTURE.md](ARCHITECTURE.md)。

| 条件 | モデル | モデル ID | 固定プロバイダ |
| --- | --- | --- | --- |
| L1 / L2 | GPT-5.6 Luna | `openai/gpt-5.6-luna` | OpenAI |
| L3 | Claude Sonnet 5 | `anthropic/claude-sonnet-5` | Anthropic |

OpenRouter で呼び、`provider.order` を上表のプロバイダに固定する。
`allow_fallbacks` は false、`require_parameters` は true、`data_collection` は deny。
エイリアスは使わない。

## OpenRouter クライアント

推論の出口は OpenRouter だけ。HTTP クライアントは 1 本で、失敗しても再試行しない。
キーは環境変数 `OPENROUTER_API_KEY`（再現ランでは Podman secret）のみ。リポジトリに置かない。
テストは HTTP をモックし、既定の CI は実ネットに出ない。パース失敗は例外を返し、呼び出し側が不正解にする。

| 用途 | メソッド | URL | モデル ID |
| --- | --- | --- | --- |
| Jev（条件 A〜C） | POST | `https://openrouter.ai/api/v1/systemone` | `typesafe/jev-1.13` |
| 比較用 LLM（L1 / L2） | POST | `https://openrouter.ai/api/v1/chat/completions` | `openai/gpt-5.6-luna` |
| 比較用 LLM（L3） | POST | `https://openrouter.ai/api/v1/chat/completions` | `anthropic/claude-sonnet-5` |

Jev 用の呼び出しに Chat Completions の URL は使わない。`~typesafe/jev-latest` などのエイリアスも使わない。

## 評価の統計

同じケースを条件 A 対 B1 のように 2 条件で比べるときは、当たり外れの差に McNemar、指標の幅にブートストラップ、複数回の判定に Holm を使う。解説は [docs/statistical-methods.md](docs/statistical-methods.md)、位置づけは [ARCHITECTURE.md](ARCHITECTURE.md) の統計節。

## コントリビューション

ブランチ命名とコミット規約は [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。

## ライセンス

ディレクトリごとにライセンスが異なります。REUSE の SPDX 識別子をファイルに付け、全文は `LICENSES/` に置きます。検証は `uv run reuse lint` です。

- `src/`: MIT
- `prompts/`: CC0-1.0
- `results/`: CC-BY-4.0

その他のリポジトリファイル（テスト、ドキュメント、設定など）は MIT です。
GitHub のサイドバーはルートの MIT のみを表示しますが、MIT が全体に及ぶわけではありません。
元データは同梱しておらず、各データセットのライセンスは `DATA_LICENSES.md` を参照ください。
