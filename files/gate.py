#!/usr/bin/env python3
"""Decide whether Firefox or Cursor must be closed or opened before changes."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def report(script, args):
    proc = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout).strip() or f"{script.name} failed"
        return {"action": "abort", "message": message}
    return json.loads(proc.stdout)


def blocker(status, quit_message, open_message):
    if status.get("action") == "abort":
        return "abort", status["message"]
    pending = status.get("pending") or []
    needs_user = status.get("needs_profile") or status.get("needs_launch")
    if not pending and not needs_user:
        return None
    if status.get("running"):
        detail = ", ".join(pending) if pending else "setup"
        return "abort", f"{quit_message} Still needed: {detail}."
    if needs_user:
        return "pause", open_message
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--entries", default="[]")
    parser.add_argument("--folders", default="[]")
    parser.add_argument("--dotfiles", default="[]")
    parser.add_argument("--extensions-manifest", type=Path)
    parser.add_argument("--stock-html", type=Path)
    args = parser.parse_args()

    firefox_args = [
        "--pending",
        "--home",
        str(args.home),
        "--user-js",
        str(args.root / "files" / "firefox" / "user.js"),
    ]
    if args.extensions_manifest:
        firefox_args.extend(["--extensions-manifest", str(args.extensions_manifest)])
    if args.stock_html:
        firefox_args.extend(["--stock-html", str(args.stock_html)])
    firefox = report(args.root / "files" / "firefox" / "apply.py", firefox_args)

    cursor_args = [
        "--pending",
        "--home",
        str(args.home),
        "--root",
        str(args.root),
        "--entries",
        args.entries,
        "--folders",
        args.folders,
        "--dotfiles",
        args.dotfiles,
    ]
    cursor = report(args.root / "files" / "cursor" / "apply_state.py", cursor_args)

    blockers = [
        blocker(
            firefox,
            "Quit Firefox, then run the bootstrap again.",
            "Open Firefox once so it creates a profile, then quit Firefox.\nPress Enter to continue.",
        ),
        blocker(
            cursor,
            "Quit Cursor, then run the bootstrap again.",
            "Open Cursor once, then quit Cursor.\nPress Enter to continue.",
        ),
    ]
    chosen = [item for item in blockers if item]
    aborts = [message for action, message in chosen if action == "abort"]
    pauses = [message for action, message in chosen if action == "pause"]
    if aborts:
        action = "abort"
        message = "\n".join(aborts)
    elif pauses:
        action = "pause"
        message = "\n".join(pauses)
    else:
        action = "ok"
        message = ""
    json.dump({"action": action, "message": message}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
