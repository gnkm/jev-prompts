---
title: OpenRouter 上の Jev の呼び出し方
queried at: 2026-09-21
agent: web-reader
query: TypeSafe Jev は OpenRouter でどう公開されているか。モデル slug、state+questions か Chat Completions か、型付き応答、料金、エイリアス。
---

# OpenRouter 上の Jev の呼び出し方

調査日 2026-09-21。正本ではなく、その時点の公開ドキュメントと Models API の記録。

## claims

### 掲載と slug

- OpenRouter のモデルカタログで `jev` を探すと、カテゴリ Decisions に 2 件ある。
- OpenRouter 上の ID:
  - `typesafe/jev-1.13`（正規 slug は `typesafe/jev-1.13-20260917`）
  - `~typesafe/jev-latest`（エイリアス。`alias_target.slug` は `typesafe/jev-1.13`）
- Models API 上の architecture は `text->decisions`。`output_modalities: ["decisions"]`。
- 既定の `GET /api/v1/models`（チャット系 446 件）には載らない。
  `GET /api/v1/models?output_modalities=decisions` で 2 件出る。
  フィルタなしの `GET /api/v1/models/typesafe/jev-1.13` は 404。
- TypeSafe 公式側の名前は異なる。版付きは `jev-1.13.0`。エイリアス `jev-latest` と
  `jev-preview` は調査時点でどちらも `jev-1.13.0`。Python SDK の既定は `jev-latest`。
  利用ガイドの `TypeSafeClient(model="jev")` の裸の `jev` は OpenRouter のカタログ ID ではない。

### 呼び出し方（Chat Completions ではない）

OpenRouter はチャット以外のエンドポイントを 2 つ案内している。どちらも
`model` + `state` + `questions`（型は `noul` / `choice` / `score`）を送る。

**経路 A — OpenRouter Decisions API**

- `POST https://openrouter.ai/api/alpha/decisions`
- SDK: `openrouter.alpha.decisions.create(...)`。`model` は `typesafe/jev-1.13` または `~typesafe/jev-latest`
- モデルページは Decisions API であり、OpenAI 互換の chat エンドポイントではない、
  chat completions SDK では動かないと書いている。

**経路 B — OpenRouter System One API（TypeSafe SDK 互換）**

- `POST https://openrouter.ai/api/v1/systemone`
- 公式 TypeSafe クライアントを `base_url="https://openrouter.ai/api"` に向け、
  OpenRouter の API キーを使う（SDK が `/v1/systemone` を付ける）。
- OpenRouter が書く ID 写像: `jev-1.13` → `typesafe/jev-1.13`、
  `jev-latest` → `~typesafe/jev-latest`。すでに接頭辞付きならそのまま。

**TypeSafe 公式 SDK（OpenRouter を使わない直叩き）**

- 既定 `base_url`: `https://api.typesafe.ai`
- `client.system_one(state, questions)`。`Noul` / `Choice` / `Score`（または dict）
- HTTP: `POST https://api.typesafe.ai/v1/systemone`
- 認証: `TYPESAFE_API_KEY`。既定モデル `jev-latest`

### 応答の形

自由記述のチャットではなく、型付きの answers。

OpenRouter Decisions の 200 例:

- `id`、`model`（`typesafe/jev-1.13-20260917`）、`provider`（`TypeSafe`）、
  `answers`、`usage`（`input_tokens` / `output_tokens` / `cost`）
- noul: `{ "type": "noul", "noul": 0.96 }`
- choice: `{ "type": "choice", "choice": "…", "confidence": …, "probabilities": {…} }`
- score: `{ "type": "score", "score": …, "confidence": …, "legend": {…}, "probabilities": {…} }`

TypeSafe 公式の 200 例は同じ answer オブジェクトから OpenRouter 固有欄
（`id` / `provider` / `usage.cost`）を除いた形。応答の `model` は `jev-1.13.0`。
どちらの API でも Noul に `confidence` は無い。

### TypeSafe 公式は OpenRouter を案内しているか

- `https://docs.typesafe.ai/llms.txt` に SDK・HTTP API・models・primitives はある。
  OpenRouter のページは無い。
- `https://docs.typesafe.ai/sdk/python/usage.md` は `api.typesafe.ai` 直叩きのみ
  （`TYPESAFE_BASE_URL` の既定は `https://api.typesafe.ai`）。OpenRouter の言及なし。
- `site:docs.typesafe.ai openrouter` はヒットなし。
- OpenRouter 側は TypeSafe SDK を経路として案内している:
  `https://openrouter.ai/docs/guides/community/typesafe-sdk`

### 料金・コンテキスト・エイリアス

| 項目 | OpenRouter | TypeSafe 公式 |
| --- | --- | --- |
| 入力 | $0.042 / 1M（`pricing.prompt` = トークンあたり `0.000000042`） | $0.042 / 1M（$42 / Btok） |
| 出力 | $0 | $0 |
| 掲載コンテキスト | 32,000 | 1 リクエスト 64k。`state` + 最長の質問は 32k |
| `jev-latest` | あり。`~typesafe/jev-latest` → `typesafe/jev-1.13` | あり。エイリアス → `jev-1.13.0` |
| `jev-1.13` | あり。`typesafe/jev-1.13` | 版付き名は `jev-1.13.0` |
| `jev-preview` | OpenRouter カタログに無い | あり（調査時点では `jev-latest` と同じ） |
| 掲載日 | 2026-09-18 | — |

OpenRouter `top_provider.max_completion_tokens`: 28800。
TypeSafe 公式のレート制限（250k tokens/s、1200 rpm）が OpenRouter にも載るかは未確認。

### 注意点

- Chat Completions ではない。chat SDK では動かない（モデルページ）。
  プロバイダ一覧の FAQ は「OpenAI 互換 API」と `https://openrouter.ai/api/v1` と書いており、
  モデルページと食い違う。
- 既定の Models API は `output_modalities=decisions` を付けないと Jev を返さない。
- TypeSafe SDK の `client.models.list()` を OpenRouter に向けると、OpenRouter の
  Models API 形になって拒否される。`/typesafe` を見るか Models API を直接呼ぶ。
- 応答の `model` 文字列が違う。OpenRouter は `typesafe/jev-1.13-20260917`、
  TypeSafe 直は `jev-1.13.0`。
- OpenRouter は `id` / `provider` / `usage.cost` を足す。
- プロバイダは 1 つ。OpenRouter は全リクエストを TypeSafe に転送し、経路選択は無い。
  ページ上の P50 レイテンシは 0.26s。`api.typesafe.ai` 直叩きとの差は文書化されていない。
- Choice / Score の probabilities と confidence は OpenRouter Decisions の OpenAPI 例に
  ある。欠けるとは書かれていない。Noul に probabilities / confidence が無いのは TypeSafe と同じ。
- SNS では掲載を beta と呼ぶ投稿がある。プロダクトページはその語を使っていない。

## sources

- https://openrouter.ai/models?q=jev
- https://openrouter.ai/typesafe
- https://openrouter.ai/typesafe/jev-1.13
- https://openrouter.ai/~typesafe/jev-latest
- https://openrouter.ai/docs/guides/community/typesafe-sdk
- https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-questions-and-answers-request.md
- https://openrouter.ai/docs/client-sdks/python/sdks/decisions/README.md
- https://openrouter.ai/docs/client-sdks/python/sdks/systemone/README.md
- https://openrouter.ai/docs/llms.txt
- https://openrouter.ai/api/v1/models?output_modalities=decisions
- https://openrouter.ai/api/v1/models/typesafe/jev-1.13-20260917/endpoints
- https://openrouter.ai/
- https://docs.typesafe.ai/llms.txt
- https://docs.typesafe.ai/sdk/python/usage.md
- https://docs.typesafe.ai/sdk/python.md
- https://docs.typesafe.ai/sdk/python/api/clients/sync.md
- https://docs.typesafe.ai/sdk/python/api/types/responses.md
- https://docs.typesafe.ai/sdk/python/api/constants.md
- https://docs.typesafe.ai/models.md
- https://docs.typesafe.ai/api.md
- https://docs.typesafe.ai/introduction/quickstart.md

## observed_instructions

- OpenRouter のページは API キーの export と Decisions / System One のサンプル送信を案内していた。実行していない。
- TypeSafe のページは `TYPESAFE_API_KEY` を置いて `api.typesafe.ai` へ POST する案内。実行していない。

## gaps

- Chat Completions で Jev を呼んだときの実際の HTTP エラー本文（文書上は動かない。4xx は未取得）。
- OpenRouter 経由で `client.system_one(..., model="jev")` が通るか（裸の `jev` は写像表に無い）。
- OpenRouter と `api.typesafe.ai` の実測レイテンシ差。
- OpenRouter が TypeSafe の 64k 全体 / 32k state+question 分割を守るか、掲載の 32k だけか。
- TypeSafe 公式が OpenRouter をサポート経路として認めているか（docs.typesafe.ai には無かった）。
- カタログに無い `jev-preview` を OpenRouter に送れるか。
- OpenRouter が TypeSafe の 250k tok/s・1200 rpm をそのまま適用するか。
