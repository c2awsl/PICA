use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;
use tauri::Manager;

/// Holds the managed Python server process so we can kill it on exit.
struct PythonProcess(Mutex<Option<Child>>);

/// Spawn the Python backend server as a child process.
fn spawn_python_server() -> Result<Child, String> {
    let project_dir = std::env::current_dir().map_err(|e| e.to_string())?;

    // Try `python` first, then `python3` as fallback
    let python_cmd = if Command::new("python")
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .and_then(|mut c| c.wait())
        .map(|s| s.success())
        .unwrap_or(false)
    {
        "python"
    } else {
        "python3"
    };

    let child = Command::new(python_cmd)
        .args(["-m", "pica"])
        .current_dir(&project_dir)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| {
            format!(
                "Failed to start PICA server.\n\n\
                 Make sure Python 3.11+ is installed and in PATH.\n\
                 Command tried: `{} -m pica`\n\
                 Error: {}",
                python_cmd, e
            )
        })?;

    Ok(child)
}

/// Poll the server health endpoint until it responds or we time out.
fn wait_for_server(timeout_secs: u64) -> Result<(), String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| e.to_string())?;

    let start = std::time::Instant::now();
    loop {
        if start.elapsed().as_secs() > timeout_secs {
            return Err(format!(
                "PICA server did not start within {} seconds.\n\n\
                 Check that the server can start normally by running:\n  python -m pica\n\
                 in the project directory.",
                timeout_secs
            ));
        }
        match client.get("http://127.0.0.1:8765/pending").send() {
            Ok(resp) if resp.status().is_success() => return Ok(()),
            _ => std::thread::sleep(Duration::from_millis(500)),
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Spawn the Python backend
    let python_child = spawn_python_server().unwrap_or_else(|err| {
        eprintln!("{}", err);
        std::process::exit(1);
    });

    // Wait for the server to be ready
    println!("Starting PICA server…");
    if let Err(err) = wait_for_server(30) {
        let _ = python_child.kill();
        eprintln!("{}", err);
        std::process::exit(1);
    }
    println!("PICA is ready.");

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(PythonProcess(Mutex::new(Some(python_child))))
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                if let Some(state) = window.try_state::<PythonProcess>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(mut child) = guard.take() {
                            let _ = child.kill();
                            let _ = child.wait();
                        }
                    }
                }
                std::process::exit(0);
            }
        })
        .run(tauri::generate_context!())
        .expect("Failed to run PICA desktop app.");
}
