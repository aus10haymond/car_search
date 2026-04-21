use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, WindowEvent};

// ── Project root (compile-time constant) ──────────────────────────────────────
//
// CARGO_MANIFEST_DIR is the absolute path of src-tauri/ at compile time.
// Walking up three parents gives: src-tauri → frontend → dashboard → project root.
fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent() // frontend/
        .unwrap()
        .parent() // dashboard/
        .unwrap()
        .parent() // project root
        .unwrap()
        .to_path_buf()
}

// ── Shared state: holds the backend child process ────────────────────────────
struct BackendProcess(Mutex<Option<Child>>);

fn kill_backend(app: &AppHandle) {
    if let Some(state) = app.try_state::<BackendProcess>() {
        if let Ok(mut guard) = state.0.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
            }
        }
    }
}

// ── App entry point ───────────────────────────────────────────────────────────
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            // ── Start FastAPI backend ──────────────────────────────────────
            let root = project_root();
            log::info!("Project root: {}", root.display());

            let mut cmd = Command::new("python");
            cmd.args([
                "-m", "uvicorn",
                "dashboard.backend.app:app",
                "--host", "127.0.0.1",
                "--port", "8000",
            ])
            .current_dir(&root);

            // On Windows, suppress the console window that would otherwise
            // pop up behind the Tauri window whenever the app launches.
            #[cfg(target_os = "windows")]
            {
                use std::os::windows::process::CommandExt;
                const CREATE_NO_WINDOW: u32 = 0x0800_0000;
                cmd.creation_flags(CREATE_NO_WINDOW);
            }

            match cmd.spawn() {
                Ok(child) => {
                    *app.state::<BackendProcess>().0.lock().unwrap() = Some(child);
                    log::info!("Backend started on http://127.0.0.1:8000");
                }
                Err(e) => {
                    log::error!("Failed to start backend: {e}");
                }
            }

            // ── Build tray menu ────────────────────────────────────────────
            let open_item =
                MenuItem::with_id(app, "open", "Open Dashboard", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open_item, &quit_item])?;

            // ── Create tray icon ───────────────────────────────────────────
            let _tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .tooltip("Carvana Tracker")
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => show_window(app),
                    "quit" => {
                        kill_backend(app);
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_window(tray.app_handle());
                    }
                })
                .build(app)?;

            Ok(())
        })
        // ── Close button → minimize to tray, not quit ─────────────────────
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn show_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}
