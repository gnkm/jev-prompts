---
title: REUSE Specification 3.3 と reuse lint
queried at: 2026-09-21
agent: web-reader
query: REUSE 3.3 でファイルを適法にする方法、REUSE.toml、LICENSES/、SPDX タグ、reuse lint の対象。
---

# REUSE Specification 3.3 と reuse lint

調査日 2026-09-21。正本ではなく、その時点の公開仕様とツール文書の記録。
`reuse.software` への直接取得は拒否されたため、公式サイト／ツールの GitHub ソースで確認した。

## claims

- Covered File には Licensing Information が必須。手段はコメントヘッダー（推奨）、隣接 `.license`、祖先の `REUSE.toml`。DEP5 は deprecated で `REUSE.toml` と同時使用不可。
- `REUSE.toml` は `version = 1`。`path` は `/` 区切り glob。同一ファイルに複数テーブルがマッチしたら最後のテーブルだけを使う。`precedence` は `closest`（既定）/ `aggregate` / `override`。
- 使うライセンス全文はルート `LICENSES/` に SPDX ID + 拡張子で置く（`MIT.txt`、`CC0-1.0.txt`、`CC-BY-4.0.txt`）。参照されない License File は置いてはならない。ライセンス文は無改変。ヘッダーは付けない。
- ルートの `LICENSE` / `COPYING` は Covered File ではない。GitHub 向けに残してよい。
- zero-byte ファイルとシンボリックリンクは Covered File ではない。VCS 無視ファイルも対象外。`REUSE.toml` 自体も対象外。
- PyPI パッケージ名は `reuse`。公式例は `pipx` / `pip`。`uv run reuse lint` という記載は無い。
- 推奨ヘッダー例: `SPDX-FileCopyrightText: 2019 Jane Doe` と `SPDX-License-Identifier: MIT`。
- ディレクトリ単位の一括付与は FAQ の `REUSE.toml` glob が公式のやり方。

## sources

- https://reuse.software/spec-3.3/
- https://reuse.software/faq/
- https://reuse.software/tutorial/
- https://reuse.readthedocs.io/en/stable/man/reuse-lint.html
- https://reuse.readthedocs.io/en/stable/man/reuse-download.html
- https://pypi.org/project/reuse/

## gaps

- 公式ページに空ディレクトリ / `.gitkeep` という語は無い。
- 公式ページに `uv run reuse lint` の記載は無い。
