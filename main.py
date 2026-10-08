"""AiROS Staff local launcher.

Default mode runs the whole system in Docker (postgres + redis + migrations
+ api + web) via the root docker-compose.yml:

    python main.py                      # docker compose up --build
    python main.py --seed               # same, plus the demo-tenant seed profile
    python main.py --down               # docker compose down

Frontend: http://localhost:3000   API: http://localhost:8000/api/v1
Demo logins (after --seed): admin@demo.local / employee@demo.local,
password Demo!Pass123.

`--native` keeps the old bare-metal dev flow (uvicorn --reload + tsx/Vite dev
server, optional Android emulator via Capacitor):

    python main.py --native             # backend + frontend + emulator app
    python main.py --native --web       # browser-only: skip the emulator
    python main.py --native --backend-only
    python main.py --native --frontend-only
    python main.py --native --backend-port 8001 --frontend-port 3001

Environment variables:
    BACKEND_HOST   bind host for uvicorn          (default 127.0.0.1)
    BACKEND_PORT   uvicorn port                   (default 8000)
    FRONTEND_PORT  PORT env passed to tsx server  (default 3000)
    ANDROID_SDK    Android SDK override (else ANDROID_HOME / ANDROID_SDK_ROOT /
                   platform default / frontend/android/local.properties sdk.dir)
    ANDROID_AVD    AVD name for emulator mode     (default: 'dev_avd' if present,
                   else first from `emulator -list-avds`)

    ANDROID_JAVA_HOME  JDK >= 21 override used for the `cap run` gradle build
                   (else JAVA_HOME / ~/.jdks / standard JDK locations)

Emulator-mode prerequisites: Android SDK + at least one AVD, JDK 21 (the Capacitor
gradle project targets Java 21), `npm install` already run inside frontend/. The emulator maps 10.0.2.2 to the
host loopback, so frontend/.env VITE_API_URL and capacitor.config.json
server.url must point at 10.0.2.2:<port>.

Stdlib only. Ctrl+C stops the services (and the emulator if we started it).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import NoReturn

# Child output (gradle logs etc.) can carry non-console-codepage characters.
sys.stdout.reconfigure(errors="replace")  # type: ignore[attr-defined]

PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND = PROJECT_ROOT / "backend"
FRONTEND = PROJECT_ROOT / "frontend"
IS_WINDOWS = os.name == "nt"

HMR_PORT = 24678

def fail(msg: str) -> NoReturn:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)

def log(msg: str) -> None:
    print(f"[LAUNCHER] {msg}", flush=True)


class LaunchError(Exception):
    """Fatal error raised while children are running - caught in main() so
    running services are shut down cleanly instead of leaking."""

# Port checks - connect-test first (a 0.0.0.0 listener is invisible to a
# 127.0.0.1 bind on Windows), then an exclusive bind on the real listen addr.

def check_port_free(bind_addr: str, port: int, label: str) -> None:
    msg = (f"{label} port {port} is already in use - another dev server may "
           f"still be running; stop it first or pass a different port.")
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
        fail(msg)
    except (ConnectionRefusedError, socket.timeout, OSError):
        pass
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if IS_WINDOWS:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind((bind_addr, port))
    except OSError:
        fail(msg)
    finally:
        sock.close()

def port_open(host: str, port: int) -> bool:
    try:
        socket.create_connection((host, port), timeout=0.5).close()
        return True
    except OSError:
        return False

# Process helpers - children run in their own process group / session so the
# whole tree can be signalled without touching anything else.

def spawn(cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    kwargs: dict = {"cwd": str(cwd), "env": env, "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)

def start_stream(proc: subprocess.Popen[bytes], tag: str) -> threading.Thread:
    def stream() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            print(f"[{tag}] {raw.decode('utf-8', errors='replace').rstrip()}", flush=True)
    t = threading.Thread(target=stream, daemon=True)
    t.start()
    return t

def interrupt(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(proc.pid, signal.SIGINT)
    except (ProcessLookupError, OSError):
        pass

def reap(proc: subprocess.Popen[bytes], grace: float = 5.0) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.terminate()
        proc.wait(timeout=grace)
    except (subprocess.TimeoutExpired, OSError):
        proc.kill()

def backend_python() -> str:
    venv = BACKEND / (".venv/Scripts/python.exe" if IS_WINDOWS else ".venv/bin/python")
    return str(venv) if venv.exists() else sys.executable

# Android helpers

def resolve_sdk() -> Path:
    candidates = [
        os.environ.get("ANDROID_SDK"),
        os.environ.get("ANDROID_HOME"),
        os.environ.get("ANDROID_SDK_ROOT"),
    ]
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(str(Path(local) / "Android/Sdk"))
    elif sys.platform == "darwin":
        candidates.append(str(Path.home() / "Library/Android/sdk"))
    else:
        candidates.append(str(Path.home() / "Android/Sdk"))
    props = FRONTEND / "android" / "local.properties"
    if props.exists():
        for line in props.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("sdk.dir="):
                candidates.append(line.split("=", 1)[1].strip().replace("\\:", ":"))
    for c in candidates:
        if c and Path(c).is_dir():
            return Path(c)
    raise LaunchError("Android SDK not found - set ANDROID_SDK (or ANDROID_HOME / "
                      "sdk.dir in frontend/android/local.properties).")

def pick_avd(emulator: str, env: dict[str, str]) -> str:
    requested = os.environ.get("ANDROID_AVD")
    try:
        out = subprocess.run([emulator, "-list-avds"], env=env,
                             capture_output=True, text=True, timeout=15)
        avds = [a.strip() for a in out.stdout.splitlines() if a.strip()]
    except (OSError, subprocess.TimeoutExpired):
        avds = []
    if requested:
        return requested
    if "dev_avd" in avds:
        return "dev_avd"
    if avds:
        return avds[0]
    raise LaunchError("no Android AVDs found - create one or set ANDROID_AVD.")

def adb_online_serials(adb: str, env: dict[str, str]) -> list[str]:
    out = subprocess.run([adb, "devices"], env=env, capture_output=True,
                         text=True, timeout=15)
    return [ln.split("\t")[0].strip() for ln in out.stdout.splitlines()[1:]
            if ln.strip().endswith("\tdevice")]

def java_major(java_bin: Path) -> int | None:
    try:
        out = subprocess.run([str(java_bin), "-version"], capture_output=True,
                             text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r'version "(\d+)(?:\.(\d+))?', out.stderr + out.stdout)
    if not m:
        return None
    major = int(m.group(1))
    if major == 1 and m.group(2):  # legacy "1.8.0_x" form
        major = int(m.group(2))
    return major


def resolve_jdk() -> tuple[Path, int]:
    """Find a JDK >= 21 for the Capacitor gradle build."""
    candidates: list[Path] = []
    for env_name in ("ANDROID_JAVA_HOME", "JAVA_HOME"):
        if os.environ.get(env_name):
            candidates.append(Path(os.environ[env_name]))
    jdks = Path.home() / ".jdks"
    if jdks.is_dir():
        candidates.extend(sorted(jdks.iterdir()))
    if IS_WINDOWS:
        for base in (r"C:\Program Files\Microsoft", r"C:\Program Files\Java",
                     r"C:\Program Files\Eclipse Adoptium"):
            candidates.extend(sorted(Path(base).glob("jdk-*")) if Path(base).is_dir() else [])
        candidates.append(Path(r"C:\Program Files\Android\Android Studio\jbr"))
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / r"Programs\Android\Android Studio\jbr")
    elif sys.platform == "darwin":
        candidates.extend(sorted(Path("/Library/Java/JavaVirtualMachines").glob("*/Contents/Home")))
    else:
        candidates.extend(sorted(Path("/usr/lib/jvm").glob("*")))

    java_name = "java.exe" if IS_WINDOWS else "java"
    best: tuple[Path, int] | None = None
    for c in candidates:
        java_bin = c / "bin" / java_name
        if not java_bin.exists():
            continue
        major = java_major(java_bin)
        if major is not None and major >= 21 and (best is None or major > best[1]):
            best = (c, major)
    if best is None:
        raise LaunchError("Capacitor's gradle project needs JDK 21+ - install one or set "
                          "ANDROID_JAVA_HOME to an existing JDK 21+ directory.")
    return best


def adb_out(adb: str, env: dict[str, str], *args: str) -> str:
    out = subprocess.run([adb, *args], env=env, capture_output=True,
                         text=True, timeout=30)
    return out.stdout.strip()

def android_flow(sdk: Path, bport: int, fport: int, children: dict[str, subprocess.Popen[bytes]],
                 threads: list[threading.Thread]) -> None:
    exe = ".exe" if IS_WINDOWS else ""
    adb = str(sdk / "platform-tools" / f"adb{exe}")
    emulator = str(sdk / "emulator" / f"emulator{exe}")
    if not Path(adb).exists() or not Path(emulator).exists():
        raise LaunchError(f"adb/emulator not found under {sdk} - check ANDROID_SDK.")

    child_env = dict(os.environ, ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk))
    jdk, jdk_major = resolve_jdk()
    child_env["JAVA_HOME"] = str(jdk)
    log(f"using JDK {jdk_major} at {jdk}")
    child_env["PATH"] = (str(sdk / "platform-tools") + os.pathsep + str(jdk / "bin")
                         + os.pathsep + child_env.get("PATH", ""))

    # 1. Wait for the frontend dev server (capacitor server.url live-reloads from it)
    if not port_open("127.0.0.1", fport):
        log("waiting for frontend dev server...")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if port_open("127.0.0.1", fport):
                break
            fe = children.get("FRONTEND")
            if fe is not None and fe.poll() is not None:
                return  # main loop reports the exit
            time.sleep(0.5)
        else:
            raise LaunchError(f"frontend dev server did not come up on port {fport} within 90s.")

    # 2. Emulator: reuse a running one, else boot our own
    serials = adb_online_serials(adb, child_env)
    if serials:
        serial = serials[0]
        log(f"using already-running emulator {serial}")
    else:
        # Only an emulator we spawn gets reaped on shutdown.
        avd = pick_avd(emulator, child_env)
        log(f"booting emulator (AVD {avd})...")
        # -no-snapshot-save: quick-boot snapshots cost ~2.5 GB of disk on exit.
        proc = spawn([emulator, "-avd", avd, "-netdelay", "none", "-netspeed", "full",
                      "-no-snapshot-save"], sdk, child_env)
        children["EMULATOR"] = proc
        threads.append(start_stream(proc, "EMULATOR"))
        deadline = time.monotonic() + 240
        serial = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise LaunchError(f"emulator exited with code {proc.returncode} before booting.")
            serials = adb_online_serials(adb, child_env)
            if serials:
                serial = serials[0]
                break
            time.sleep(2)
        if serial is None:
            raise LaunchError("emulator did not appear in `adb devices` within 240s.")

    subprocess.run([adb, "-s", serial, "wait-for-device"], env=child_env, timeout=240)
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        if adb_out(adb, child_env, "-s", serial, "shell", "getprop", "sys.boot_completed") == "1":
            break
        emu = children.get("EMULATOR")
        if emu is not None and emu.poll() is not None:
            raise LaunchError(f"emulator exited with code {emu.returncode} during boot.")
        time.sleep(2)
    else:
        raise LaunchError(f"emulator {serial} did not finish booting within 240s.")
    # adb can briefly report "authorizing" right after a snapshot boot; cap run
    # fails on that, so wait for a stable "device" state first.
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and serial not in adb_online_serials(adb, child_env):
        time.sleep(2)
    time.sleep(3)
    log(f"emulator {serial} booted")

    # 3. Deploy via capacitor (sync + gradle build + install + launch)
    npx = shutil.which("npx")
    if not npx:
        raise LaunchError("npx not found on PATH - install Node.js first.")
    # The committed capacitor.config.json intentionally carries no server.url:
    # a remote URL there would make production APKs load a dead dev server.
    # Emulator runs inject it transiently and restore the file afterwards.
    cap_cfg = FRONTEND / "capacitor.config.json"
    cap_cfg_orig = cap_cfg.read_text(encoding="utf-8")
    try:
        cfg = json.loads(cap_cfg_orig)
        cfg["server"] = {"url": f"http://10.0.2.2:{fport}", "cleartext": True}
        cap_cfg.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError) as e:
        raise LaunchError(f"could not write dev server.url into capacitor.config.json: {e}")
    log("running cap run android (first gradle build can take several minutes)...")
    cap = spawn([npx, "cap", "run", "android", "--target", serial], FRONTEND, child_env)
    cap_thread = start_stream(cap, "ANDROID")
    try:
        code = cap.wait(timeout=900)
    except subprocess.TimeoutExpired:
        cap.kill()
        raise LaunchError("cap run android timed out after 15 minutes.")
    finally:
        try:
            cap_cfg.write_text(cap_cfg_orig, encoding="utf-8")
        except OSError:
            pass
    cap_thread.join(timeout=5)
    if code != 0:
        raise LaunchError(f"cap run android failed with code {code} - see [ANDROID] output above.")
    log(f"app installed and launched on {serial}; live-reloading from http://10.0.2.2:{fport}")

# Warnings for android config drift (non-fatal)

def android_banner_warnings(bport: int, fport: int) -> None:
    cfg = FRONTEND / "capacitor.config.json"
    try:
        server_url = json.loads(cfg.read_text(encoding="utf-8")).get("server", {}).get("url", "")
        port = server_url.rsplit(":", 1)[-1].rstrip("/")
        if port.isdigit() and int(port) != fport:
            print(f"WARNING: capacitor.config.json server.url port ({port}) != FRONTEND_PORT ({fport})")
    except (OSError, json.JSONDecodeError):
        pass
    env_file = FRONTEND / ".env"
    try:
        vite = [ln for ln in env_file.read_text(encoding="utf-8").splitlines()
                if ln.startswith("VITE_API_URL=")]
        if vite and f":{bport}/" not in vite[0]:
            print(f"WARNING: frontend/.env VITE_API_URL does not point at backend port {bport}")
    except OSError:
        pass

# ---------------------------------------------------------------------------
# Docker mode (default) — the whole stack in containers via the root compose
# file: postgres + redis + alembic migrations + api + web.

def docker_bin() -> str:
    docker = shutil.which("docker")
    if not docker:
        fail("docker not found on PATH - install Docker Desktop.")
    return docker

def docker_mode(args: argparse.Namespace) -> int:
    native_only = []
    if args.web or args.android:
        native_only.append("--web/--android (emulator needs the tsx dev server)")
    if args.backend_only or args.frontend_only:
        native_only.append("--backend-only/--frontend-only")
    if args.backend_port or args.frontend_port:
        native_only.append("--backend-port/--frontend-port (ports are fixed by compose)")
    if native_only:
        fail(f"{', '.join(native_only)} only apply in --native mode.")

    docker = docker_bin()
    if subprocess.run([docker, "compose", "version"],
                      capture_output=True).returncode != 0:
        fail("docker compose plugin unavailable - update Docker Desktop.")
    if subprocess.run([docker, "info"], capture_output=True).returncode != 0:
        fail("Docker daemon is not running - start Docker Desktop first.")

    if args.down:
        return subprocess.run([docker, "compose", "down"],
                              cwd=PROJECT_ROOT).returncode

    # A clear message beats compose's cryptic bind failure.
    for port, label in ((8000, "API"), (3000, "Frontend"),
                        (5432, "Postgres"), (6379, "Redis")):
        if port_open("127.0.0.1", port):
            fail(f"{label} port {port} is already in use - stop the other "
                 f"process first (is the stack already running? "
                 f"`python main.py --down`).")

    cmd = [docker, "compose"]
    if args.seed:
        # The seed service is behind the 'seed' profile and runs once,
        # after migrations complete - safe to re-run (idempotent).
        cmd += ["--profile", "seed"]
    cmd += ["up", "--build"]

    child = spawn(cmd, PROJECT_ROOT, dict(os.environ))
    stream = start_stream(child, "DOCKER")

    print("========================================")
    print("AiROS Staff - Docker stack")
    print("========================================")
    print("Frontend: http://localhost:3000")
    print("API:      http://localhost:8000/api/v1   Docs: http://localhost:8000/docs")
    print("Postgres: 127.0.0.1:5432   Redis: 127.0.0.1:6379")
    if args.seed:
        print("Seed:     demo tenant will be created after migrations "
              "(admin@demo.local / employee@demo.local, Demo!Pass123)")
    else:
        print("Seed:     skipped - rerun with --seed for demo logins")
    print("First build can take several minutes. Ctrl+C stops the stack.")
    print("========================================")

    exit_code = 0
    try:
        exit_code = child.wait() or 0
    except KeyboardInterrupt:
        # Compose catches CTRL_BREAK and stops the containers itself.
        interrupt(child)
        reap(child, grace=60)
        if child.poll() is None:
            child.kill()
        # Belt: containers must not outlive the launcher.
        subprocess.run([docker, "compose", "stop"], cwd=PROJECT_ROOT,
                       capture_output=True, timeout=120)
    stream.join(timeout=2)
    return exit_code

# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the AiROS Staff system (Docker by default, "
                    "--native for bare-metal dev servers).")
    parser.add_argument("--backend-port", type=int)
    parser.add_argument("--frontend-port", type=int)
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--frontend-only", action="store_true")
    parser.add_argument("--web", action="store_true",
                        help="native mode: browser-only, skip the emulator")
    parser.add_argument("--android", action="store_true", help=argparse.SUPPRESS)  # legacy alias
    parser.add_argument("--native", action="store_true",
                        help="bare-metal dev servers (uvicorn --reload + tsx) "
                             "instead of Docker; required for the emulator flow")
    parser.add_argument("--seed", action="store_true",
                        help="docker mode: also run the demo-tenant seed profile")
    parser.add_argument("--down", action="store_true",
                        help="docker mode: stop the stack (compose down)")
    args = parser.parse_args()

    if not args.native:
        return docker_mode(args)

    if args.seed or args.down:
        fail("--seed/--down only apply in Docker mode (drop --native).")

    if not BACKEND.is_dir():
        fail(f"backend directory not found at {BACKEND}")
    if not FRONTEND.is_dir():
        fail(f"frontend directory not found at {FRONTEND}")
    if args.backend_only and args.frontend_only:
        fail("--backend-only and --frontend-only are mutually exclusive.")

    host = os.environ.get("BACKEND_HOST", "127.0.0.1")
    bport = args.backend_port or int(os.environ.get("BACKEND_PORT", "8000"))
    fport = args.frontend_port or int(os.environ.get("FRONTEND_PORT", "3000"))

    run_backend = not args.frontend_only
    run_frontend = not args.backend_only
    android = not args.web and not args.backend_only

    children: dict[str, subprocess.Popen[bytes]] = {}
    threads: list[threading.Thread] = []

    if run_backend:
        check_port_free(host, bport, "Backend")
        py = backend_python()
        probe = subprocess.run([py, "-c", "import uvicorn"], capture_output=True)
        if probe.returncode != 0:
            fail(f"uvicorn not importable via {py} - run: {py} -m pip install -r backend/requirements.txt")
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        children["BACKEND"] = spawn(
            [py, "-m", "uvicorn", "app.main:app", "--reload", "--host", host, "--port", str(bport)],
            BACKEND, env)

    if run_frontend:
        # server.ts listens on 0.0.0.0
        check_port_free("0.0.0.0", fport, "Frontend")
        fe_env = dict(os.environ, PORT=str(fport))
        if port_open("127.0.0.1", HMR_PORT):
            print(f"WARNING: HMR websocket port {HMR_PORT} is in use - starting frontend with DISABLE_HMR=true")
            fe_env["DISABLE_HMR"] = "true"
        npm = shutil.which("npm")
        if not npm:
            fail("npm not found on PATH - install Node.js first.")
        if not (FRONTEND / "node_modules").is_dir():
            fail("frontend/node_modules missing - run: npm install (inside frontend/)")
        children["FRONTEND"] = spawn([npm, "run", "dev"], FRONTEND, fe_env)

    print("========================================")
    print("AiROS Staff Development Environment")
    print("========================================")
    if run_backend:
        print(f"Backend:  http://{host}:{bport}   API: http://{host}:{bport}/api/v1   Docs: http://{host}:{bport}/docs")
    if run_frontend:
        print(f"Frontend: http://localhost:{fport}")
    if android:
        print("Mode:     Android emulator app (use --web for browser only)")
        print(f"Android:  AVD {os.environ.get('ANDROID_AVD') or 'auto'} -> app loads "
              f"http://10.0.2.2:{fport} (injected into capacitor.config.json server.url), "
              f"API via VITE_API_URL in frontend/.env")
        android_banner_warnings(bport, fport)
    else:
        print("Mode:     browser (default is emulator app)")
    print("Press Ctrl+C to stop both services.")
    print("========================================")
    if not android:
        print("note: frontend/.env VITE_API_URL must point at the backend URL above.")

    for tag, proc in children.items():
        threads.append(start_stream(proc, tag))

    exit_code = 0
    try:
        if android:
            android_flow(resolve_sdk(), bport, fport, children, threads)
        while True:
            for tag, proc in children.items():
                code = proc.poll()
                if code is not None:
                    print(f"[{tag}] exited with code {code}", flush=True)
                    for other in children.values():
                        if other is not proc:
                            interrupt(other)
                            reap(other)
                    return code or 1
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    except LaunchError as e:
        print(f"error: {e}", file=sys.stderr)
        exit_code = 1
    for proc in children.values():
        interrupt(proc)
    for proc in children.values():
        reap(proc)
    for t in threads:
        t.join(timeout=2)
    return exit_code

if __name__ == "__main__":
    sys.exit(main())
