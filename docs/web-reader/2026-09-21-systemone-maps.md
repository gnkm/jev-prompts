---
title: System One の questions / answers は ID キーの map
queried at: 2026-09-21
agent: web-reader
query: TypeSafe / OpenRouter の System One で questions と answers は配列か質問 ID の map か。
---

# System One の questions / answers は ID キーの map

調査日 2026-09-21。正本ではなく、その時点の公開ドキュメントの記録。

## claims

- TypeSafe `POST /v1/systemone` の `questions` は JSON object（質問 ID → question）。array ではない。
- 応答の `answers` も同じ ID をキーにした object。answer オブジェクト自身に質問 ID フィールドは無い。
- Python SDK の `system_one` は `Mapping[str, Question]`。応答 `answers` は `dict[str, Answer]`。
- OpenRouter `POST /api/v1/systemone` は TypeSafe と同じ shape。例も ID キーの object。
- OpenRouter Alpha Decisions も OpenAPI 上は object + additionalProperties。array 定義ではない。
- Noul answer は `type` と `noul`。Choice は `choice` / `confidence` / `probabilities`。Score はそれらに加え `legend`。

## sources

- https://docs.typesafe.ai/api.md
- https://docs.typesafe.ai/sdk/python/usage.md
- https://docs.typesafe.ai/sdk/python/api/types/responses.md
- https://docs.typesafe.ai/sdk/python/api/clients/sync.md
- https://openrouter.ai/docs/guides/community/typesafe-sdk
- https://openrouter.ai/docs/client-sdks/python/sdks/systemone/README.md
- https://openrouter.ai/docs/client-sdks/python/components/decisionsresponse.md
- https://openrouter.ai/docs/client-sdks/python/components/questions.md
- https://openrouter.ai/docs/client-sdks/python/components/answers.md
- https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-questions-and-answers-request.md

## observed_instructions

- TypeSafe / OpenRouter の docs index（llms.txt）を先に取れという案内。実行していない。

## gaps

- `questions` を JSON array で送ったときの HTTP ステータスは未記載。
- TypeSafe JSON schema の `answers` required と HTTP 文面が一致しない。
