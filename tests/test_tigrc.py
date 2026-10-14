import shutil
import subprocess
from pathlib import Path

import pytest

from deepwick_spec.ansi import runs, style_of
from deepwick_spec.check_port import check_port
from deepwick_spec.palette import load_palette
from deepwick_spec.tui import capture, tmux_available

REPO = Path(__file__).resolve().parents[1]
PALETTE = load_palette()
C = PALETTE.colors


def isolated_env(tmp_path, **extra):
    dirs = {"HOME": tmp_path / "home"}
    for kind in ("CONFIG", "DATA", "STATE", "CACHE"):
        dirs[f"XDG_{kind}_HOME"] = tmp_path / kind.lower()
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    env = {key: str(path) for key, path in dirs.items()}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
    env.update({key: str(value) for key, value in extra.items()})
    return env


def make_repo(root):
    git = ["git", "-C", str(root), "-c", "user.name=Deepwick", "-c", "user.email=deepwick@example.invalid"]
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "PATH": "/usr/bin:/bin"}
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, env=env)
    (root / "app.py").write_text('def greet(name):\n    return "Hello, " + name\n')
    (root / "notes.txt").write_text("Deepwick sample repository.\n")
    subprocess.run([*git, "add", "."], check=True, env=env)
    subprocess.run([*git, "commit", "-qm", "Initial commit"], check=True, env=env)
    subprocess.run([*git, "tag", "v0.1"], check=True, env=env)
    (root / "app.py").write_text('def greet(name):\n    return "Hi, " + name\n')
    subprocess.run([*git, "commit", "-qam", "Shorter greeting"], check=True, env=env)
    (root / "app.py").write_text('def greet(name):\n    return "Hey, " + name\n')
    (root / "new.py").write_text("print('new')\n")
    subprocess.run([*git, "add", "new.py"], check=True, env=env)
    (root / "untracked.txt").write_text("scratch\n")
    return root


THEME = REPO / "deepwick.tigrc"
requires_tig = pytest.mark.skipif(shutil.which("tig") is None, reason="requires tig")
NAMES = {"default", "black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"} | {f"color{i}" for i in range(8, 16)}
ATTRS = {"bold", "dim", "reverse", "underline", "normal", "standout", "blink"}
EXPECTED = {
    "main.id": ("yellow", "default"), "main.author": ("color12", "default"), "main.date": ("color8", "default"),
    "diff-add": ("green", "default"), "diff-del": ("red", "default"),
    "stat-staged": ("green", "default"), "stat-unstaged": ("blue", "default"), "stat-untracked": ("cyan", "default"),
    "title-focus": ("black", "blue"), "cursor": ("default", "black"),
    "main-head": ("cyan", "default"), "main-tag": ("magenta", "default"),
}


def entries():
    assert THEME.is_file(), "deepwick.tigrc missing"
    result = {}
    for line in THEME.read_text(encoding="utf-8").splitlines():
        parts = line.split("#", 1)[0].split()
        if parts:
            assert parts[0] == "color", line
            result[parts[1]] = (parts[2], parts[3], tuple(parts[4:]))
    return result


def test_only_ansi_slots_and_attributes():
    for area, (fg, bg, attrs) in entries().items():
        assert fg in NAMES and bg in NAMES, area
        assert set(attrs) <= ATTRS, area


def test_role_colors():
    e = entries()
    for area, (fg, bg) in EXPECTED.items():
        assert e[area][:2] == (fg, bg), area


@requires_tig
def test_tig_accepts_every_line(tmp_path):
    env = {**isolated_env(tmp_path), "PATH": "/usr/bin:/bin", "TIGRC_USER": str(THEME), "TIGRC_SYSTEM": "/dev/null"}
    # setsid: no controlling terminal, so tig cannot grab the user's tty; it parses the config, warns, and exits.
    result = subprocess.run(["setsid", "-w", "tig"], env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, cwd=tmp_path, timeout=10)
    assert "tig warning" not in result.stdout + result.stderr


@pytest.mark.skipif(not (tmux_available() and shutil.which("tig")), reason="requires tmux and tig")
def test_tig_renders_slots(tmp_path):
    repo = make_repo(tmp_path / "repo")
    # Keep the system tigrc: it defines the view columns; TIGRC_USER still replaces the user's config.
    env = isolated_env(tmp_path, TIGRC_USER=THEME, TERM="tmux-256color")
    text = capture(f"cd {repo} && tig", env, size=(120, 30), wait_for="Initial commit")
    assert style_of(text, "Deepwick")["fg"] == "ansi:12"
    assert any(s["fg"] == "ansi:0" and s["bg"] == "ansi:4" for _, s in runs(text))


def test_port_conventions():
    assert check_port(REPO, PALETTE.allowed_hex()) == []
