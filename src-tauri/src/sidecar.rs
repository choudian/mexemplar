use std::{
    env, fs,
    io::{Read, Write},
    net::TcpListener,
    net::TcpStream,
    path::PathBuf,
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
                let _ = child.kill();
            }
        }
    }
}

impl Drop for SidecarState {
    fn drop(&mut self) {
        if let Ok(mut child) = self.child.lock() {
            if let Some(child) = child.take() {
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

pub fn launch_sidecar(app: &AppHandle) -> Result<SidecarState, String> {
    let port = reserve_local_port()?;
    let token = generate_token();
    let port_arg = port.to_string();
    let data_dir = resolve_sidecar_data_dir(app)?;
    fs::create_dir_all(&data_dir).map_err(|error| error.to_string())?;
    let command = app
        .shell()
        .sidecar("mexamplar-sidecar")
        .map_err(|error| error.to_string())?
        .args(["--host", "127.0.0.1", "--port", &port_arg])
        .env("MEXEMPLAR_DESKTOP_TOKEN", &token)
        .env("EXEMPLAR_DATA_DIR", data_dir.as_os_str());

    let (mut events, child) = command.spawn().map_err(|error| error.to_string())?;
    tauri::async_runtime::spawn(async move {
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Terminated(payload) => {
                    eprintln!("Mexemplar sidecar exited with code {:?}", payload.code);
                }
                CommandEvent::Error(_) => {
                    eprintln!("Mexemplar sidecar emitted a process error");
                }
                CommandEvent::Stdout(_) | CommandEvent::Stderr(_) => {}
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
