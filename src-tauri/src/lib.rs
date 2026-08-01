use std::sync::Mutex;
use tauri::Manager;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

// Learn more about Tauri commands at https://tauri.app/develop/calling-rust/
#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

/// Holds the running Python sidecar so it can be killed on app exit.
struct BackendProcess(Mutex<Option<CommandChild>>);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            // debug builds don't spawn the sidecar - run axiom-backend\dev.ps1 instead
            if cfg!(debug_assertions) {
                println!(
                    "[axiom-backend] debug build: not spawning sidecar - \
                     run axiom-backend\\dev.ps1 to start the backend"
                );
                return Ok(());
            }

            let (mut rx, child) = app
                .shell()
                .sidecar("axiom-backend")
                .expect("failed to create axiom-backend sidecar command")
                .spawn()
                .expect("failed to spawn axiom-backend sidecar");

            app.manage(BackendProcess(Mutex::new(Some(child))));

            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            print!("[axiom-backend] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stderr(line) => {
                            eprint!("[axiom-backend] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Error(err) => {
                            eprintln!("[axiom-backend] error: {err}");
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[axiom-backend] exited: {:?}", payload.code);
                        }
                        _ => {}
                    }
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![greet])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                if let Some(state) = app_handle.try_state::<BackendProcess>() {
                    if let Some(child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
        });
}
