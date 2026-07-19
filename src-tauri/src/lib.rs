mod sidecar;
mod window;

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            let state = sidecar::launch_sidecar(app.handle())?;
            app.manage(state);
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(
                event,
                tauri::WindowEvent::CloseRequested { .. } | tauri::WindowEvent::Destroyed
            ) {
                sidecar::kill_sidecar(window.app_handle());
            }
        })
        .invoke_handler(tauri::generate_handler![
            sidecar::get_sidecar_config,
            window::minimize,
            window::toggle_maximize,
            window::close,
            window::start_dragging
        ])
        .build(tauri::generate_context!())
        .expect("failed to run Mexemplar desktop shell");

    app.run(|app_handle, event| {
        if matches!(
            event,
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
        ) {
            sidecar::kill_sidecar(app_handle);
        }
    });
}
