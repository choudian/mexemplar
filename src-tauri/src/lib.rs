mod sidecar;
mod window;

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_http::init())
        .setup(|app| {
            let state = sidecar::launch_sidecar(app.handle())?;
            app.manage(state);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            sidecar::get_sidecar_config,
            window::minimize,
            window::toggle_maximize,
            window::close,
            window::start_dragging
        ])
        .run(tauri::generate_context!())
        .expect("failed to run Mexemplar desktop shell");
}
