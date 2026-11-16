import json
import sqlite3
import unittest
from archive import Store
from fixtures import seed
from model import D
from vendor import plane2

def seeded():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    seed(conn)
    return Store(conn)

class LegacyBehavior(unittest.TestCase):
    def setUp(self):
        self.store = seeded()
    def tearDown(self):
        self.store.close()
    def test_queries(self):
        cases = [
            ((179500000,400000,-179500000,600000), ["clone","cross","edge"]),
            ((500000,500000,500000,500000), ["ordinary"]),
            ((-D,-90000000,D,90000000), ["bent","clone","cross","edge","ordinary","point","replace","tie"]),
            ((-D,500000,-D,500000), ["clone","cross","edge"]),
            ((D,500000,D,500000), ["clone","cross","edge"]),
            ((0,10000000,0,10000000), ["tie"]),
            ((D,10000000,D,10000000), []),
            ((-D,-7000000,-D,-7000000), ["point"]),
            ((D,20500000,D,21500000), ["bent"]),
        ]
        for rect, expected in cases:
            self.assertEqual(self.store.search(*rect), expected, rect)
    def test_requests_and_replacement(self):
        s = self.store
        original = [[179000000,40000000],[-179000000,40000000]]
        self.assertEqual(s.put("r7", "replace", original), {"request_id":"r7","revision":7,"track_id":"replace"})
        self.assertEqual(s.get("replace"), [[0,40000000],[1000000,40000000]])
        with self.assertRaises(ValueError):
            s.put("r7", "replace", [[0,0],[1,1]])
        self.assertEqual(s.put("r10","cross",[[0,30000000],[1,30000000]])["revision"],10)
        self.assertEqual(s.search(179500000,400000,-179500000,600000), ["clone","edge"])
        self.assertEqual(s.get("absent"), None)
    def test_validation_atomic(self):
        s = self.store
        before = s.get("cross")
        with self.assertRaises(ValueError):
            s.put("bad","cross",[[True,0],[1,1]])
        self.assertEqual(s.get("cross"), before)
        with self.assertRaises(ValueError):
            s.search(0,1,0,0)

class PlanarSDK(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(":memory:", isolation_level=None)
        self.c.execute("PRAGMA foreign_keys=ON")
        self.c.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value INTEGER NOT NULL)")
        self.c.executemany("INSERT INTO meta VALUES(?,?)",[("schema_version",2),("generation",0)])
        plane2.install(self.c)
    def tearDown(self):
        self.c.close()
    def test_native_index_and_rational(self):
        # Plain planar probes only: no periodic transformation.
        p = [["1/3","2/3"],["5/3","4/3"]]
        raw = [[0,0],[1,1]]
        receipt = plane2.native_put(self.c,"p1","a",raw,[p])
        self.assertEqual(receipt["revision"],1)
        rows = list(plane2.candidates(self.c,"1/3","2/3","1/3","2/3"))
        self.assertEqual([r[0] for r in rows],["a"])
        self.assertTrue(plane2.intersects(rows[0][1],("1/3","2/3","1/3","2/3")))
        self.assertFalse(plane2.intersects(p,(0,0,0,0)))
        self.assertEqual(plane2.native_put(self.c,"p1","a",raw,[]),receipt)
        plane2.native_put(self.c,"p2","a",raw,[[[100,0],[200,0]]])
        self.assertEqual(list(plane2.candidates(self.c,0,0,2,2)),[])
        self.assertEqual(plane2.get(self.c,"a"),raw)
        plan = self.c.execute("EXPLAIN QUERY PLAN SELECT piece_id FROM sdk2_box WHERE minx<=1 AND maxx>=0").fetchall()
        self.assertTrue(any("VIRTUAL TABLE INDEX" in str(row) for row in plan))
    def test_degenerate_and_failure(self):
        self.assertTrue(plane2.intersects([["1/3",0],["1/3",0]],("1/3",0,"1/3",0)))
        with self.assertRaises(ValueError):
            plane2.native_put(self.c,"bad","x",[[0,0],[1,1]],[[[0,0],[600000000,0]]])
        self.assertIsNone(plane2.get(self.c,"x"))
        self.assertEqual(self.c.execute("SELECT value FROM meta WHERE key='generation'").fetchone()[0],0)

def demo():
    s = seeded()
    try:
        print(json.dumps({
            "crossing":s.search(179500000,400000,-179500000,600000),
            "central":s.search(500000,500000,500000,500000),
            "original":s.get("cross"),
            "old_replay":s.put("r7","replace",[[179000000,40000000],[-179000000,40000000]]),
            "current_replacement":s.get("replace")
        },ensure_ascii=False,sort_keys=True))
    finally:
        s.close()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        demo()
    else:
        unittest.main()
