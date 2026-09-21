# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""リポジトリ内の固定パス。秘匿情報は置かない。"""

from pathlib import Path

# src/jev_prompts/config/paths.py → リポジトリルート
REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_DIR = REPO_ROOT / "prompts"
LOCAL_LOGS_DIR = REPO_ROOT / "data" / "logs"
RESULTS_DIR = REPO_ROOT / "results"
