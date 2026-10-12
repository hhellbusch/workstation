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


def ensure_folders(storage, folders, check):
    existing = [folder for folder in folders if folder.is_dir()]
    missing = [str(folder) for folder in folders if not folder.is_dir()]
    notices = [f"Cursor folder {path} is not present yet." for path in missing]
    if not existing:
        return False, notices

    if storage.is_file():
        data = json.loads(storage.read_text())
    else:
        data = {}
    backup = data.setdefault("backupWorkspaces", {})
    recorded = backup.setdefault("folders", [])
    changed = False
    for folder in existing:
        uri = folder.resolve().as_uri()
        if any(isinstance(item, dict) and item.get("folderUri") == uri for item in recorded):
            continue
        changed = True
        if not check:
            recorded.append({"folderUri": uri})
    if changed and not check:
        storage.parent.mkdir(parents=True, exist_ok=True)
        storage.write_text(json.dumps(data, indent=4) + "\n")
    return changed, notices


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--entries", required=True)
    parser.add_argument("--folders", default="[]")
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
    notices = []
    try:
        changed = apply_entries(database, entries, args.check) if entries else False
    except sqlite3.OperationalError as exc:
        if "locked" not in str(exc).lower():
            raise
        changed = False
        notices.append(
            "Quit Cursor and run the bootstrap again to apply Cursor chat settings."
        )

    folders = []
    for item in json.loads(args.folders):
        folder = Path(item)
        if not folder.is_absolute():
            folder = args.home / folder
        folders.append(folder)
    folder_changed, folder_notices = ensure_folders(
        args.home / ".config/Cursor/User/globalStorage/storage.json",
        folders,
        args.check,
    )
    changed = changed or folder_changed
    notices.extend(folder_notices)

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
