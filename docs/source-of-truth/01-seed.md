---
title: Jev プロンプト実験プロジェクト仕様書草案
description: Jev のプロンプト実験を始めるにあたっての原案
created at: 2026-09-21
---

# Jev プロンプト実験プロジェクト仕様書草案

## 目的

Jev の性能を最大限引き出す方法を知る。

## 成果物

- 課題セット 3 式
  - 実験結果レポート
  - プロンプト
  - 推論用コード
  - 精度評価用コード
  - テストコード
  - CI 設定
- 使用方法のドキュメント
- ライセンスファイル

## 技術スタック

- Python
- uv(`uv pip` 禁止)
- pytest
- Ruff
- Import Linter
- Radon
- Xenon
- [reuse lint](https://reuse.readthedocs.io/en/stable/man/reuse-lint.html)
- Podman(`podman secret`)
- OpenRouter

## ライセンス

- src(ソースコード): MIT
- prompts(プロンプト): CC0-1.0
- results(実験結果): CC BY 4.0

## 参照

- [REUSE Specification – Version 3.3](https://reuse.software/spec-3.3/)

### Typesafe Master customer agreement

> TypeSafe’s Confidential Information includes the Access Credentials, Documentation, Customer’s Fees and all pricing information, the terms and conditions of this Agreement, and other non-public information with respect to the Services or any other TypeSafe product or service.
