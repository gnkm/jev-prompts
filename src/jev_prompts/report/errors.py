# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""公開レポートの入力・出力契約。"""


class ReportError(ValueError):
    """公開物に本文が残る、またはレポートの入力が足りない。"""
