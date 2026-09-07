"""App-local creative annotations. Never rewrite media or create sidecars."""
from pathlib import Path
import sqlite3
from contextlib import closing, contextmanager

COLORS = ('red', 'orange', 'green', 'blue', 'purple')
EMPTY = (0, '', False)


class RatingStore:
    def __init__(self, database=None):
        self.database = database or Path.home() / '.local/share/omarchy-file-picker/ratings.sqlite3'
        self.cache = {}

    @staticmethod
    def key(path):
        return str(Path(path).absolute())

    def refresh(self, paths):
        self.cache = {}
        if not self.database.exists():
            return
        keys = list(dict.fromkeys(self.key(path) for path in paths))
        with closing(sqlite3.connect(self.database, timeout=2)) as db:
            for start in range(0, len(keys), 400):
                batch = keys[start:start + 400]
                rows = db.execute('SELECT path, stars, color, rejected FROM ratings WHERE path IN (' +
                                  ','.join('?' for _ in batch) + ')', batch)
                self.cache.update((p, (s, c, bool(r))) for p, s, c, r in rows)

    def get(self, path):
        return self.cache.get(self.key(path), EMPTY)

    @contextmanager
    def _connect(self):
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.database.touch(mode=0o600, exist_ok=True)
        db = sqlite3.connect(self.database, timeout=2)
        try:
            with db:
                # Reserve the writer before reading existing fields, so another
                # picker window cannot merge its edit against the same old row.
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS ratings '
                           '(path TEXT PRIMARY KEY, stars INTEGER NOT NULL DEFAULT 0, '
                           'color TEXT NOT NULL DEFAULT "", rejected INTEGER NOT NULL DEFAULT 0)')
                yield db
        finally:
            db.close()

    def set_many(self, paths, *, stars=None, color=None, rejected=None):
        if stars is not None and (type(stars) is not int or not 0 <= stars <= 5):
            raise ValueError('Rating must be from zero to five stars.')
        if color is not None and color not in ('', *COLORS):
            raise ValueError('Unknown color label.')
        if rejected is not None and type(rejected) is not bool:
            raise ValueError('Rejected must be true or false.')
        changes = {}
        with self._connect() as db:
            for path in paths:
                key = self.key(path)
                old = db.execute('SELECT stars, color, rejected FROM ratings WHERE path=?', (key,)).fetchone() or EMPTY
                value = (old[0] if stars is None else stars, old[1] if color is None else color,
                         bool(old[2]) if rejected is None else rejected)
                db.execute('INSERT INTO ratings VALUES (?, ?, ?, ?) ON CONFLICT(path) DO UPDATE SET '
                           'stars=excluded.stars, color=excluded.color, rejected=excluded.rejected', (key, *value))
                changes[key] = value
        self.cache.update(changes)

    def move(self, mapping):
        if not mapping or not self.database.exists():
            return
        changes = {}
        removed = set()
        with self._connect() as db:
            expanded = {self.key(a): self.key(b) for a, b in mapping.items() if a != b}
            roots = sorted(expanded.items(), key=lambda pair: len(pair[0]), reverse=True)
            # Directory renames carry annotations for their descendants too.
            for (path,) in db.execute('SELECT path FROM ratings'):
                if path in expanded:
                    continue
                for source, target in roots:
                    if path.startswith(source + '/'):
                        expanded[path] = target + path[len(source):]
                        break
            records = [(a, b, db.execute('SELECT stars,color,rejected FROM ratings WHERE path=?', (a,)).fetchone())
                       for a, b in expanded.items()]
            for source, _, _ in records:
                db.execute('DELETE FROM ratings WHERE path=?', (source,))
                removed.add(source)
            for _, target, value in records:
                db.execute('DELETE FROM ratings WHERE path=?', (target,))
                removed.add(target)
                if value:
                    db.execute('INSERT INTO ratings VALUES (?, ?, ?, ?)', (target, *value))
                    changes[target] = (value[0], value[1], bool(value[2]))
        # An I/O, constraint or commit failure must leave the visible cache in
        # the same state as the rolled-back database.
        for path in removed:
            self.cache.pop(path, None)
        self.cache.update(changes)


def matches(value, mode='all', minimum=0, color=''):
    stars, label, rejected = value
    return ((mode != 'rated' or (stars > 0 and not rejected)) and
            (mode != 'rejected' or rejected) and stars >= minimum and
            (not color or color == label))
