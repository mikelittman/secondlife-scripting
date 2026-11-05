use std::env;
use std::path::{Path, PathBuf};

use zed_extension_api::{self as zed, Command, LanguageServerId, Result, Worktree};

const EXTENSION_ID: &str = "lsl-slua";

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

        // Gram's Wasm process runs in extensions/work/<id>, which does not contain
        // the package. The checkout is the sibling directory extensions/installed/<id>.
        let home = env
            .iter()
            .find(|(name, _)| name == "HOME")
            .map(|(_, value)| value.clone());
        let pythonpath =
            env::join_paths(package_roots(home.as_deref())).map_err(|error| error.to_string())?;
        upsert_env(
            &mut env,
            "PYTHONPATH",
            pythonpath.to_string_lossy().into_owned(),
        );
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

fn package_roots(home: Option<&str>) -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if let Ok(pwd) = env::var("PWD") {
        push_package_roots(&mut roots, Path::new(&pwd));
    }
    if let Ok(cwd) = env::current_dir() {
        push_package_roots(&mut roots, &cwd);
    }
    if let Some(home) = home {
        let home = Path::new(home);
        for relative in [
            "Library/Application Support/Gram/extensions/installed",
            ".config/gram/extensions/installed",
            ".local/share/gram/extensions/installed",
        ] {
            roots.push(home.join(relative).join(EXTENSION_ID));
        }
    }
    roots
}

fn push_package_roots(roots: &mut Vec<PathBuf>, dir: &Path) {
    let installed = dir
        .parent()
        .and_then(Path::parent)
        .map(|extensions| extensions.join("installed").join(EXTENSION_ID));
    if let Some(installed) = installed {
        roots.push(installed);
    }
    roots.push(dir.to_path_buf());
}

fn upsert_env(env: &mut Vec<(String, String)>, key: &str, value: String) {
    if let Some((_, existing)) = env.iter_mut().find(|(name, _)| name == key) {
        if existing.is_empty() {
            *existing = value;
        } else {
            *existing = format!("{value}{sep}{existing}", sep = env_path_separator());
        }
    } else {
        env.push((key.to_string(), value));
    }
}

fn env_path_separator() -> &'static str {
    if cfg!(windows) { ";" } else { ":" }
}

zed::register_extension!(LslSluaExtension);
