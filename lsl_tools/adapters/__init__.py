"""Editor adapters. Each one turns the shared language packs into that editor's files."""

from lsl_tools.adapters.gram import GramAdapter
from lsl_tools.adapters.helix import HelixAdapter
from lsl_tools.adapters.nvim import NvimAdapter
from lsl_tools.adapters.vscode import VsCodeAdapter

ADAPTERS = {
    "gram": GramAdapter(),
    "vscode": VsCodeAdapter(),
    "helix": HelixAdapter(),
    "nvim": NvimAdapter(),
}
