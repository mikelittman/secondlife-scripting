use std::env;

use zed_extension_api::{self as zed, Command, LanguageServerId, Result, Worktree};

struct LslSluaExtension;

impl zed::Extension for LslSluaExtension {
    fn new() -> Self {
        Self
    }

    fn language_server_command(
        &mut self,
        _language_server_id: &LanguageServerId,
        worktree: &Worktree,
    ) -> Result<Command> {
        let mut env = worktree.shell_env();
        if let Some(path) = worktree.which("lsl-tools") {
            return Ok(Command {
                command: path,
                args: vec!["lsp".into()],
                env,
            });
        }

        // Gram checks this extension out as its working directory, which contains lsl_tools.
        let extension_dir = env::current_dir().map_err(|error| error.to_string())?;
        env.push(("PYTHONPATH".into(), extension_dir.to_string_lossy().into_owned()));
        let python = worktree
            .which("python3")
            .unwrap_or_else(|| "python3".to_string());
        Ok(Command {
            command: python,
            args: vec!["-m".into(), "lsl_tools".into(), "lsp".into()],
            env,
        })
    }
}

zed::register_extension!(LslSluaExtension);
