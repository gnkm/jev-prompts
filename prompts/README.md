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

各タイプ 1 問のフィクスチャである。BANKING77 の 77 意図など本編の中身は後続。

A から動かす軸は 1 つだけにする。

- B1 / B2 / B3 は `state` を A と同一にし、`questions` だけを変える。
- B2 は `instructions` を A と同一にし、`criteria` だけを変える。
- C は `questions` を A と同一にし、`state` のキーだけを増やす。
- L3 は L2 と同じメッセージにする（モデルの差はカタログに書かない）。
