"""Business component: region candidates, exact query and track identity.

v1 keeps the original latitude envelope + SDK1 periodic evaluation.
After the SDK2 switch the region index is the plane2 RTree: periodic windows
are translated to planar boxes via covering.query_boxes, candidates come only
from plane2.candidates and exact filtering uses plane2.intersects. SDK1 is never
imported on the v2 path.
"""
import json

from model import window
from covering import query_boxes, pieces
from vendor import plane2
from vendor import periodic1


class Region:
    def __init__(self, conn):
        self.conn = conn

    def _schema(self):
        return self.conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]

    def replace(self, track_id, ps):
        if self._schema() == 2:
            # Compatibility writes maintain target storage only; plane2.replace
            # clears the old pieces and their RTree rows inside the caller txn.
            plane2.replace(self.conn, track_id, ps, pieces(ps))
            return
        ys = [p[1] for p in ps]
        self.conn.execute(
            "INSERT OR REPLACE INTO region_v1 VALUES(?,?,?)",
            (track_id, min(ys), max(ys)))

    def search(self, west, south, east, north):
        rect = window(west, south, east, north)
        if self._schema() == 2:
            return self._search_v2(rect)
        rows = self.conn.execute(
            "SELECT t.track_id,t.points_json FROM region_v1 r "
            "JOIN tracks_v1 t ON t.track_id=r.track_id "
            "WHERE r.south<=? AND r.north>=?", (north, south))
        return sorted(tid for tid, raw in rows if periodic1.intersects(json.loads(raw), rect))

    def _search_v2(self, rect):
        w, s, e, n = rect
        hits = set()
        for box in query_boxes(w, s, e, n):
            for track_id, piece in plane2.candidates(self.conn, *box):
                # Exact planar intersection; the RTree is only a conservative
                # candidate source and may report envelope false positives.
                if plane2.intersects(piece, box):
                    hits.add(track_id)
        return sorted(hits)
