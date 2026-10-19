"""summarize_logs.py parses the access-log stage fields — including the
pw= token appended at end-of-line, and degrades to "-" when absent."""
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "perf"
    / "summarize_logs.py"
)


def _run(stdin: str) -> str:
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "--min-count", "1"],
        input=stdin, capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_parses_pw_at_end_of_line():
    out = _run(
        "method=GET path=/api/v1/tasks status=200 duration_ms=900 "
        "db=800/40x6 redis=10x2 ext=0 user=u company=c pw=250\n"
        "method=GET path=/api/v1/tasks status=200 duration_ms=1500 "
        "db=1400/60x6 redis=8x2 ext=0 user=u company=c pw=700\n"
    )
    line = next(l for l in out.splitlines() if "GET /api/v1/tasks" in l)
    cols = line.split()
    assert cols[7] == "700"  # pw95 column = max of the two samples
    assert "*SLOW" in line and "POOLWAIT" in line  # 183ms/q, 700 pw95


def test_absent_pw_shows_dash_and_no_poolwait_flag():
    out = _run(
        "method=GET path=/api/v1/zones status=304 duration_ms=60 "
        "db=45/10x1 redis=0x0 ext=0 user=u company=c\n"
    )
    line = next(l for l in out.splitlines() if "GET /api/v1/zones" in l)
    cols = line.split()
    assert cols[7] == "-"  # pw95 column
    assert "POOLWAIT" not in line


def test_noise_lines_are_skipped():
    out = _run(
        "random noise\n"
        "method=GET path=/api/v1/me status=200 duration_ms=10 "
        "db=5/2x1 redis=0x0 ext=0 user=u company=c pw=3\n"
    )
    assert "1 requests" in out
    assert "GET /api/v1/me" in out
