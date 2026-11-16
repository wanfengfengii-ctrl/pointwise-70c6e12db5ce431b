"""Atomic v1 (periodic) -> v2 (SDK2 planar) archive migration.

Commit boundary
---------------
The whole upgrade runs in one SQLite transaction. All SDK2 target tables,
tracks, pieces, receipts and the meta switch are prepared first; the
schema_version=2 switch happens before the user checkpoint; only afterwards is
the transaction committed. Any exception (including a failing checkpoint) rolls
back and leaves the v1 database byte-for-byte intact, so reopening and
retrying is safe. A process killed before commit likewise leaves the old
database untouched because SQLite discards the uncommitted journal/WAL on the
next open. An already upgraded database is a no-op, so repeated upgrades have
no side effects.

The maintenance window assumes a single worker with no concurrent writers.
"""
import json
import sqlite3

from covering import pieces
from vendor import plane2

META_SQL = "SELECT value FROM meta WHERE key='schema_version'"


def _connect(path):
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def upgrade(path, checkpoint=None):
    conn = _connect(path)
    try:
        upgrade_connection(conn, checkpoint)
    finally:
        conn.close()
    return None


def upgrade_connection(conn, checkpoint=None):
    """Same atomic upgrade against an already-open connection (used by tests)."""
    row = conn.execute(META_SQL).fetchone()
    if row is None:
        raise ValueError("not an initialized archive database")
    if row[0] == 2:
        # Idempotent re-entry: target storage already owns the archive.
        return None
    if row[0] != 1:
        raise ValueError("unsupported schema_version")
    conn.execute("BEGIN IMMEDIATE")
    try:
        plane2.install(conn)
        track_rows = conn.execute(
            "SELECT track_id,points_json FROM tracks_v1").fetchall()
        for track_id, points_json in track_rows:
            original = json.loads(points_json)
            # plane2.replace validates and owns piece/RTree maintenance.
            plane2.replace(conn, track_id, original, pieces(original))
        # Every request binding and its original receipt text is carried over
        # verbatim; historical requests never become current tracks.
        conn.execute(
            "INSERT INTO sdk2_receipts(request_id,payload,receipt) "
            "SELECT request_id,payload,receipt FROM receipts_v1")
        # Atomic visibility marker: switch only after all target data is ready.
        conn.execute("UPDATE meta SET value=2 WHERE key='schema_version'")
        if checkpoint is not None:
            checkpoint("before_commit")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return None
