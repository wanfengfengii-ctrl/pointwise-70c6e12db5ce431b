"""Business component: original trajectories, replacement and request receipts.

The same Store serves both schemas. On schema v1 the original tables and SDK1
region evaluation are used unchanged. After the migration switch (schema v2)
all coordinates, pieces, receipts and the generation counter live in the SDK2
target tables; old v1 tables remain on disk for audit only and are never read
or written by business operations.
"""
import json
import sqlite3
from model import name, points, payload, dump, transaction
from region import Region
from covering import pieces
from vendor import plane2

DDL = (
    "CREATE TABLE meta(key TEXT PRIMARY KEY,value INTEGER NOT NULL)",
    "CREATE TABLE tracks_v1(track_id TEXT PRIMARY KEY,points_json TEXT NOT NULL)",
    "CREATE TABLE region_v1(track_id TEXT PRIMARY KEY,south INTEGER NOT NULL,north INTEGER NOT NULL)",
    "CREATE INDEX region_v1_south ON region_v1(south)",
    "CREATE TABLE receipts_v1(request_id TEXT PRIMARY KEY,payload TEXT NOT NULL,receipt TEXT NOT NULL)",
)

def initialize(conn):
    for sql in DDL:
        conn.execute(sql)
    conn.executemany("INSERT INTO meta VALUES(?,?)", [("schema_version", 1), ("generation", 0)])

class Store:
    def __init__(self, path):
        self.conn = path if isinstance(path, sqlite3.Connection) else sqlite3.connect(path, isolation_level=None)
        self.conn.execute("PRAGMA foreign_keys=ON")
        if not self.conn.execute("SELECT 1 FROM sqlite_master WHERE name='meta'").fetchone():
            with transaction(self.conn):
                initialize(self.conn)
        self.region = Region(self.conn)

    def _schema(self):
        return self.conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]

    def put(self, request_id, track_id, ps):
        name(request_id)
        ps = points(ps)
        body = payload(track_id, ps)
        with transaction(self.conn):
            schema = self._schema()
            if schema == 2:
                return self._put_v2(request_id, track_id, ps, body)
            if schema != 1:
                raise ValueError("unsupported schema")
            old = self.conn.execute("SELECT payload,receipt FROM receipts_v1 WHERE request_id=?", (request_id,)).fetchone()
            if old:
                if old[0] != body:
                    raise ValueError("request content conflict")
                return json.loads(old[1])
            generation = self.conn.execute("SELECT value FROM meta WHERE key='generation'").fetchone()[0] + 1
            receipt = {"request_id": request_id, "track_id": track_id, "revision": generation}
            self.conn.execute("INSERT OR REPLACE INTO tracks_v1 VALUES(?,?)", (track_id, dump(ps)))
            self.region.replace(track_id, ps)
            self.conn.execute("INSERT INTO receipts_v1 VALUES(?,?,?)", (request_id, body, dump(receipt)))
            self.conn.execute("UPDATE meta SET value=? WHERE key='generation'", (generation,))
            return receipt

    def _put_v2(self, request_id, track_id, ps, body):
        # Target receipts are the request ledger; replay is keyed on originals.
        old = self.conn.execute(
            "SELECT payload,receipt FROM sdk2_receipts WHERE request_id=?",
            (request_id,)).fetchone()
        if old:
            if old[0] != body:
                raise ValueError("request content conflict")
            # A replayed request never restores a track that a later request
            # replaced: return the original receipt without touching geometry.
            return json.loads(old[1])
        generation = self.conn.execute(
            "SELECT value FROM meta WHERE key='generation'").fetchone()[0] + 1
        receipt = {"request_id": request_id, "track_id": track_id, "revision": generation}
        # plane2.replace atomically swaps the original text, all owned pieces and
        # their RTree rows inside this same caller transaction.
        plane2.replace(self.conn, track_id, ps, pieces(ps))
        self.conn.execute(
            "INSERT INTO sdk2_receipts VALUES(?,?,?)", (request_id, body, dump(receipt)))
        self.conn.execute("UPDATE meta SET value=? WHERE key='generation'", (generation,))
        return receipt

    def get(self, track_id):
        name(track_id)
        if self._schema() == 2:
            # Fresh parsed copy: callers cannot mutate stored coordinates.
            return plane2.get(self.conn, track_id)
        row = self.conn.execute("SELECT points_json FROM tracks_v1 WHERE track_id=?", (track_id,)).fetchone()
        return None if row is None else json.loads(row[0])

    def search(self, west, south, east, north):
        return self.region.search(west, south, east, north)

    def close(self):
        self.conn.close()
