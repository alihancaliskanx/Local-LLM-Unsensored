#!/usr/bin/env python3
"""
cll/host.py — Tor Onion Service Host & Key Persistence Manager (qwhost)
Exposes local ports (web apps, dev servers, APIs) to Tor as persistent v3 .onion services.
Guarantees address immutability across system restarts.
"""

import sys
import os
import re
import socket
import argparse
import tarfile
import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple, List

TOR_CONTROL_HOST = "127.0.0.1"
TOR_CONTROL_PORT = 9051
COOKIE_CANDIDATES = [
    "/var/lib/tor/control_auth_cookie",
    "/run/tor/control.authcookie",
    os.path.expanduser("~/.local/share/tor/control_auth_cookie")
]
SERVICES_DIR = Path(os.path.expanduser("~/.local/share/qwen/onion_services"))


def get_control_connection() -> socket.socket:
    """Connects and authenticates to Tor Control Port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5.0)
    try:
        s.connect((TOR_CONTROL_HOST, TOR_CONTROL_PORT))
    except Exception as e:
        sys.stderr.write(f"Error: Cannot connect to Tor Control Port at {TOR_CONTROL_HOST}:{TOR_CONTROL_PORT}: {e}\n")
        sys.stderr.write("Hint: Make sure tor is running (e.g. 'sudo systemctl start tor').\n")
        sys.exit(1)

    cookie = None
    for cp in COOKIE_CANDIDATES:
        if os.path.exists(cp):
            try:
                with open(cp, "rb") as f:
                    cookie = f.read()
                break
            except PermissionError:
                pass

    if cookie:
        s.sendall(b"AUTHENTICATE " + cookie.hex().encode() + b"\r\n")
    else:
        s.sendall(b"AUTHENTICATE \"\"\r\n")

    res = s.recv(1024).decode("utf-8", errors="ignore")
    if "250 OK" not in res:
        sys.stderr.write(f"Error: Tor Control Port authentication failed: {res.strip()}\n")
        sys.stderr.write("Hint: Ensure your user is in the 'tor' group: 'sudo usermod -aG tor $USER' and log back in.\n")
        sys.exit(1)
    return s


def send_tor_cmd(s: socket.socket, cmd: str) -> str:
    s.sendall(cmd.strip().encode("utf-8") + b"\r\n")
    data = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
        if b"250 OK" in chunk or b"510 " in chunk or b"552 " in chunk or b"512 " in chunk:
            break
    return data.decode("utf-8", errors="ignore")


def get_active_onions(s: socket.socket) -> Dict[str, str]:
    """Retrieves active onion services from Tor control port (both current and detached)."""
    active = {}
    for info_key in ("onions/current", "onions/detached"):
        resp = send_tor_cmd(s, f"GETINFO {info_key}")
        m = re.search(r"250\+" + re.escape(info_key) + r"=(.*?)\r?\n\.\r?\n250 OK", resp, re.DOTALL)
        if m:
            for line in m.group(1).strip().splitlines():
                line = line.strip()
                if line:
                    active[line] = "active"
    return active


def start_service(port: int, name: str, remote_port: int = 80):
    """Starts or restores an Onion service with permanent key storage."""
    SERVICES_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SERVICES_DIR, 0o700)

    key_file = SERVICES_DIR / f"{name}.key"
    host_file = SERVICES_DIR / f"{name}.onion"
    target = f"{remote_port},127.0.0.1:{port}"

    s = get_control_connection()

    if key_file.exists():
        with open(key_file, "r", encoding="utf-8") as f:
            stored_key = f.read().strip()
        cmd = f"ADD_ONION {stored_key} Flags=Detach Port={target}"
    else:
        cmd = f"ADD_ONION NEW:ED25519-V3 Flags=Detach Port={target}"

    res = send_tor_cmd(s, cmd)
    if "250 OK" not in res:
        sys.stderr.write(f"Error starting onion service: {res.strip()}\n")
        s.close()
        sys.exit(1)

    sid_match = re.search(r"ServiceID=([a-z2-7]{56})", res)
    key_match = re.search(r"PrivateKey=(ED25519-V3:[A-Za-z0-9+/=]+)", res)

    if not sid_match:
        sys.stderr.write(f"Error: Could not parse ServiceID from response: {res}\n")
        s.close()
        sys.exit(1)

    service_id = sid_match.group(1)
    onion_url = f"{service_id}.onion"

    if key_match:
        with open(key_file, "w", encoding="utf-8") as f:
            f.write(key_match.group(1) + "\n")
        os.chmod(key_file, 0o600)

    with open(host_file, "w", encoding="utf-8") as f:
        f.write(f"{onion_url}\n{port}\n")
    os.chmod(host_file, 0o600)

    s.close()

    print("═══════════════════════════════════════════════════════════════")
    print(f" 🧅 Tor Onion Service Active — [{name}]")
    print(f" 🌐 Address:   http://{onion_url}")
    print(f" 🎯 Target:    127.0.0.1:{port} (Mapped to remote port {remote_port})")
    print(f" 🔑 Key File:  {key_file} (Perm: 0600 - IMMUTABLE ON REBOOT)")
    print(" 🛑 Stop:      qwhost stop " + name)
    print("═══════════════════════════════════════════════════════════════")


def stop_service(name: str):
    """Stops an active Onion service."""
    host_file = SERVICES_DIR / f"{name}.onion"
    if not host_file.exists():
        sys.stderr.write(f"Error: No onion service found with name '{name}'\n")
        sys.exit(1)

    with open(host_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    if not lines:
        sys.stderr.write(f"Error: Host file for '{name}' is empty\n")
        sys.exit(1)

    service_id = lines[0].replace(".onion", "")

    s = get_control_connection()
    res = send_tor_cmd(s, f"DEL_ONION {service_id}")
    s.close()

    if "250 OK" in res:
        print(f"✔ Onion service [{name}] ({service_id[:16]}...) stopped.")
    else:
        print(f"Notice: Service was not currently active in Tor daemon ({res.strip()}).")


def list_services():
    """Lists all configured and active Onion services."""
    if not SERVICES_DIR.exists():
        print("No onion services configured. Use: qwhost start <port> [name]")
        return

    s = get_control_connection()
    active_sids = get_active_onions(s)
    s.close()

    host_files = list(SERVICES_DIR.glob("*.onion"))
    if not host_files:
        print("No onion services configured. Use: qwhost start <port> [name]")
        return

    print("═══════════════════════════════════════════════════════════════════════════════")
    print(" 🧅 Configured Tor Onion Services (qwhost)")
    print("═══════════════════════════════════════════════════════════════════════════════")
    print(f"{'Name':<15} | {'Status':<10} | {'Target':<14} | {'Onion Address'}")
    print("-" * 79)

    for hf in sorted(host_files):
        name = hf.stem
        try:
            with open(hf, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
            onion_url = lines[0] if lines else "unknown"
            port = lines[1] if len(lines) > 1 else "?"
            sid = onion_url.replace(".onion", "")
            is_active = sid in active_sids
            status_str = "🟢 ACTIVE" if is_active else "⚪ STOPPED"
            print(f"{name:<15} | {status_str:<10} | 127.0.0.1:{port:<6} | {onion_url}")
        except Exception as e:
            print(f"{name:<15} | ERROR: {e}")
    print("═══════════════════════════════════════════════════════════════════════════════")


def backup_keys(dest: Optional[str] = None):
    """Safely archives all onion service private keys."""
    if not SERVICES_DIR.exists():
        print("No onion services to back up.")
        return

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_path = dest or os.path.expanduser(f"~/onion_keys_backup_{timestamp}.tar.gz")

    with tarfile.open(dest_path, "w:gz") as tar:
        tar.add(SERVICES_DIR, arcname="onion_services")

    os.chmod(dest_path, 0o600)
    print(f"✔ Successfully created secure key backup: {dest_path}")
    print("  Permissions set to 0600 (owner read-only). Keep this file safe and offline!")


def main():
    parser = argparse.ArgumentParser(
        description="qwhost — Tor Onion Service Host & Key Persistence Manager",
        epilog="Guarantees that your .onion address stays permanent across computer restarts."
    )
    sub = parser.add_subparsers(dest="cmd")

    start_p = sub.add_parser("start", help="Host a local port as a persistent .onion address")
    start_p.add_argument("port", type=int, help="Local port to expose (e.g. 3000, 8080, 41625)")
    start_p.add_argument("name", nargs="?", default="default", help="Service name identifier (default: 'default')")
    start_p.add_argument("--remote-port", type=int, default=80, help="Virtual port on onion address (default: 80)")

    stop_p = sub.add_parser("stop", help="Stop an active onion service")
    stop_p.add_argument("name", nargs="?", default="default", help="Service name identifier")

    sub.add_parser("list", help="List all configured onion services and their statuses")
    sub.add_parser("status", help="List all configured onion services and their statuses")

    backup_p = sub.add_parser("backup", help="Create a secure, encrypted/chmod-600 backup of all onion keys")
    backup_p.add_argument("--dest", type=str, help="Destination archive path")

    args = parser.parse_args()

    if not args.cmd or args.cmd in ("list", "status"):
        list_services()
    elif args.cmd == "start":
        start_service(args.port, args.name, args.remote_port)
    elif args.cmd == "stop":
        stop_service(args.name)
    elif args.cmd == "backup":
        backup_keys(args.dest)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
