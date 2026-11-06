"""Exercise process management with real HTTP processes in an isolated project."""

import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipUnless(shutil.which("node"), "Node.js is required for service lifecycle tests")
class StartScriptTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / "start.sh").is_file(), "start.sh must provide the service entry point")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project with spaces"
        self.project.mkdir()
        shutil.copy2(ROOT / "start.sh", self.project / "start.sh")
        python = self.project / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        (self.project / "fastapi.py").write_text("", encoding="utf-8")
        # A small real server avoids dependency downloads and any access to corpus data.
        (self.project / "uvicorn.py").write_text('''
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode())
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("app")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if os.environ.get("FAIL_BACKEND"):
        raise SystemExit(1)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
''', encoding="utf-8")
        vite = self.project / "frontend/node_modules/vite/bin/vite.js"
        vite.parent.mkdir(parents=True)
        vite.write_text('''
const http = require('node:http');
const fs = require('node:fs');
const { spawn } = require('node:child_process');
if (process.env.FAIL_FRONTEND) process.exit(1);
const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], {stdio: 'ignore'});
fs.writeFileSync(process.env.CHILD_PID_FILE, String(child.pid));
const port = Number(process.argv[process.argv.indexOf('--port') + 1]);
http.createServer((req, res) => {
  if (req.url.startsWith('/api/')) {
    http.get(process.env.DATASETS_BACKEND_URL + req.url, upstream => upstream.pipe(res));
  } else { res.end('frontend ready'); }
}).listen(port, '127.0.0.1');
''', encoding="utf-8")
        backend_port, frontend_port = free_port(), free_port()
        while frontend_port == backend_port:
            frontend_port = free_port()
        self.env = {
            **os.environ,
            "BACKEND_PORT": str(backend_port),
            "FRONTEND_PORT": str(frontend_port),
            "START_TIMEOUT": "5",
            "STOP_TIMEOUT": "3",
            "CHILD_PID_FILE": str(self.project / "child.pid"),
        }
        self.addCleanup(self.cleanup_processes)

    def run_script(self, command, *, success=True, **env):
        result = subprocess.run(
            ["bash", str(self.project / "start.sh"), command],
            cwd=self.temp.name, env={**self.env, **env},
            capture_output=True, text=True, timeout=30,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def cleanup_processes(self):
        self.run_script("stop")

    def pids(self):
        return {file.stem: int(file.read_text().splitlines()[0])
                for file in (self.project / ".run").glob("*.pid")}

    def assert_port_closed(self, port):
        with socket.socket() as sock:
            sock.settimeout(1)
            self.assertNotEqual(sock.connect_ex(("127.0.0.1", int(port))), 0)

    def assert_process_stopped(self, pid):
        state = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
        self.assertTrue(not state.stdout.strip() or state.stdout.strip().startswith("Z"), state.stdout)

    def crash_frontend(self):
        pid = self.pids()["frontend"]
        # Always reap this fixture's orphan group even when the regression assertion fails.
        def cleanup_group():
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.addCleanup(cleanup_group)
        os.kill(pid, signal.SIGKILL)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
            if not state.stdout.strip() or state.stdout.strip().startswith("Z"):
                return pid
            time.sleep(0.02)
        self.fail("frontend leader did not exit after SIGKILL")

    def test_start_is_idempotent_restart_replaces_processes_and_stop_closes_ports(self):
        self.run_script("start")
        original = self.pids()
        self.assertEqual(set(original), {"backend", "frontend"})
        self.run_script("start")
        self.assertEqual(self.pids(), original)
        self.run_script("status")
        with urlopen(f"http://127.0.0.1:{self.env['FRONTEND_PORT']}/api/health", timeout=2) as response:
            self.assertEqual(json.load(response), {"status": "ok"})
        self.run_script("restart")
        self.assertTrue(all(self.pids()[name] != pid for name, pid in original.items()))
        child_pid = int((self.project / "child.pid").read_text())
        self.run_script("stop")
        self.run_script("stop")
        self.assertEqual(self.pids(), {})
        for key in ("BACKEND_PORT", "FRONTEND_PORT"):
            self.assert_port_closed(self.env[key])
        self.assert_process_stopped(child_pid)
        self.run_script("status", success=False)

    def test_frontend_failure_rolls_back_backend(self):
        result = self.run_script("start", success=False, FAIL_FRONTEND="1")
        self.assertIn("frontend 启动失败", result.stderr)
        self.assertEqual(self.pids(), {})
        self.assert_port_closed(self.env["BACKEND_PORT"])

    def test_occupied_port_is_reported_without_starting_backend(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", int(self.env["FRONTEND_PORT"])))
            listener.listen()
            result = self.run_script("start", success=False)
            self.assertIn(self.env["FRONTEND_PORT"], result.stderr)
            self.assertEqual(self.pids(), {})
            self.assert_port_closed(self.env["BACKEND_PORT"])

    def test_stale_pid_file_never_stops_an_unrelated_process(self):
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
        self.addCleanup(unrelated.wait)
        self.addCleanup(lambda: unrelated.poll() is None and unrelated.send_signal(signal.SIGTERM))
        run_dir = self.project / ".run"
        run_dir.mkdir()
        (run_dir / "backend.pid").write_text(f"{unrelated.pid}\nold identity\n{'0' * 32}\n", encoding="utf-8")
        self.run_script("stop")
        self.assertIsNone(unrelated.poll())
        self.assertEqual(self.pids(), {})

    def test_stop_does_not_require_installed_app_dependencies(self):
        self.run_script("start")
        shutil.rmtree(self.project / ".venv")
        shutil.rmtree(self.project / "frontend/node_modules")
        self.run_script("stop")
        self.assertEqual(self.pids(), {})
        self.assert_port_closed(self.env["FRONTEND_PORT"])

    def test_stop_cleans_children_after_the_service_leader_crashes(self):
        self.run_script("start")
        child_pid = int((self.project / "child.pid").read_text())
        self.crash_frontend()
        self.run_script("status", success=False)
        self.run_script("stop")
        self.assert_process_stopped(child_pid)
        self.assertEqual(self.pids(), {})

    def test_start_recovers_a_crashed_service_without_leaking_its_children(self):
        self.run_script("start")
        backend_pid = self.pids()["backend"]
        child_pid = int((self.project / "child.pid").read_text())
        frontend_pid = self.crash_frontend()
        self.run_script("start")
        self.assertEqual(self.pids()["backend"], backend_pid)
        self.assertNotEqual(self.pids()["frontend"], frontend_pid)
        self.assert_process_stopped(child_pid)


if __name__ == "__main__":
    unittest.main()
