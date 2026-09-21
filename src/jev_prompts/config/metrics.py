# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""指標の閾値。合格ラインは置かない。"""

from typing import Final

CONFIDENT_THRESHOLD: Final = 0.9
ECE_BINS: Final = 10
NOUL_DECISION_THRESHOLD: Final = 0.5
TOKENS_PER_THOUSAND: Final = 1000
LATENCY_P50: Final = 0.5
LATENCY_P95: Final = 0.95
