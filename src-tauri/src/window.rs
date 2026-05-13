use crate::sidecar::SidecarState;
use tauri::Manager;

#[tauri::command]
pub fn minimize(window: tauri::Window) -> Result<(), String> {
    window.minimize().map_err(|error| error.to_string())
}

#[tauri::command]
pub fn toggle_maximize(window: tauri::Window) -> Result<(), String> {
    if window.is_maximized().map_err(|error| error.to_string())? {
        window.unmaximize().map_err(|error| error.to_string())
    } else {
        window.maximize().map_err(|error| error.to_string())
    }
}

#[tauri::command]
pub fn close(window: tauri::Window) -> Result<(), String> {
    if let Some(state) = window.try_state::<SidecarState>() {
        state.kill();
    }
    window.close().map_err(|error| error.to_string())
}

#[tauri::command]
pub fn start_dragging(window: tauri::Window) -> Result<(), String> {
    window.start_dragging().map_err(|error| error.to_string())
}
