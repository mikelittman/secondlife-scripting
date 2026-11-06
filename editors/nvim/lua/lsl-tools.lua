-- Point Neovim at the LSL tree-sitter grammar and the shared language server.
-- SLua reuses the upstream Luau parser; its queries add the Second Life libraries.

local parser_config = require("nvim-treesitter.parsers").get_parser_configs()
parser_config.lsl = {
  install_info = {
    url = "https://github.com/mikelittman/secondlife-scripting",
    location = "languages/lsl",
    branch = "main",
    files = { "src/parser.c" },
  },
  filetype = "lsl",
}

local configs = require("lspconfig.configs")
local util = require("lspconfig.util")
if not configs.lsl_tools then
  configs.lsl_tools = {
    default_config = {
      cmd = { "lsl-tools", "lsp" },
      filetypes = { "lsl", "slua", "luau" },
      root_dir = util.root_pattern(".git"),
      single_file_support = true,
    },
  }
end
require("lspconfig").lsl_tools.setup({})
