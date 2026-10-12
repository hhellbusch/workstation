#!/usr/bin/env python3
"""Set Cursor preferences that live in the state database, not settings.json."""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

KEY_RE = re.compile(r"^cursor/[A-Za-z0-9._-]+$")


def stored(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if not text or len(text) > 32 or any(char in text for char in "\n\r"):
        raise ValueError(f"refusing cursor state value {text!r}")
    return text


def current_value(connection, key):
    row = connection.execute(
        "SELECT value FROM ItemTable WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    value = row[0]
    if isinstance(value, bytes):
        return value.decode()
    return value


def apply_entries(database, entries, check):
    created = False
    if not database.is_file():
        if check:
            return True
        database.parent.mkdir(parents=True, exist_ok=True)
        database.parent.chmod(0o755)
        connection = sqlite3.connect(database, timeout=1)
        created = True
    else:
        mode = "ro" if check else "rw"
        connection = sqlite3.connect(f"file:{database}?mode={mode}", uri=True, timeout=1)

    changed = False
    try:
        if not check:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS ItemTable "
                "(key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)"
            )
        for key, value in entries:
            try:
                current = current_value(connection, key)
            except sqlite3.OperationalError as exc:
                if check and "no such table" in str(exc):
                    return True
                raise
            if current == value:
                continue
            changed = True
            if not check:
                connection.execute(
                    "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                    (key, value),
                )
        if changed and not check:
            connection.commit()
    finally:
        connection.close()

    if not check and (created or changed):
        database.chmod(0o600)
    return changed


def cursor_installed():
    return any(path.exists() for path in (Path("/usr/bin/cursor"), Path("/usr/share/cursor/cursor")))


def cursor_running():
    proc = Path("/proc")
    if not proc.is_dir():
        return False
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "comm").read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if command in {"cursor", "cursor-bin"}:
            return True
    return False


def folder_uri(folder):
    return folder.resolve().as_uri()


def recorded_folders(storage):
    if not storage.is_file():
        return []
    data = json.loads(storage.read_text())
    folders = data.get("backupWorkspaces", {}).get("folders", [])
    return [item.get("folderUri") for item in folders if isinstance(item, dict)]


def ensure_folders(storage, folders, check):
    missing = [str(folder) for folder in folders if not folder.is_dir()]
    if missing:
        raise ValueError("Cursor folder is not on disk yet: " + ", ".join(missing))
    if not folders:
        return False
    if not storage.is_file():
        raise ValueError("Open Cursor once, quit it, then run the bootstrap again.")

    data = json.loads(storage.read_text())
    backup = data.setdefault("backupWorkspaces", {})
    recorded = backup.setdefault("folders", [])
    changed = False
    for folder in folders:
        uri = folder_uri(folder)
        if any(isinstance(item, dict) and item.get("folderUri") == uri for item in recorded):
            continue
        changed = True
        if not check:
            recorded.append({"folderUri": uri})
    if changed and not check:
        storage.write_text(json.dumps(data, indent=4) + "\n")
        storage.chmod(0o600)
    return changed


def cursor_report(args, entries, folders, database, storage):
    pending = []
    if args.root is not None:
        for relative in json.loads(args.dotfiles):
            source = args.root / "files" / "home" / relative
            destination = args.home / relative
            if not source.is_file():
                continue
            current = destination.read_text(encoding="utf-8") if destination.is_file() else None
            if current != source.read_text(encoding="utf-8"):
                pending.append(relative)

    installed = cursor_installed()
    needs_launch = installed and (entries or folders) and not storage.is_file()
    if storage.is_file():
        known = set(recorded_folders(storage))
        for folder in folders:
            if folder_uri(folder) not in known:
                pending.append(str(folder))
        if entries and database.is_file():
            try:
                connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=0.2)
            except sqlite3.OperationalError:
                pending.append("state database")
            else:
                try:
                    for key, value in entries:
                        if current_value(connection, key) != value:
                            pending.append(key)
                except sqlite3.OperationalError:
                    pending.append("state database")
                finally:
                    connection.close()
        elif entries:
            pending.extend(key for key, _value in entries)

    return {
        "pending": pending,
        "needs_launch": needs_launch,
        "running": cursor_running(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--entries", required=True)
    parser.add_argument("--folders", default="[]")
    parser.add_argument("--dotfiles", default="[]")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--pending", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    raw = json.loads(args.entries)
    entries = []
    for item in raw:
        key = item["key"]
        if not KEY_RE.match(key):
            raise ValueError(f"refusing cursor state key {key!r}")
        entries.append((key, stored(item["value"])))

    database = args.home / ".config/Cursor/User/globalStorage/state.vscdb"
    storage = args.home / ".config/Cursor/User/globalStorage/storage.json"
    folders = []
    for item in json.loads(args.folders):
        folder = Path(item)
        if not folder.is_absolute():
            folder = args.home / folder
        folders.append(folder)

    if args.pending:
        json.dump(cursor_report(args, entries, folders, database, storage), sys.stdout)
        sys.stdout.write("\n")
        return 0

    if (entries or folders) and cursor_installed() and not storage.is_file():
        print("Open Cursor once, quit it, then run the bootstrap again.", file=sys.stderr)
        return 1
    if cursor_running() and cursor_report(args, entries, folders, database, storage)["pending"]:
        print("Quit Cursor, then run the bootstrap again.", file=sys.stderr)
        return 1

    notices = []
    try:
        changed = apply_entries(database, entries, args.check) if entries else False
    except sqlite3.OperationalError as exc:
        if "locked" not in str(exc).lower():
            raise
        print("Quit Cursor, then run the bootstrap again.", file=sys.stderr)
        return 1

    changed = ensure_folders(storage, folders, args.check) or changed
    json.dump({"changed": changed, "notices": notices}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        json.dump({"changed": False, "notices": [str(exc)]}, sys.stdout)
        sys.stdout.write("\n")
        sys.exit(1)
