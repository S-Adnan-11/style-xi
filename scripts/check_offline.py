"""Check a fresh source checkout with fictional data and guarded Python transport."""

import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


def finite_json(path):
    def reject(value):
        raise AssertionError(f"nonfinite JSON: {value}")
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)
    json.dumps(value, allow_nan=False)
    return value


def main():
    if Path.cwd().resolve() != ROOT:
        raise SystemExit("Run from the repository root.")
    if any((ROOT / name).exists() for name in ("data", "outputs")):
        raise SystemExit("Use a fresh checkout without data/ or outputs/ for this check.")
    print(f"Interpreter: {sys.executable}\n{platform.platform()} / {platform.python_version()}", flush=True)
    with tempfile.TemporaryDirectory(prefix="style-xi-offline-") as temp:
        log = Path(temp) / "network.log"
        env = {k: v for k, v in os.environ.items()
               if not k.upper().startswith(("HIGHLIGHTLY", "RAPIDAPI", "PYTHON", "PIP_", "UV_"))
               and k.upper() not in ("VIRTUAL_ENV", "GH_TOKEN", "GITHUB_TOKEN")}
        env.update(PYTHONPATH=os.pathsep.join((str(ROOT / "scripts/offline_guard"), str(ROOT))),
                   PYTHONNOUSERSITE="1", PYTHONUTF8="1", STYLE_XI_NETWORK_LOG=str(log),
                   STREAMLIT_BROWSER_GATHER_USAGE_STATS="false")

        def no_attempts():
            if log.exists() and log.stat().st_size:
                raise AssertionError("unexpected non-loopback transport attempt; check failed")

        def run(*args, timeout=180):
            print("+ python " + " ".join(args), flush=True)
            result = subprocess.run([sys.executable, *args], cwd=ROOT, env=env,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    timeout=timeout)
            print(result.stdout, end="", flush=True)
            print(result.stderr, end="", file=sys.stderr, flush=True)
            no_attempts()
            result.check_returncode()
            return result.stdout

        # Demonstrate actual interception before running any application code.
        probe = """import sitecustomize, socket
assert sitecustomize.ACTIVE
for attempt in (
    lambda: socket.getaddrinfo('offline.invalid', 443),
    lambda: socket.socket().connect(('192.0.2.1', 443)),
    lambda: socket.socket(type=socket.SOCK_DGRAM).sendto(b'x', ('192.0.2.1', 443)),
):
    try:
        attempt()
    except RuntimeError:
        pass
    else:
        raise AssertionError('guard failed')
"""
        subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env, check=True, timeout=20)
        assert log.read_text(encoding="utf-8").splitlines() == [
            "socket.getaddrinfo", "socket.connect", "socket.sendto"]
        log.unlink()
        print("Transport guard self-check passed (DNS, TCP, UDP).", flush=True)
        run("-m", "pip", "check")
        run("-c", "import pandas, sklearn, matplotlib, streamlit; print('Runtime imports OK')")

        # Exercise AppTest and real server startup before any example writes files.
        run("-m", "unittest", "discover", "-s", "tests", "-p", "test_ui.py", "-v")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        server_log = Path(temp) / "server.log"
        with server_log.open("w", encoding="utf-8") as output:
            process = subprocess.Popen([
                sys.executable, "-m", "streamlit", "run", "app.py",
                "--server.address", "127.0.0.1", "--server.port", str(port),
                "--server.headless", "true", "--browser.gatherUsageStats", "false",
            ], cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 45
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                while True:
                    no_attempts()
                    if process.poll() is not None:
                        raise AssertionError("Streamlit exited during startup")
                    try:
                        with opener.open(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as response:
                            assert response.status == 200 and response.read() == b"ok"
                        break
                    except (urllib.error.URLError, TimeoutError, ConnectionError):
                        if time.monotonic() >= deadline:
                            raise AssertionError("Streamlit startup timeout") from None
                        time.sleep(0.2)
                print("Pristine Streamlit loopback health passed (HTTP startup evidence).", flush=True)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        no_attempts()
        assert not (ROOT / "data").exists() and not (ROOT / "outputs").exists()

        assert "fictional" in run("examples/synthetic_demo.py")
        run("-m", "style_xi", "import-cache", "--input", "data/synthetic", "--output", "outputs/sample.json")
        run("-m", "style_xi", "profiles", "--input", "outputs/sample.json", "--output", "outputs/profiles.json")
        assert "fictional" in run("examples/similarity_demo.py")
        comparison = run("-m", "style_xi", "compare", "--input", "outputs/fictional-profiles.json",
                         "--cohort", "data/similarity/cohort.json", "--query",
                         "highlightly/900301/2025/regular/900101/901201", "--min-minutes", "90",
                         "--min-appearances", "2", "--limit", "5", "--output", "outputs/neighbours.json")
        assert "Fictional activity comparison" in comparison
        for path in (ROOT / "outputs").glob("*.json"):
            finite_json(path)
        profiles = finite_json(ROOT / "outputs/profiles.json")
        aster = next(p for p in profiles["profiles"] if p["player_id"] == 900201
                     and p["team_id"] == 900101 and p["stage"] == "regular")
        assert aster["metrics"]["passes_per_90"]["value"] == 75
        assert aster["metrics"]["passes_success_pct"]["value"] == 82
        neighbours = finite_json(ROOT / "outputs/neighbours.json")
        assert [n["candidate"]["identity"]["player_id"] for n in neighbours["neighbours"]] == [
            901202, 901203, 901206, 901204, 901205]
        assert neighbours["neighbours"][0]["distance"] == neighbours["neighbours"][1]["distance"]
        run("-m", "unittest", "discover", "-s", "tests", "-v")
        no_attempts()
        summary = (f"Offline checks passed: {platform.platform()}, CPython {platform.python_version()}.\n"
                   f"requirements.txt SHA-256: {hashlib.sha256((ROOT / 'requirements.txt').read_bytes()).hexdigest()}\n"
                   "Dependency consistency, runtime imports, pristine AppTest and loopback health, "
                   "fictional CLI outputs and full unittest suite passed.\n"
                   "Zero unexpected non-loopback Python socket attempts; no provider credentials.\n"
                   "Health is startup evidence; browser rendering was not checked.\n")
        print(summary, flush=True)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
                stream.write(summary)


if __name__ == "__main__":
    main()
