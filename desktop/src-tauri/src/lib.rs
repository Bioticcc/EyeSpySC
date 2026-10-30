//! EyeSpySC desktop shell. All counting happens in the bundled `eyespysc`
//! command-line tool, run once per job (a one-shot CLI sidecar). The CLI prints
//! one JSON object per line with `--json-progress`; these are forwarded to the
//! window unchanged.

use std::collections::VecDeque;
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};

use serde_json::Value;
use tauri::ipc::Channel;
use tauri::{AppHandle, Manager, RunEvent};

/// The one CLI process that may run at a time (previews or a count).
#[derive(Default)]
struct RunState {
    child: Arc<Mutex<Option<Child>>>,
}

/// Packaged builds install the CLI next to the app binary (`/usr/bin/eyespysc`).
/// Development builds use `EYESPYSC_CLI`, or else the backend virtualenv.
fn cli_path() -> Result<PathBuf, String> {
    if cfg!(debug_assertions) {
        if let Some(path) = std::env::var_os("EYESPYSC_CLI") {
            return Ok(PathBuf::from(path));
        }
        return Ok(Path::new(env!("CARGO_MANIFEST_DIR")).join("../../backend/.venv/bin/eyespysc"));
    }
    let executable = std::env::current_exe()
        .map_err(|error| format!("Could not locate the EyeSpySC program: {error}"))?;
    let directory = executable
        .parent()
        .ok_or("Could not locate the EyeSpySC program folder.")?;
    Ok(directory.join("eyespysc"))
}

/// The last lines the CLI wrote to stderr, for error messages.
fn stderr_summary(lines: &VecDeque<String>) -> String {
    let message = lines
        .iter()
        .rev()
        .find(|line| !line.trim().is_empty())
        .map(|line| line.trim().to_string())
        .unwrap_or_default();
    if message.is_empty() {
        "The counting program stopped unexpectedly.".to_string()
    } else {
        message
    }
}

fn run_cli(state: &RunState, args: Vec<String>, on_event: &Channel<Value>) -> Result<(), String> {
    let cli = cli_path()?;
    if !cli.is_file() {
        return Err(format!("The counting program is missing: {}", cli.display()));
    }
    let mut slot = state.child.lock().map_err(|_| "Run state is unavailable.")?;
    if slot.is_some() {
        return Err("EyeSpySC is already working on images. Wait for it to finish.".to_string());
    }
    let mut child = Command::new(&cli)
        .args(&args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("Could not start the counting program: {error}"))?;
    let stdout = child.stdout.take().ok_or("The counting program has no output.")?;
    let mut stderr = child.stderr.take().ok_or("The counting program has no error output.")?;
    *slot = Some(child);
    drop(slot);

    let stderr_reader = std::thread::spawn(move || {
        let mut text = String::new();
        let _ = stderr.read_to_string(&mut text);
        let mut tail = VecDeque::new();
        for line in text.lines() {
            tail.push_back(line.to_string());
            if tail.len() > 20 {
                tail.pop_front();
            }
        }
        tail
    });

    let mut send_error = None;
    for line in BufReader::new(stdout).lines() {
        let Ok(line) = line else { break };
        let Ok(event) = serde_json::from_str::<Value>(&line) else { continue };
        if let Err(error) = on_event.send(event) {
            send_error = Some(error.to_string());
            break;
        }
    }

    let status = {
        let mut slot = state.child.lock().map_err(|_| "Run state is unavailable.")?;
        let status = match slot.as_mut() {
            Some(child) => {
                if send_error.is_some() {
                    let _ = child.kill();
                }
                child.wait().map_err(|error| error.to_string())
            }
            None => Err("The run was stopped.".to_string()),
        };
        *slot = None;
        status
    };
    let tail = stderr_reader.join().unwrap_or_default();
    if let Some(error) = send_error {
        return Err(format!("The window stopped listening to the run: {error}"));
    }
    match status {
        Ok(status) if status.success() => Ok(()),
        Ok(_) => Err(stderr_summary(&tail)),
        Err(error) => Err(error),
    }
}

fn input_args(inputs: &[String]) -> Result<Vec<String>, String> {
    if inputs.is_empty() {
        return Err("Choose at least one image or folder.".to_string());
    }
    let mut args = Vec::new();
    for input in inputs {
        if !Path::new(input).is_absolute() {
            return Err(format!("Image paths must be absolute: {input}"));
        }
        args.push("--input".to_string());
        args.push(input.clone());
    }
    Ok(args)
}

/// Let the window load images (previews, overlays) from this folder only.
fn allow_images_from(app: &AppHandle, folder: &Path) -> Result<(), String> {
    app.asset_protocol_scope()
        .allow_directory(folder, true)
        .map_err(|error| format!("Could not allow images from {}: {error}", folder.display()))
}

/// Write an 8-bit preview and thumbnail of every image into the app cache,
/// replacing the previous selection's previews. Each selection gets a new
/// folder, so the window never shows a cached image from an earlier one.
#[tauri::command]
async fn preview_images(
    app: AppHandle,
    inputs: Vec<String>,
    on_event: Channel<Value>,
) -> Result<(), String> {
    let mut args = input_args(&inputs)?;
    let cache = app
        .path()
        .app_cache_dir()
        .map_err(|error| format!("Could not find the cache folder: {error}"))?
        .join("previews");
    if cache.exists() {
        std::fs::remove_dir_all(&cache)
            .map_err(|error| format!("Could not clear old previews: {error}"))?;
    }
    std::fs::create_dir_all(&cache)
        .map_err(|error| format!("Could not create the cache folder: {error}"))?;
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_millis())
        .unwrap_or_default();
    let previews = cache.join(stamp.to_string());
    allow_images_from(&app, &previews)?;
    args.extend([
        "--output-root".to_string(),
        previews.to_string_lossy().into_owned(),
        "--preview-only".to_string(),
        "--json-progress".to_string(),
    ]);
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<RunState>();
        run_cli(&state, args, &on_event)
    })
    .await
    .map_err(|error| format!("The preview job could not finish: {error}"))?
}

/// Count sperm in every image, writing results to a new folder.
#[tauri::command]
async fn count_sperm(
    app: AppHandle,
    inputs: Vec<String>,
    output_root: String,
    on_event: Channel<Value>,
) -> Result<(), String> {
    let mut args = input_args(&inputs)?;
    let output = PathBuf::from(&output_root);
    if !output.is_absolute() {
        return Err("The results folder must be an absolute path.".to_string());
    }
    if output.exists() {
        return Err(format!("The results folder already exists: {output_root}"));
    }
    if let Some(parent) = output.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|error| format!("Could not create {}: {error}", parent.display()))?;
    }
    allow_images_from(&app, &output)?;
    args.extend([
        "--output-root".to_string(),
        output_root,
        "--minimal".to_string(),
        "--json-progress".to_string(),
    ]);
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<RunState>();
        run_cli(&state, args, &on_event)
    })
    .await
    .map_err(|error| format!("The count could not finish: {error}"))?
}

// Copied from Missus Tom (desktop/src-tauri/src/lib.rs, v0.4.8): WSL-aware folder opener.
fn is_wsl_release(release: &str) -> bool {
    let release = release.to_ascii_lowercase();
    release.contains("microsoft") || release.contains("wsl")
}

fn is_wsl() -> bool {
    if std::env::var_os("WSL_DISTRO_NAME").is_some() {
        return true;
    }
    ["/proc/sys/kernel/osrelease", "/proc/version"]
        .iter()
        .filter_map(|path| std::fs::read_to_string(path).ok())
        .any(|release| is_wsl_release(&release))
}

fn open_directory_blocking(path: &str) -> Result<(), String> {
    let requested = Path::new(path);
    if !requested.is_absolute() {
        return Err("The folder path must be absolute.".to_string());
    }
    let canonical = requested
        .canonicalize()
        .map_err(|error| format!("Could not find the folder: {error}"))?;
    if !canonical.is_dir() {
        return Err("The requested path is not a folder.".to_string());
    }
    if is_wsl() {
        let converted = Command::new("wslpath")
            .arg("-w")
            .arg(&canonical)
            .output()
            .map_err(|error| format!("Could not convert the folder for Windows Explorer: {error}"))?;
        if !converted.status.success() {
            return Err(format!(
                "Could not convert the folder for Windows Explorer: {}",
                String::from_utf8_lossy(&converted.stderr).trim()
            ));
        }
        let windows_path = String::from_utf8_lossy(&converted.stdout).trim_end().to_string();
        // Explorer often exits non-zero even after opening the folder, so a
        // successful spawn is the success signal.
        Command::new("explorer.exe")
            .arg(windows_path)
            .spawn()
            .map_err(|error| format!("Could not start explorer.exe: {error}"))?;
        return Ok(());
    }
    let status = Command::new("xdg-open")
        .arg(&canonical)
        .status()
        .map_err(|error| format!("Could not start xdg-open: {error}"))?;
    if !status.success() {
        return Err(format!("xdg-open could not open the folder (exit status {status})."));
    }
    Ok(())
}

#[tauri::command]
async fn open_directory(path: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || open_directory_blocking(&path))
        .await
        .map_err(|error| format!("The folder opener could not finish: {error}"))?
}

fn stop_running_cli(state: &RunState) {
    if let Ok(mut slot) = state.child.lock() {
        if let Some(child) = slot.as_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }
        *slot = None;
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(RunState::default())
        .invoke_handler(tauri::generate_handler![
            preview_images,
            count_sperm,
            open_directory
        ])
        .build(tauri::generate_context!())
        .expect("EyeSpySC could not start")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                stop_running_cli(&app.state::<RunState>());
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stderr_summary_uses_last_non_empty_line() {
        let lines: VecDeque<String> = ["Traceback", "RuntimeError: Could not read image: a.tif", ""]
            .iter()
            .map(|line| line.to_string())
            .collect();
        assert_eq!(stderr_summary(&lines), "RuntimeError: Could not read image: a.tif");
        assert_eq!(
            stderr_summary(&VecDeque::new()),
            "The counting program stopped unexpectedly."
        );
    }

    #[test]
    fn input_args_require_absolute_paths() {
        assert!(input_args(&[]).is_err());
        assert!(input_args(&["relative.tif".to_string()]).is_err());
        assert_eq!(
            input_args(&["/data/a.tif".to_string(), "/data/b".to_string()]).unwrap(),
            vec!["--input", "/data/a.tif", "--input", "/data/b"]
        );
    }

    #[test]
    fn wsl_release_detection() {
        assert!(is_wsl_release("5.15.167.4-microsoft-standard-WSL2"));
        assert!(!is_wsl_release("6.1.0-25-amd64"));
    }
}
