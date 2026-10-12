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


def write_user_js(profile, source):
    destination = profile / "user.js"
    contents = source.read_text(encoding="utf-8")
    if destination.is_file() and destination.read_text(encoding="utf-8") == contents:
        return False
    destination.write_text(contents, encoding="utf-8")
    destination.chmod(0o644)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-js", required=True, type=Path)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--stock-html", type=Path)
    args = parser.parse_args()

    notices = []
    changed = False
    profiles = profile_directories(args.home)
    if not profiles:
        if any(Path(path).exists() for path in ("/usr/bin/firefox", "/usr/lib64/firefox/firefox")):
            notices.append("Open Firefox once, then run the bootstrap again to apply Firefox settings.")
        json.dump({"changed": False, "notices": notices}, sys.stdout)
        sys.stdout.write("\n")
        return 0

    for profile in profiles:
        if write_user_js(profile, args.user_js):
            changed = True

    stock_urls, stock_folders = set(), set()
    if args.stock_html and args.stock_html.is_file():
        stock_urls, stock_folders = load_stock(args.stock_html)

    running = firefox_is_running()
    if running:
        message = "Quit Firefox and run the bootstrap again to load the blank new tab, privacy settings, and disabled password manager"
        if stock_urls or stock_folders:
            message += ", and to remove the stock bookmarks"
        notices.append(message + ".")
    elif stock_urls or stock_folders:
        for profile in profiles:
            database = profile / "places.sqlite"
            if not database.is_file():
                continue
            try:
                removed = clear_stock_bookmarks(database, stock_urls, stock_folders)
            except sqlite3.OperationalError:
                notices.append("Quit Firefox and run the bootstrap again to remove the stock bookmarks.")
                break
            if removed:
                changed = True

    json.dump({"changed": changed, "notices": notices}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
