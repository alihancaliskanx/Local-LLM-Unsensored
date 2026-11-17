use std::env;
use std::io;
use std::net::{Shutdown, SocketAddr, TcpListener, TcpStream};
use std::process::Command;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const VERSION: &str = "0.1.0";

fn current_time_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn is_port_open(addr: &str) -> bool {
    TcpStream::connect_timeout(
        &addr.parse().unwrap_or_else(|_| SocketAddr::from(([127, 0, 0, 1], 8080))),
        Duration::from_millis(150),
    )
    .is_ok()
}

fn wait_for_backend(target: &str, timeout_secs: u64) -> bool {
    let start = Instant::now();
    let max_dur = Duration::from_secs(timeout_secs);
    while start.elapsed() < max_dur {
        if is_port_open(target) {
            return true;
        }
        thread::sleep(Duration::from_millis(100));
    }
    false
}

fn pipe_stream(mut reader: TcpStream, mut writer: TcpStream, last_active: Arc<AtomicU64>) {
    let mut buf = [0u8; 8192];
    loop {
        match io::Read::read(&mut reader, &mut buf) {
            Ok(0) => break,
            Ok(n) => {
                last_active.store(current_time_secs(), Ordering::Relaxed);
                if io::Write::write_all(&mut writer, &buf[..n]).is_err() {
                    break;
                }
            }
            Err(_) => break,
        }
    }
    let _ = reader.shutdown(Shutdown::Both);
    let _ = writer.shutdown(Shutdown::Both);
}

fn handle_client(
    mut client: TcpStream,
    target: String,
    llama_target: String,
    launch_cmd: String,
    api_key: String,
    last_active: Arc<AtomicU64>,
    is_launching: Arc<AtomicBool>,
) {
    if !api_key.is_empty() {
        let mut peek_buf = [0u8; 4096];
        let mut n = 0;
        let start = Instant::now();
        while start.elapsed() < Duration::from_secs(3) {
            match client.peek(&mut peek_buf) {
                Ok(bytes) if bytes > 0 => {
                    n = bytes;
                    break;
                }
                _ => thread::sleep(Duration::from_millis(20)),
            }
        }
        if n == 0 {
            return;
        }
        let req_text = String::from_utf8_lossy(&peek_buf[..n]);
        let auth_bearer = format!("authorization: bearer {}", api_key.to_lowercase());
        let x_api_key = format!("x-api-key: {}", api_key.to_lowercase());
        let req_lower = req_text.to_lowercase();

        if !req_lower.contains(&auth_bearer) && !req_lower.contains(&x_api_key) {
            eprintln!("[cll-reaper] Security: Unauthorized request rejected (missing or invalid API key).");
            let body = b"{\"error\": {\"message\": \"Unauthorized: Missing or invalid API key\", \"type\": \"auth_error\", \"code\": 401}}";
            let header = format!(
                "HTTP/1.1 401 Unauthorized\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            );
            let _ = io::Write::write_all(&mut client, header.as_bytes());
            let _ = io::Write::write_all(&mut client, body);
            let _ = io::Write::flush(&mut client);
            let _ = client.shutdown(Shutdown::Write);
            let mut discard = [0u8; 1024];
            while let Ok(n) = io::Read::read(&mut client, &mut discard) {
                if n == 0 {
                    break;
                }
            }
            return;
        }
    }

    last_active.store(current_time_secs(), Ordering::Relaxed);

    let check_llama = !llama_target.is_empty() && llama_target != "none";
    let is_online = is_port_open(&target) && (!check_llama || is_port_open(&llama_target));

    if !is_online {
        let was_launching = is_launching.swap(true, Ordering::SeqCst);
        if !was_launching {
            eprintln!(
                "[cll-reaper] Backend (bridge: {}, llama: {}) is offline. Auto-starting local LLM backend...",
                target, llama_target
            );
            let launch_cmd_clone = launch_cmd.clone();
            thread::spawn(move || {
                let _ = Command::new("bash")
                    .arg("-c")
                    .arg(&launch_cmd_clone)
                    .spawn();
            });
        }

        let bridge_ok = wait_for_backend(&target, 35);
        let llama_ok = if check_llama {
            wait_for_backend(&llama_target, 35)
        } else {
            true
        };
        last_active.store(current_time_secs(), Ordering::Relaxed);
        is_launching.store(false, Ordering::SeqCst);

        if !bridge_ok || !llama_ok {
            eprintln!(
                "[cll-reaper] Error: Backend failed to become ready within 35 seconds (bridge: {}, llama: {}).",
                bridge_ok, llama_ok
            );
            let err_resp = b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"error\": \"Backend auto-start timed out\"}";
            let _ = io::Write::write_all(&mut client, err_resp);
            return;
        }
        eprintln!("[cll-reaper] Backend is now ready.");
    }

    let backend = match TcpStream::connect(&target) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("[cll-reaper] Failed to connect to backend {}: {}", target, e);
            let err_resp = b"HTTP/1.1 502 Bad Gateway\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"error\": \"Failed to connect to backend\"}";
            let _ = io::Write::write_all(&mut client, err_resp);
            return;
        }
    };

    let client_read = match client.try_clone() {
        Ok(c) => c,
        Err(_) => return,
    };
    let backend_write = match backend.try_clone() {
        Ok(b) => b,
        Err(_) => return,
    };

    let la1 = Arc::clone(&last_active);
    thread::spawn(move || {
        pipe_stream(client_read, backend_write, la1);
    });

    let la2 = Arc::clone(&last_active);
    pipe_stream(backend, client, la2);
}

fn print_usage() {
    println!("cll-reaper v{} — Lightweight On-Demand Gateway & Idle Reaper for Local LLM", VERSION);
    println!("\nUsage: cll-reaper [options]");
    println!("\nEnvironment Options:");
    println!("  REAPER_BIND        Listen address (default: 127.0.0.1:61230)");
    println!("  BACKEND_TARGET     Forward address (default: 127.0.0.1:61231)");
    println!("  LLAMA_TARGET       Core LLM server address to await (default: 127.0.0.1:61232)");
    println!("  REAPER_API_KEY     Optional local authorization token / API key (default: none)");
    println!("  LLM_IDLE_TIMEOUT   Inactivity timeout in seconds before stopping backend (default: 900 / 15m, 0 to disable)");
    println!("  LAUNCH_CMD         Command to spawn backend when offline (default: OPENCODE_BRIDGE_PORT=61231 PORT=61232 qwen-local server)");
    println!("  STOP_CMD           Command to stop backend on timeout (default: qstop)");
    println!("\nFlags:");
    println!("  -h, --help         Show this help message");
    println!("  -v, --version      Show version information");
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() > 1 {
        match args[1].as_str() {
            "-h" | "--help" => {
                print_usage();
                return;
            }
            "-v" | "--version" => {
                println!("cll-reaper v{}", VERSION);
                return;
            }
            _ => {}
        }
    }

    let bind_addr = env::var("REAPER_BIND").unwrap_or_else(|_| "127.0.0.1:61230".to_string());
    let backend_target = env::var("BACKEND_TARGET").unwrap_or_else(|_| "127.0.0.1:61231".to_string());
    let llama_target = env::var("LLAMA_TARGET").unwrap_or_else(|_| "127.0.0.1:61232".to_string());
    let api_key = env::var("REAPER_API_KEY").unwrap_or_default();
    let idle_timeout: u64 = env::var("LLM_IDLE_TIMEOUT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(900); // 15 mins default
    let launch_cmd = env::var("LAUNCH_CMD").unwrap_or_else(|_| {
        "OPENCODE_BRIDGE_PORT=61231 PORT=61232 qwen-local server".to_string()
    });
    let stop_cmd = env::var("STOP_CMD").unwrap_or_else(|_| {
        "qstop".to_string()
    });

    eprintln!("── [cll-reaper v{} | Minimal Gateway & Idle Reaper] ──", VERSION);
    eprintln!("  Listening on   : {}", bind_addr);
    eprintln!("  Forwarding to  : {}", backend_target);
    eprintln!("  LLM Target     : {}", llama_target);
    if !api_key.is_empty() {
        eprintln!("  Auth Protection: Enabled (API Key required)");
    } else {
        eprintln!("  Auth Protection: Disabled");
    }
    eprintln!("  Idle Timeout   : {}s ({}m)", idle_timeout, idle_timeout / 60);

    let listener = match TcpListener::bind(&bind_addr) {
        Ok(l) => l,
        Err(e) => {
            eprintln!("[cll-reaper] Fatal: Failed to bind {}: {}", bind_addr, e);
            std::process::exit(1);
        }
    };

    let last_active = Arc::new(AtomicU64::new(current_time_secs()));
    let is_launching = Arc::new(AtomicBool::new(false));

    // Idle Reaper background thread
    if idle_timeout > 0 {
        let la = Arc::clone(&last_active);
        let il_reap = Arc::clone(&is_launching);
        let target = backend_target.clone();
        let lt = llama_target.clone();
        let check_llama = !lt.is_empty() && lt != "none";
        let stop_script = stop_cmd.clone();
        let check_interval = Duration::from_secs(if idle_timeout > 5 { 5 } else { 1 });
        thread::spawn(move || loop {
            thread::sleep(check_interval);
            if !il_reap.load(Ordering::Relaxed)
                && (is_port_open(&target) || (check_llama && is_port_open(&lt)))
            {
                let now = current_time_secs();
                let last = la.load(Ordering::Relaxed);
                if now.saturating_sub(last) >= idle_timeout {
                    eprintln!(
                        "[cll-reaper] Idle timeout ({}s) reached. Terminating backend to release GPU VRAM.",
                        idle_timeout
                    );
                    let _ = Command::new("bash").arg("-c").arg(&stop_script).status();
                    la.store(current_time_secs(), Ordering::Relaxed);
                }
            }
        });
    }

    for stream in listener.incoming() {
        match stream {
            Ok(client) => {
                let target = backend_target.clone();
                let lt = llama_target.clone();
                let launch = launch_cmd.clone();
                let key = api_key.clone();
                let la = Arc::clone(&last_active);
                let il = Arc::clone(&is_launching);
                thread::spawn(move || {
                    handle_client(client, target, lt, launch, key, la, il);
                });
            }
            Err(e) => {
                eprintln!("[cll-reaper] Connection error: {}", e);
            }
        }
    }
}
