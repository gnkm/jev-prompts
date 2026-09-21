# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""対応あり検定の回数・水準。合格判定は置かない。"""

from typing import Final

from jev_prompts.config.openrouter import MAIN_SEED

BOOTSTRAP_REPLICATES: Final = 10_000
CI_LEVEL: Final = 0.95
BASELINE_CONDITION: Final = "A"
STATS_SEED: Final = MAIN_SEED
