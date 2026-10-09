#!/usr/bin/env python3
"""Install portable Codex conversation naming on Linux/macOS/WSL.

Copies program/config only. Does not transfer authentication or chat history.
"""
import argparse
import ast
import datetime
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

FILES = ["namer.py", "install.py", "config.json", "README.md", "test_namer.py"]


def preflight():
    if sys.version_info < (3, 10) or os.name != "posix":
        raise RuntimeError("Requires Python 3.10+ and Linux, macOS or WSL")
    binary = shutil.which("codex")
    if not binary:
        raise RuntimeError("Install/sign into Codex CLI first; codex must be on PATH")
    version = subprocess.run([binary, "--version"], text=True, capture_output=True, check=True).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="namer-protocol-") as directory:
        subprocess.run([binary, "app-server", "generate-json-schema", "--out", directory],
                       text=True, capture_output=True, timeout=30, check=True)
        files = list(Path(directory).rglob("ThreadSetNameParams.json"))
        if not files:
            raise RuntimeError("Codex does not provide thread/name/set; update Codex")
        props = json.loads(files[0].read_text())["properties"]
        if not {"name", "threadId"}.issubset(props):
            raise RuntimeError("Unexpected Codex naming protocol; review before installing")
    return version


def install(source, target, codex_home, check=True):
    source, target, codex_home = map(lambda p: Path(p).expanduser().resolve(), (source, target, codex_home))
    version = preflight() if check else "unchecked-test"
    hooks_path = codex_home / "hooks.json"
    # Read and validate first, so malformed existing hooks aren't overwritten.
    hooks = json.loads(hooks_path.read_text()) if hooks_path.exists() else {"hooks": {}}
    groups = hooks.setdefault("hooks", {}).setdefault("Stop", [])
    if not isinstance(groups, list):
        raise ValueError("Existing Stop hooks must be an array")
    for name in FILES:
        if not (source / name).is_file():
            raise FileNotFoundError(source / name)
        if name.endswith(".py"):
            ast.parse((source / name).read_text(), filename=str(source / name))
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    codex_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in FILES:
        dest = target / name
        if (source / name).resolve() == dest.resolve():
            continue
        # Updating keeps local settings. A fresh copy is always disabled until
        # the operator chooses to enable real-content inference.
        if name == "config.json":
            if dest.exists():
                continue
            cfg = json.loads((source / name).read_text())
            cfg["enabled"] = False
            dest.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
        else:
            shutil.copyfile(source / name, dest)
        dest.chmod(0o600)
    # Embed paths discovered on THIS computer, never the source computer.
    command = " ".join(shlex.quote(x) for x in ["env", "CODEX_HOME=" + str(codex_home),
                                                sys.executable, str(target / "namer.py"), "hook"])
    handler = {"type": "command", "command": command, "async": True,
               "timeout": 120, "statusMessage": "Checking conversation title"}
    manifest = target / "installation.json"
    previous = json.loads(manifest.read_text()).get("hook_command") if manifest.exists() else None
    # Only replace our own prior command; preserve all unrelated handlers.
    legacy = "python3 " + str(target / "namer.py") + " hook"
    remove = {command, legacy, previous} - {None}
    retained = []
    for group in groups:
        old_handlers = group.get("hooks", [])
        new_handlers = [h for h in old_handlers if h.get("command") not in remove]
        if new_handlers or not old_handlers:
            retained.append({**group, "hooks": new_handlers})
    retained.append({"hooks": [handler]})
    hooks["hooks"]["Stop"] = retained
    backup = None
    if hooks_path.exists():
        stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S%f")
        backup = hooks_path.with_name("hooks.json.backup-" + stamp)
        shutil.copyfile(hooks_path, backup)
        backup.chmod(0o600)
    temporary = hooks_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(hooks, ensure_ascii=False, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(hooks_path)
    record = {"version": "1.1.1", "codex_version": version, "install_dir": str(target),
              "codex_home": str(codex_home), "hook_command": command,
              "hooks_backup": str(backup) if backup else None}
    manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    manifest.chmod(0o600)
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--install-dir", type=Path,
                   default=Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "codex-conversation-namer")
    p.add_argument("--codex-home", type=Path,
                   default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
    p.add_argument("--check", action="store_true", help="Check runtime compatibility without installing")
    args = p.parse_args()
    if args.check:
        print(preflight())
        return
    result = install(Path(__file__).resolve().parent, args.install_dir, args.codex_home)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("Installed. Settings preserved; new installs disabled. Review/trust this hook using /hooks.")


if __name__ == "__main__":
    main()
