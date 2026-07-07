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
    crate::sidecar::kill_sidecar(window.app_handle());
    window.close().map_err(|error| error.to_string())
}

#[tauri::command]
pub fn start_dragging(window: tauri::Window) -> Result<(), String> {
    window.start_dragging().map_err(|error| error.to_string())
}
