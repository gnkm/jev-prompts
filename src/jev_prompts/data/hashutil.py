"""本文から content_hash を取る。ハッシュだけ台帳に残し、本文は残さない。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from jev_prompts.data.schema import TaskId


def sha256_text(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def content_payload(task: TaskId, record: dict[str, Any]) -> str:
    """抽出対象レコードの本文を、ハッシュ用の正規文字列にする。"""
    if task == "choice":
        return str(record["text"])
    if task == "noul":
        return str(record["message"])
    if task == "score":
        return json.dumps(
            {
                "description": record["description"],
                "query": record["query"],
                "title": record["title"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    raise ValueError(f"未知の課題: {task}")


def content_hash(task: TaskId, record: dict[str, Any]) -> str:
    return sha256_text(content_payload(task, record))
