<!--
SPDX-FileCopyrightText: 2026 gnkm

SPDX-License-Identifier: CC0-1.0
-->

# プロンプト

人が読むプロンプトの正本。ライセンスは CC0-1.0。
`src/` はここを読むだけにし、条件の差分を Python でその場生成しない。

## 配置

| パス | 中身 |
| --- | --- |
| `choice/` `score/` `noul/` | 条件 A / B1 / B2 / B3 / C の `state` と `questions` |
| `llm/<task>/` | 条件 L1 / L2 / L3 の `llm_messages` |
| `creation_time.json` | 条件 A と L2 の作成時間（分）。本編セッション後に再構成した概算 |

Choice の A は BANKING77 の 77 意図に `other` を足す。混同しやすい意図だけ `what` / `not_for` / `examples` にし、残りは 1 行説明。B1 / B2 は 77 意図のみ（`other` なし）。Score と Noul は各 1 問の本編。

A から動かす軸は 1 つだけにする。

- B1 / B2 / B3 は `state` を A と同一にし、`questions` だけを変える。
- B2 は `instructions` を A と同一にし、`criteria` だけを変える。
- C は `questions` を A と同一にし、`state` のキーだけを増やす。
- L3 は L2 と同じメッセージにする（モデルの差はカタログに書かない）。
