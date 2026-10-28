# SPDX-License-Identifier: GPL-2.0-only
"""Load tablet/erhai-lab (a script without a .py suffix) as a module."""

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "tablet" / "erhai-lab"

_loader = importlib.machinery.SourceFileLoader("erhai_lab", str(TOOL))
_spec = importlib.util.spec_from_loader("erhai_lab", _loader)
lab = importlib.util.module_from_spec(_spec)
sys.modules["erhai_lab"] = lab
_loader.exec_module(lab)
