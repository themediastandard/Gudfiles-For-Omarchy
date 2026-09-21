"""Persistent folder shortcuts and a five-folder MRU, shared by all windows."""
from contextlib import closing, contextmanager
import os
from pathlib import Path
import sqlite3


class FolderLocations:
    def __init__(self, database=None):
        self.database = database or Path.home() / '.local/share/omarchy-file-picker/folders.sqlite3'

    @staticmethod
    def key(path):
        # Normalize spelling without contacting an offline mount or dereferencing
        # symlinks. Shortcuts refer to the path the user actually chose.
        return os.path.abspath(os.path.expanduser(str(path)))

    @contextmanager
    def _write(self):
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.database.touch(mode=0o600, exist_ok=True)
        with closing(sqlite3.connect(self.database, timeout=.2)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS favorites (path TEXT PRIMARY KEY, position INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS recents (path TEXT PRIMARY KEY, position INTEGER NOT NULL)')
            yield db

    def read(self):
        if not self.database.exists():
            return [], []
        with closing(sqlite3.connect(self.database, timeout=.2)) as db, db:
            db.execute('BEGIN')
            return tuple([Path(row[0]) for row in db.execute(
                f'SELECT path FROM {table} ORDER BY position {order} {limit}')]
                for table, order, limit in (('favorites', 'ASC', ''), ('recents', 'DESC', 'LIMIT 5')))

    def set_favorite(self, path, present):
        key = self.key(path)
        with self._write() as db:
            if present:
                db.execute('INSERT OR IGNORE INTO favorites VALUES (?, '
                           '(SELECT COALESCE(MAX(position), 0) + 1 FROM favorites))', (key,))
            else:
                db.execute('DELETE FROM favorites WHERE path=?', (key,))

    def touch(self, paths):
        # First path in a single action wins; one action cannot create duplicates.
        keys = list(dict.fromkeys(self.key(path) for path in paths))[:5]
        if not keys:
            return
        with self._write() as db:
            old = [row[0] for row in db.execute('SELECT path FROM recents ORDER BY position DESC')]
            updated = (keys + [key for key in old if key not in keys])[:5]
            if updated != old:
                db.execute('DELETE FROM recents')
                db.executemany('INSERT INTO recents VALUES (?, ?)',
                               [(key, len(updated) - index) for index, key in enumerate(updated)])
