#!/usr/bin/env python3
"""Write Firefox user.js and remove bookmarks that match a system skeleton."""

import argparse
import configparser
import json
import sqlite3
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT_GUIDS = {
    "root________",
    "menu________",
    "toolbar_____",
    "unfiled_____",
    "mobile______",
}
ROOT_TITLES = {
    "Bookmarks Toolbar",
    "Bookmarks Menu",
    "Other Bookmarks",
    "Mobile Bookmarks",
}


class StockBookmarks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = set()
        self.folders = set()
        self._capture = None
        self._text = []
        self._personal_toolbar = False

    def handle_starttag(self, tag, attrs):
        attributes = {key.lower(): value for key, value in attrs}
        if tag == "h3":
            self._capture = "h3"
            self._text = []
            self._personal_toolbar = attributes.get("personal_toolbar_folder") == "true"
        elif tag == "a" and attributes.get("href"):
            self._capture = "a"
            self._text = []
            self.urls.add(attributes["href"].strip())

    def handle_endtag(self, tag):
        if tag != self._capture:
            return
        title = " ".join("".join(self._text).split())
        if tag == "h3" and title and not self._personal_toolbar and title not in ROOT_TITLES:
            self.folders.add(title)
        self._capture = None
        self._text = []

    def handle_data(self, data):
        if self._capture:
            self._text.append(data)


def firefox_is_running():
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
        if command in {"firefox", "firefox-bin"}:
            return True
    return False


def profile_directories(home):
    profiles = []
    for ini_path in (
        home / ".config/mozilla/firefox/profiles.ini",
        home / ".mozilla/firefox/profiles.ini",
    ):
        if not ini_path.is_file():
            continue
        parser = configparser.ConfigParser()
        parser.read(ini_path)
        for section in parser.sections():
            if not parser.has_option(section, "Path"):
                continue
            path = Path(parser.get(section, "Path"))
            if parser.get(section, "IsRelative", fallback="1") == "1":
                path = ini_path.parent / path
            if path.is_dir():
                profiles.append(path)
    return profiles


def load_stock(path):
    parser = StockBookmarks()
    parser.feed(Path(path).read_text(encoding="utf-8", errors="replace"))
    return parser.urls, parser.folders


def normalized(url):
    return url.rstrip("/")


def delete_folder(connection, folder_id):
    children = connection.execute(
        "SELECT id, type FROM moz_bookmarks WHERE parent = ?",
        (folder_id,),
    ).fetchall()
    for child_id, child_type in children:
        if child_type == 2:
            delete_folder(connection, child_id)
        else:
            connection.execute("DELETE FROM moz_bookmarks WHERE id = ?", (child_id,))
    connection.execute("DELETE FROM moz_bookmarks WHERE id = ?", (folder_id,))


def clear_stock_bookmarks(database, urls, folders):
    wanted = {normalized(url) for url in urls if url}
    connection = sqlite3.connect(database, timeout=1)
    try:
        connection.execute("BEGIN IMMEDIATE")
        removed = 0
        if folders:
            rows = connection.execute(
                "SELECT id, title, guid FROM moz_bookmarks WHERE type = 2"
            ).fetchall()
            for folder_id, title, guid in rows:
                if guid in ROOT_GUIDS or title not in folders:
                    continue
                delete_folder(connection, folder_id)
                removed += 1
        if wanted:
            bookmarks = connection.execute(
                """
                SELECT moz_bookmarks.id, moz_places.url
                FROM moz_bookmarks
                JOIN moz_places ON moz_places.id = moz_bookmarks.fk
                WHERE moz_bookmarks.type = 1
                """
            ).fetchall()
            for bookmark_id, url in bookmarks:
                if url and normalized(url) in wanted:
                    connection.execute("DELETE FROM moz_bookmarks WHERE id = ?", (bookmark_id,))
                    removed += 1
        connection.commit()
        return removed
    except sqlite3.OperationalError:
        connection.rollback()
        raise
    finally:
        connection.close()


def firefox_installed():
    return any(path.exists() for path in (Path("/usr/bin/firefox"), Path("/usr/lib64/firefox/firefox")))


def stock_bookmarks_present(database, urls, folders):
    wanted = {normalized(url) for url in urls if url}
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=0.2)
    except sqlite3.OperationalError:
        return None
    try:
        if folders:
            rows = connection.execute(
                "SELECT title, guid FROM moz_bookmarks WHERE type = 2"
            ).fetchall()
            for title, guid in rows:
                if guid not in ROOT_GUIDS and title in folders:
                    return True
        if wanted:
            places = connection.execute("SELECT url FROM moz_places").fetchall()
            for (url,) in places:
                if url and normalized(url) in wanted:
                    return True
        return False
    except sqlite3.OperationalError:
        return None
    finally:
        connection.close()


def extension_needs_update(profile, extension):
    source = Path(extension["path"])
    destination = profile / "extensions" / f"{extension['id']}.xpi"
    if not source.is_file():
        return False
    payload = source.read_bytes()
    return not destination.is_file() or destination.read_bytes() != payload


def install_extensions(profile, extensions):
    destination_dir = profile / "extensions"
    changed = False
    for extension in extensions:
        if not extension_needs_update(profile, extension):
            continue
        source = Path(extension["path"])
        destination = destination_dir / f"{extension['id']}.xpi"
        destination_dir.mkdir(mode=0o755, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        destination.chmod(0o644)
        changed = True
    return changed


def write_user_js(profile, source):
    destination = profile / "user.js"
    contents = source.read_text(encoding="utf-8")
    if destination.is_file() and destination.read_text(encoding="utf-8") == contents:
        return False
    destination.write_text(contents, encoding="utf-8")
    destination.chmod(0o644)
    return True


def load_extensions(manifest):
    if manifest is None or not manifest.is_file():
        return []
    return json.loads(manifest.read_text(encoding="utf-8")).get("extensions", [])


def firefox_report(home, user_js, stock_html, manifest):
    profiles = profile_directories(home)
    extensions = load_extensions(manifest)
    stock_urls, stock_folders = set(), set()
    if stock_html and stock_html.is_file():
        stock_urls, stock_folders = load_stock(stock_html)
    pending = []
    if profiles and user_js.is_file():
        desired = user_js.read_text(encoding="utf-8")
        if any((profile / "user.js").read_text(encoding="utf-8") != desired
               if (profile / "user.js").is_file() else True
               for profile in profiles):
            pending.append("user.js")
    for extension in extensions:
        if any(extension_needs_update(profile, extension) for profile in profiles):
            pending.append(extension["id"])
    if profiles and (stock_urls or stock_folders):
        for profile in profiles:
            database = profile / "places.sqlite"
            if not database.is_file():
                continue
            if stock_bookmarks_present(database, stock_urls, stock_folders):
                pending.append("stock bookmarks")
                break
    return {
        "pending": pending,
        "needs_profile": firefox_installed() and not profiles,
        "running": firefox_is_running(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-js", required=True, type=Path)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--stock-html", type=Path)
    parser.add_argument("--extensions-manifest", type=Path)
    parser.add_argument("--pending", action="store_true")
    args = parser.parse_args()

    report = firefox_report(args.home, args.user_js, args.stock_html, args.extensions_manifest)
    if args.pending:
        json.dump(report, sys.stdout)
        sys.stdout.write("\n")
        return 0

    if report["needs_profile"]:
        print(
            "Open Firefox once so it creates a profile, quit it, then run the bootstrap again.",
            file=sys.stderr,
        )
        return 1
    if report["running"] and report["pending"]:
        print("Quit Firefox, then run the bootstrap again.", file=sys.stderr)
        return 1

    notices = []
    changed = False
    profiles = profile_directories(args.home)
    if not profiles:
        json.dump({"changed": False, "notices": notices}, sys.stdout)
        sys.stdout.write("\n")
        return 0

    for profile in profiles:
        if write_user_js(profile, args.user_js):
            changed = True

    extensions = load_extensions(args.extensions_manifest)
    for profile in profiles:
        if extensions and install_extensions(profile, extensions):
            changed = True

    stock_urls, stock_folders = set(), set()
    if args.stock_html and args.stock_html.is_file():
        stock_urls, stock_folders = load_stock(args.stock_html)

    if stock_urls or stock_folders:
        for profile in profiles:
            database = profile / "places.sqlite"
            if not database.is_file():
                continue
            try:
                removed = clear_stock_bookmarks(database, stock_urls, stock_folders)
            except sqlite3.OperationalError:
                print("Quit Firefox, then run the bootstrap again.", file=sys.stderr)
                return 1
            if removed:
                changed = True

    json.dump({"changed": changed, "notices": notices}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
