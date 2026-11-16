"""Business component: region candidates, exact query and track identity projection."""
import json
from model import window
from vendor import periodic1

class Region:
    def __init__(self, conn):
        self.conn = conn

    def replace(self, track_id, ps):
        ys = [p[1] for p in ps]
        self.conn.execute(
            "INSERT OR REPLACE INTO region_v1 VALUES(?,?,?)",
            (track_id, min(ys), max(ys)))

    def search(self, west, south, east, north):
        rect = window(west, south, east, north)
        rows = self.conn.execute(
            "SELECT t.track_id,t.points_json FROM region_v1 r "
            "JOIN tracks_v1 t ON t.track_id=r.track_id "
            "WHERE r.south<=? AND r.north>=?", (north, south))
        return sorted(tid for tid, raw in rows if periodic1.intersects(json.loads(raw), rect))
