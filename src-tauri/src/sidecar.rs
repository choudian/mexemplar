use std::{
    env,
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    net::TcpListener,
    net::TcpStream,
    path::PathBuf,
    process::Command as StdCommand,
    sync::Mutex,
    time::{Duration, Instant},
};

use rand::{distributions::Alphanumeric, Rng};
use serde::Serialize;
use tauri::{AppHandle, Manager, State};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SidecarConfig {
    pub base_url: String,
    pub port: u16,
    pub session_token: String,
}

pub struct SidecarState {
    config: SidecarConfig,
    child: Mutex<Option<CommandChild>>,
}

impl SidecarState {
    fn new(config: SidecarConfig, child: CommandChild) -> Self {
        Self {
            config,
            child: Mutex::new(Some(child)),
        }
    }

    fn config(&self) -> SidecarConfig {
        self.config.clone()
    }

    pub fn kill(&self) {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(child) = guard.take() {
                kill_process_tree(child.pid());
                let _ = child.kill();
            }
        }
    }
}

pub fn kill_sidecar(app: &AppHandle) {
    if let Some(state) = app.try_state::<SidecarState>() {
        state.kill();
    }
}

impl Drop for SidecarState {
    fn drop(&mut self) {
        if let Ok(mut child) = self.child.lock() {
            if let Some(child) = child.take() {
                kill_process_tree(child.pid());
                let _ = child.kill();
            }
        }
    }
}

fn reserve_local_port() -> Result<u16, String> {
    let listener = TcpListener::bind(("127.0.0.1", 0)).map_err(|error| error.to_string())?;
    listener
        .local_addr()
        .map(|addr| addr.port())
        .map_err(|error| error.to_string())
}

fn generate_token() -> String {
    rand::thread_rng()
        .sample_iter(&Alphanumeric)
        .take(48)
        .map(char::from)
        .collect()
}

fn check_sidecar_health(port: u16, token: &str) -> bool {
    let addr = format!("127.0.0.1:{port}");
    let Ok(mut stream) = TcpStream::connect_timeout(
        &addr
            .parse()
            .unwrap_or_else(|_| ([127, 0, 0, 1], port).into()),
        Duration::from_millis(300),
    ) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let request = format!(
        "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-Mexemplar-Session: {token}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }

    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200")
}

fn spawn_health_poll(config: SidecarConfig) {
    tauri::async_runtime::spawn_blocking(move || {
        let deadline = Instant::now() + Duration::from_secs(20);
        while Instant::now() < deadline {
            if check_sidecar_health(config.port, &config.session_token) {
                return;
            }
            std::thread::sleep(Duration::from_millis(250));
        }
        eprintln!("Mexemplar sidecar health check did not become ready before timeout");
    });
}

fn open_sidecar_log(data_dir: &PathBuf) -> Result<File, String> {
    let log_dir = data_dir.join("logs");
    fs::create_dir_all(&log_dir).map_err(|error| error.to_string())?;
    OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join("sidecar.log"))
        .map_err(|error| error.to_string())
}

fn write_sidecar_output(log: &mut File, stream: &str, bytes: &[u8]) {
    let _ = write!(log, "[{stream}] ");
    let _ = log.write_all(bytes);
    if !matches!(bytes.last(), Some(b'\n' | b'\r')) {
        let _ = writeln!(log);
    }
    let _ = log.flush();
}

fn resolve_sidecar_data_dir(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(configured) = env::var("EXEMPLAR_DATA_DIR") {
        let trimmed = configured.trim();
        if !trimmed.is_empty() {
            return Ok(PathBuf::from(trimmed));
        }
    }

    if cfg!(debug_assertions) {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        if let Some(project_root) = manifest_dir.parent() {
            return Ok(project_root.join("data"));
        }
    }

    app.path()
        .app_data_dir()
        .map(|dir| dir.join("data"))
        .map_err(|error| error.to_string())
}

fn resolve_sidecar_working_dir(app: &AppHandle) -> Result<PathBuf, String> {
    if cfg!(debug_assertions) {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        if let Some(project_root) = manifest_dir.parent() {
            return Ok(project_root.to_path_buf());
        }
    }

    app.path().app_data_dir().map_err(|error| error.to_string())
}

fn resolve_playwright_browsers_path() -> Option<PathBuf> {
    if env::var_os("PLAYWRIGHT_BROWSERS_PATH").is_some() {
        return None;
    }

    env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .map(|path| path.join("ms-playwright"))
}

fn kill_process_tree(pid: u32) {
    #[cfg(windows)]
    {
        let _ = StdCommand::new("taskkill.exe")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .status();
    }

    #[cfg(not(windows))]
    {
        let _ = pid;
    }
}

#[cfg(windows)]
fn current_sidecar_binary_path() -> Option<PathBuf> {
    let mut path = env::current_exe().ok()?;
    path.set_file_name("mexamplar-sidecar.exe");
    Some(path)
}

#[cfg(windows)]
fn quote_powershell_single(value: &str) -> String {
    format!("'{}'", value.replace('\'', "''"))
}

#[cfg(windows)]
fn kill_stale_sidecars_for_current_binary() {
    let Some(sidecar_path) = current_sidecar_binary_path() else {
        return;
    };
    let target = quote_powershell_single(&sidecar_path.to_string_lossy());
    let script = format!(
        r#"$target = {target}
$extended = '\\?\' + $target
Get-CimInstance Win32_Process -Filter "Name = 'mexamplar-sidecar.exe'" |
    Where-Object {{
        ($_.ExecutablePath -eq $target) -or
        ($_.CommandLine -and ($_.CommandLine.Contains($target) -or $_.CommandLine.Contains($extended)))
    }} |
    ForEach-Object {{ & taskkill.exe /PID ([string]$_.ProcessId) /T /F | Out-Null }}"#
    );

    let _ = StdCommand::new("powershell.exe")
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            &script,
        ])
        .status();
}

#[cfg(not(windows))]
fn kill_stale_sidecars_for_current_binary() {}

pub fn launch_sidecar(app: &AppHandle) -> Result<SidecarState, String> {
    kill_stale_sidecars_for_current_binary();

    let port = reserve_local_port()?;
    let token = generate_token();
    let port_arg = port.to_string();
    let data_dir = resolve_sidecar_data_dir(app)?;
    let working_dir = resolve_sidecar_working_dir(app)?;
    fs::create_dir_all(&data_dir).map_err(|error| error.to_string())?;
    let mut sidecar_log = open_sidecar_log(&data_dir)?;
    let mut command = app
        .shell()
        .sidecar("mexamplar-sidecar")
        .map_err(|error| error.to_string())?
        .args(["--host", "127.0.0.1", "--port", &port_arg])
        .current_dir(&working_dir)
        .env("MEXEMPLAR_DESKTOP_TOKEN", &token)
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUTF8", "1")
        .env("EXEMPLAR_DATA_DIR", data_dir.as_os_str());

    if let Some(playwright_browsers_path) = resolve_playwright_browsers_path() {
        command = command.env(
            "PLAYWRIGHT_BROWSERS_PATH",
            playwright_browsers_path.as_os_str(),
        );
    }

    if cfg!(debug_assertions) {
        command = command.arg("--verbose");
    }

    let (mut events, child) = command.spawn().map_err(|error| error.to_string())?;
    tauri::async_runtime::spawn(async move {
        let _ = writeln!(sidecar_log, "[tauri] Mexemplar sidecar spawned");
        let _ = sidecar_log.flush();
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Terminated(payload) => {
                    let _ = writeln!(
                        sidecar_log,
                        "[tauri] Mexemplar sidecar exited with code {:?}",
                        payload.code
                    );
                    let _ = sidecar_log.flush();
                    eprintln!("Mexemplar sidecar exited with code {:?}", payload.code);
                }
                CommandEvent::Error(error) => {
                    let _ = writeln!(
                        sidecar_log,
                        "[tauri] Mexemplar sidecar emitted a process error: {error}"
                    );
                    let _ = sidecar_log.flush();
                    eprintln!("Mexemplar sidecar emitted a process error");
                }
                CommandEvent::Stdout(bytes) => {
                    write_sidecar_output(&mut sidecar_log, "stdout", &bytes);
                }
                CommandEvent::Stderr(bytes) => {
                    write_sidecar_output(&mut sidecar_log, "stderr", &bytes);
                }
                _ => {}
            }
        }
    });

    let config = SidecarConfig {
        base_url: format!("http://127.0.0.1:{port}"),
        port,
        session_token: token,
    };
    spawn_health_poll(config.clone());

    Ok(SidecarState::new(config, child))
}

#[tauri::command]
pub fn get_sidecar_config(state: State<'_, SidecarState>) -> SidecarConfig {
    state.config()
}
