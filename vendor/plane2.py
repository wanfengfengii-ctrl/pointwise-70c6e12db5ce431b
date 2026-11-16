"""SDK2: exact rational planar segments with an SQLite RTree candidate index.
No periodic coordinate conversion or migration is implemented here.
"""
import json
from fractions import Fraction
from model import name, points, payload, dump, transaction, D, Y

CALLS = []
DDL = (
    "CREATE TABLE sdk2_tracks(track_id TEXT PRIMARY KEY,original_json TEXT NOT NULL)",
    "CREATE TABLE sdk2_receipts(request_id TEXT PRIMARY KEY,payload TEXT NOT NULL,receipt TEXT NOT NULL)",
    "CREATE TABLE sdk2_piece(piece_id INTEGER PRIMARY KEY,track_id TEXT NOT NULL REFERENCES sdk2_tracks(track_id),coords TEXT NOT NULL)",
    "CREATE INDEX sdk2_piece_owner ON sdk2_piece(track_id)",
    "CREATE VIRTUAL TABLE sdk2_box USING rtree(piece_id,minx,maxx,miny,maxy)",
)

def install(conn):
    for sql in DDL:
        conn.execute(sql)

def number(value):
    if type(value) is bool or not isinstance(value, (int, str, Fraction)):
        raise ValueError("integer, fraction text or Fraction required")
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError("bad rational") from exc

def segment(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("segment needs two endpoints")
    out = []
    for p in value:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise ValueError("coordinate pair required")
        x, y = map(number, p)
        if not -3*D <= x <= 3*D or not -Y <= y <= Y:
            raise ValueError("planar coordinate out of bounds")
        out.append((x, y))
    return tuple(out)

def get(conn, track_id):
    CALLS.append("get")
    row = conn.execute("SELECT original_json FROM sdk2_tracks WHERE track_id=?", (name(track_id),)).fetchone()
    return None if row is None else json.loads(row[0])

def replace(conn, track_id, original, pieces):
    """Caller owns transaction. Replaces every old piece belonging to track_id."""
    CALLS.append("replace")
    name(track_id)
    ps = points(original)
    ss = [segment(p) for p in pieces]
    if not ss:
        raise ValueError("at least one planar segment required")
    old = [r[0] for r in conn.execute("SELECT piece_id FROM sdk2_piece WHERE track_id=?", (track_id,))]
    conn.executemany("DELETE FROM sdk2_box WHERE piece_id=?", [(i,) for i in old])
    conn.execute("DELETE FROM sdk2_piece WHERE track_id=?", (track_id,))
    conn.execute("INSERT OR REPLACE INTO sdk2_tracks VALUES(?,?)", (track_id, dump(ps)))
    for (x, y), (xx, yy) in ss:
        raw = dump([[str(x), str(y)], [str(xx), str(yy)]])
        cur = conn.execute("INSERT INTO sdk2_piece(track_id,coords) VALUES(?,?)", (track_id, raw))
        conn.execute("INSERT INTO sdk2_box VALUES(?,?,?,?,?)",
                     (cur.lastrowid, float(min(x, xx)), float(max(x, xx)),
                      float(min(y, yy)), float(max(y, yy))))

def native_put(conn, request_id, track_id, original, pieces):
    """Native API: caller supplies planar representation; payload identity uses originals."""
    CALLS.append("native_put")
    name(request_id)
    body = payload(track_id, original)
    with transaction(conn):
        if conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] != 2:
            raise ValueError("SDK2 requires schema 2")
        old = conn.execute("SELECT payload,receipt FROM sdk2_receipts WHERE request_id=?", (request_id,)).fetchone()
        if old:
            if old[0] != body:
                raise ValueError("request content conflict")
            return json.loads(old[1])
        replace(conn, track_id, original, pieces)
        gen = conn.execute("SELECT value FROM meta WHERE key='generation'").fetchone()[0] + 1
        receipt = {"request_id": request_id, "track_id": track_id, "revision": gen}
        conn.execute("INSERT INTO sdk2_receipts VALUES(?,?,?)", (request_id, body, dump(receipt)))
        conn.execute("UPDATE meta SET value=? WHERE key='generation'", (gen,))
        return receipt

def candidates(conn, west, south, east, north):
    """Closed planar box. Always uses sdk2_box, then returns exact coordinates."""
    CALLS.append("candidates")
    w, s, e, n = map(number, (west, south, east, north))
    if w > e or s > n:
        raise ValueError("unordered planar box")
    for tid, raw in conn.execute(
        "SELECT p.track_id,p.coords FROM sdk2_box b JOIN sdk2_piece p USING(piece_id) "
        "WHERE b.minx<=? AND b.maxx>=? AND b.miny<=? AND b.maxy>=?",
        (float(e), float(w), float(n), float(s))):
        yield tid, segment(json.loads(raw))

def intersects(piece, rect):
    CALLS.append("intersects")
    a, b = segment(piece)
    w, s, e, n = map(number, rect)
    if w > e or s > n:
        raise ValueError("unordered planar box")
    def inside(p):
        return w <= p[0] <= e and s <= p[1] <= n
    def cross(p, q, r):
        return (q[0]-p[0])*(r[1]-p[1]) - (q[1]-p[1])*(r[0]-p[0])
    def on(p, q, r):
        return cross(p,q,r) == 0 and min(p[0],q[0]) <= r[0] <= max(p[0],q[0]) and min(p[1],q[1]) <= r[1] <= max(p[1],q[1])
    def touch(c, d):
        u, v, z, t = cross(a,b,c), cross(a,b,d), cross(c,d,a), cross(c,d,b)
        return (u*v < 0 and z*t < 0) or on(a,b,c) or on(a,b,d) or on(c,d,a) or on(c,d,b)
    corners = [(w,s), (e,s), (e,n), (w,n)]
    return inside(a) or inside(b) or any(touch(corners[i], corners[(i+1)%4]) for i in range(4))
