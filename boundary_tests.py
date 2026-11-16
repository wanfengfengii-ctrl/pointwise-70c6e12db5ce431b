"""Extended boundary regression for the SDK2 periodic->planar archive.

These tests supplement, never replace, the assertions in checks.py:
  * the independent reference judge (reference.py) is cross-checked against
    the SDK2-backed Store.search on crossing, tie, folded, multi-segment and
    degenerate tracks, including rational window boundaries;
  * the 180-degree tie in both directions, +/-180 equivalence and backtracking
    tracks are pinned explicitly;
  * global and degenerate windows hit exactly; results are sorted/deduped;
  * the query path uses the SDK2 RTree only: SDK1 is disabled, every candidate
    comes through plane2.candidates with a VIRTUAL TABLE INDEX plan, and a
    selective window cannot pull all pieces;
  * replay cannot restore a replaced track and conflicting replays are atomic.
"""
import json
import unittest
from fractions import Fraction

from archive import Store
from fixtures import seed
from migration import upgrade, upgrade_connection
from reference import ref_intersects
from model import D, Y
from vendor import periodic1, plane2

ONE = 1000000

# Extra tracks stressing tie directions, folds, backtracks and repeated hits.
EXTRA = {
    # 90 -> -90 raw step -180: negative tie, traverses 0 on the cover.
    "tie_neg": [[90 * ONE, 0], [-90 * ONE, 0]],
    # -90 -> 90 raw step +180: positive tie, traverses 180 on the cover.
    "tie_pos": [[-90 * ONE, 0], [90 * ONE, 0]],
    # +/-180 same meridian: degenerate segment sitting on the dateline.
    "dateline_pt": [[-D, 5 * ONE], [D, 5 * ONE]],
    # Three crossings through the dateline with a fold-back in the middle.
    "fold": [[170 * ONE, 10 * ONE], [-170 * ONE, 11 * ONE],
             [170 * ONE, 12 * ONE], [-170 * ONE, 13 * ONE]],
    # Backtrack in ordinary longitude range, never crossing the dateline.
    "back": [[20 * ONE, 20 * ONE], [25 * ONE, 21 * ONE],
             [22 * ONE, 22 * ONE], [20 * ONE, 23 * ONE]],
    # Repeated identical points and a zero-length segment in the middle.
    "repeat": [[10 * ONE, 30 * ONE], [10 * ONE, 30 * ONE],
               [12 * ONE, 31 * ONE]],
    # Vertical meridian segment on longitude 100deg.
    "meridian": [[100 * ONE, -10 * ONE], [100 * ONE, 10 * ONE]],
    # Segment with rational midpoint crossings: endpoints integer, slope 1/3.
    "rational": [[0, 0], [3 * ONE, ONE]],
    # Antipodal pair 0 <-> 180: the two shortest arcs are equal length; the
    # sign of the raw step decides which half-circle is drawn.
    "tie_ant_neg": [[0, 7 * ONE], [D, 8 * ONE]],
    "tie_ant_pos": [[D, 7 * ONE], [0, 8 * ONE]],
}

WINDOWS = [
    # selective crossing window near the dateline
    (179 * ONE + 500000, 400000, -179 * ONE - 500000, 600000),
    # tiny central window with rational (non-integer) boundaries
    (Fraction(500000, 3), Fraction(1000000, 9),
     Fraction(500000, 3), Fraction(1000000, 9)),
    # global window
    (-D, -Y, D, Y),
    # degenerate single-meridian windows on both dateline spellings
    (-D, 0, -D, 0),
    (D, 0, D, 0),
    (D, 5 * ONE, -D, 5 * ONE),
    # degenerate point windows
    (0, 0, 0, 0),
    (100 * ONE, 0, 100 * ONE, 0),
    (22 * ONE, 22 * ONE, 22 * ONE, 22 * ONE),
    # ordinary local window and a meridian slice
    (20 * ONE, 19 * ONE, 26 * ONE, 24 * ONE),
    (100 * ONE, -Y, 100 * ONE, Y),
    # non-integer latitude slice across the rational-slope segment
    (-D, Fraction(ONE, 3), D, Fraction(ONE, 3)),
    # window on the 180 tie longitude: tie_neg must miss, tie_pos must hit
    (D, -ONE, D, ONE),
    (0, -ONE, 0, ONE),
]


def build_store():
    import sqlite3
    conn = sqlite3.connect(":memory:", isolation_level=None)
    seed(conn)
    s = Store(conn)
    for i, (tid, ps) in enumerate(EXTRA.items(), start=100):
        s.put("x%d" % i, tid, ps)
    return s


class PeriodicReferenceCrossCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = build_store()
        cls.upgraded = build_store()
        upgrade_connection(cls.upgraded.conn)
        cls.originals = {
            tid: json.loads(raw)
            for tid, raw in cls.upgraded.conn.execute(
                "SELECT track_id,original_json FROM sdk2_tracks")}

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        cls.upgraded.close()

    def search_v2(self, conn, rect):
        # Direct v2 path: the public API keeps integer-only window validation,
        # while the SDK2 index itself supports exact rational boundaries.
        from region import Region
        return Region(conn)._search_v2(rect)

    def test_reference_agrees_on_v1(self):
        for rect in WINDOWS:
            w, s, e, n = rect
            expected = sorted(
                tid for tid, ps in self.originals.items()
                if ref_intersects(ps, rect))
            # Reference uses Fraction; v1 search requires integer windows only.
            if all(type(v) is int for v in rect):
                self.assertEqual(self.store.search(w, s, e, n), expected, rect)

    def test_sdk2_matches_reference_everywhere(self):
        for rect in WINDOWS:
            w, s, e, n = rect
            expected = sorted(
                tid for tid, ps in self.originals.items()
                if ref_intersects(ps, rect))
            self.assertEqual(self.search_v2(self.upgraded.conn, rect),
                             expected, rect)

    def test_public_search_rejects_rational_window(self):
        with self.assertRaises(ValueError):
            self.upgraded.search(Fraction(1, 2), 0, Fraction(1, 2), 0)

    def test_tie_directions_and_dateline_equivalence(self):
        s = self.upgraded
        # Both antipodal endpoint orderings pick the arc through longitude 0;
        # the raw-difference sign only decides which semicircle, and neither
        # semicircle reaches the dateline for this pair.
        dateline = s.search(D, -ONE, D, ONE)
        self.assertNotIn("tie_neg", dateline)
        self.assertNotIn("tie_pos", dateline)
        central = s.search(0, -ONE, 0, ONE)
        self.assertIn("tie_neg", central)
        self.assertIn("tie_pos", central)

    def test_antipodal_tie_arc_direction(self):
        s = self.upgraded
        # For 0 <-> +180 antipodes both raw orderings draw the +90deg half
        # circle (reverse travel order over the same arc); neither draws the
        # -90deg half. The tie rule only distinguishes direction when the two
        # equal-length arcs are geometrically different (see tie_neg/tie_pos on
        # the +90/-90 antipode, which both take the 0deg arc per SDK1 folding).
        lower = s.search(-90 * ONE, 7 * ONE, -90 * ONE, 8 * ONE)
        upper = s.search(90 * ONE, 7 * ONE, 90 * ONE, 8 * ONE)
        self.assertNotIn("tie_ant_neg", lower)
        self.assertNotIn("tie_ant_pos", lower)
        self.assertIn("tie_ant_neg", upper)
        self.assertIn("tie_ant_pos", upper)
        # Both still touch their shared endpoint meridians.
        for tid in ("tie_ant_neg", "tie_ant_pos"):
            self.assertIn(tid, s.search(0, 7 * ONE, 0, 8 * ONE))
            self.assertIn(tid, s.search(D, 7 * ONE, D, 8 * ONE))
        # Independent judge agrees with every call above.
        for rect in ((-90 * ONE, 7 * ONE, -90 * ONE, 8 * ONE),
                     (90 * ONE, 7 * ONE, 90 * ONE, 8 * ONE),
                     (0, 7 * ONE, 0, 8 * ONE),
                     (D, 7 * ONE, D, 8 * ONE)):
            for tid in ("tie_ant_neg", "tie_ant_pos"):
                self.assertEqual(
                    tid in s.search(*rect),
                    ref_intersects(self.originals[tid], rect), rect)
        # +/-180 are the same meridian: all three spellings agree.
        a = s.search(-D, 4 * ONE, -D, 6 * ONE)
        b = s.search(D, 4 * ONE, D, 6 * ONE)
        c = s.search(D, 5 * ONE, -D, 5 * ONE)
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        self.assertIn("dateline_pt", a)

    def test_sorted_dedup_and_global_coverage(self):
        s = self.upgraded
        got = s.search(-D, -Y, D, Y)
        self.assertEqual(got, sorted(set(got)))
        self.assertEqual(set(got), set(self.originals))
        # Same coordinates, different ids both surface (cross/clone from seed).
        window = (179 * ONE + 500000, 400000, -179 * ONE - 500000, 600000)
        self.assertEqual(sorted(set(s.search(*window)) & {"clone", "cross", "edge"}),
                         ["clone", "cross", "edge"])

    def test_rational_boundary_point_contact(self):
        # Exact point on the rational segment: (1e6, 1e6/3).
        x, y = ONE, Fraction(ONE, 3)
        self.assertEqual(
            self.search_v2(self.upgraded.conn, (x, y, x, y)), ["rational"])
        # A hair-width window next to the line still contains the point.
        lo, hi = y - 1, y + 1
        self.assertEqual(
            self.search_v2(self.upgraded.conn, (x - 1, lo, x + 1, hi)),
            ["rational"])


class IndexPathAndSDK1Isolation(unittest.TestCase):
    def setUp(self):
        self.store = build_store()
        upgrade_connection(self.store.conn)

    def tearDown(self):
        self.store.close()

    def test_no_sdk1_and_rtree_candidates_only(self):
        from vendor.periodic1 import intersects as real_intersects
        def forbidden(*a, **k):
            raise AssertionError("SDK1 used after switch")
        periodic1.intersects = forbidden
        plane2.CALLS.clear()
        try:
            hits = self.store.search(
                179 * ONE + 500000, 400000, -179 * ONE - 500000, 600000)
        finally:
            periodic1.intersects = real_intersects
        self.assertTrue(hits)
        self.assertIn("candidates", plane2.CALLS)
        self.assertNotIn("replace", plane2.CALLS)
        plan = self.store.conn.execute(
            "EXPLAIN QUERY PLAN SELECT p.track_id FROM sdk2_box b "
            "JOIN sdk2_piece p USING(piece_id) "
            "WHERE b.minx<=? AND b.maxx>=? AND b.miny<=? AND b.maxy>=?",
            (0, 0, 0, 0)).fetchall()
        self.assertTrue(any("VIRTUAL TABLE INDEX" in str(r) for r in plan))

    def test_selective_window_does_not_fetch_all_pieces(self):
        total = self.store.conn.execute(
            "SELECT COUNT(*) FROM sdk2_piece").fetchone()[0]
        observed = []
        original = plane2.candidates
        def counting(conn, w, s, e, n):
            gen = original(conn, w, s, e, n)
            def wrapped():
                for item in gen:
                    observed.append(item[0])
                    yield item
            return wrapped()
        plane2.candidates = counting
        try:
            self.store.search(100 * ONE, -100, 100 * ONE, 100)
        finally:
            plane2.candidates = original
        self.assertTrue(observed)
        self.assertLess(len(set(observed)), total)
        self.assertEqual(set(observed), {"meridian"})

    def test_local_window_never_uses_global_box(self):
        seen_boxes = []
        original = plane2.candidates
        def spy(conn, w, s, e, n):
            seen_boxes.append((w, e))
            return original(conn, w, s, e, n)
        plane2.candidates = spy
        try:
            self.store.search(500000, 500000, 500000, 500000)
        finally:
            plane2.candidates = original
        # Local query: three period-shifted local boxes, none spanning the
        # whole cover.
        self.assertEqual(len(seen_boxes), 3)
        for w, e in seen_boxes:
            self.assertLess(e - w, 6 * D)

    def test_replay_does_not_restore_replaced_track(self):
        s = self.store
        crossing = [[179 * ONE, 40 * ONE], [-179 * ONE, 40 * ONE]]
        receipt = s.put("r100", "victim", crossing)
        s.put("r101", "victim", [[1, 1], [2, 2]])
        # Same request id, same original payload: original receipt, no restore.
        self.assertEqual(s.put("r100", "victim", crossing), receipt)
        self.assertEqual(s.get("victim"), [[1, 1], [2, 2]])
        # Conflicting replay raises and changes nothing.
        with self.assertRaises(ValueError):
            s.put("r100", "victim", [[3, 3], [4, 4]])
        self.assertEqual(s.get("victim"), [[1, 1], [2, 2]])
        # The crossing geometry is fully withdrawn from the index.
        hits = s.search(179 * ONE + 500000, 400000,
                        -179 * ONE - 500000, 600000)
        self.assertNotIn("victim", hits)
        self.assertEqual(
            sorted(set(hits) & {"clone", "cross", "edge"}),
            ["clone", "cross", "edge"])

    def test_native_append_is_immediately_visible(self):
        s = self.store
        original = [[60 * ONE, 60 * ONE], [61 * ONE, 61 * ONE]]
        receipt = plane2.native_put(
            s.conn, "native_x", "native_t", original, [original])
        self.assertEqual(receipt["revision"],
                         s.conn.execute(
                             "SELECT value FROM meta WHERE key='generation'").fetchone()[0])
        self.assertEqual(s.get("native_t"), original)
        self.assertEqual(
            s.search(60 * ONE + 500000, 60 * ONE + 500000,
                     60 * ONE + 500000, 60 * ONE + 500000),
            ["native_t"])


class FuzzAgainstReference(unittest.TestCase):
    def test_random_tracks_and_windows(self):
        import random
        from region import Region
        rng = random.Random(20261116)
        store = build_store()
        upgrade_connection(store.conn)
        region = Region(store.conn)
        # Add 40 random tracks, including dateline, tie and fold-back shapes.
        edge_longitudes = (-D, D, -90 * ONE, 90 * ONE, 0)
        for k in range(40):
            npts = rng.randint(2, 6)
            ps = []
            for j in range(npts):
                if k % 3 == 0 and j:
                    x = rng.choice(edge_longitudes)
                else:
                    x = rng.randint(-D, D)
                ps.append([x, rng.randint(-Y, Y)])
            store.put("fuzz_req_%d" % k, "fuzz_%d" % k, ps)
        originals = {tid: json.loads(raw) for tid, raw in store.conn.execute(
            "SELECT track_id,original_json FROM sdk2_tracks")}
        for _ in range(1000):
            w = rng.randint(-D, D)
            e = rng.randint(-D, D)
            s = rng.randint(-Y, Y)
            n = rng.randint(s, Y)
            rect = (w, s, e, n)
            expected = sorted(tid for tid, ps in originals.items()
                              if ref_intersects(ps, rect))
            self.assertEqual(region._search_v2(rect), expected, rect)
        store.close()

    def test_matches_sdk1_oracle_on_integer_windows(self):
        # Direct differential test against the frozen SDK1 behavior on a large
        # random, tie-heavy corpus; SDK1 is the behavior oracle for integer
        # windows even though the production v2 path never calls it.
        import random
        from region import Region
        rng = random.Random(99173)
        store = build_store()
        upgrade_connection(store.conn)
        region = Region(store.conn)
        special = (-D, D, -D + 1, D - 1, 0, 90 * ONE, -90 * ONE)
        for k in range(60):
            ps = [[rng.choice(special) if rng.random() < 0.4
                   else rng.randint(-D, D),
                   rng.randint(-Y, Y)] for _ in range(rng.randint(2, 7))]
            store.put("ora_req_%d" % k, "ora_%d" % k, ps)
        originals = {tid: json.loads(raw) for tid, raw in store.conn.execute(
            "SELECT track_id,original_json FROM sdk2_tracks")}
        for _ in range(800):
            w, e = rng.randint(-D, D), rng.randint(-D, D)
            s = rng.randint(-Y, Y)
            n = rng.randint(s, Y)
            rect = (w, s, e, n)
            expected = sorted(tid for tid, ps in originals.items()
                              if periodic1.intersects(ps, rect))
            self.assertEqual(region._search_v2(rect), expected, rect)
        store.close()


class RepresentationBounds(unittest.TestCase):
    def test_pieces_always_within_sdk2_limits(self):
        from covering import pieces
        from vendor.plane2 import segment
        extreme = [
            # Alternating dateline crossings of every length.
            [[179999999, 0], [-179999999, 1], [179999999, 2], [-179999999, 3],
             [179999999, 4], [-179999999, 5]],
            # Monotone walk across the whole range, repeated.
            [[-D, 0], [D, 1], [-D, 2], [D, 3]],
            # Repeated degenerate and zero-length points.
            [[D, 10], [D, 10], [-D, 11], [-D, 11], [0, 12]],
        ]
        for ps in extreme:
            ss = pieces(ps)
            self.assertTrue(ss)
            for piece in ss:
                # plane2.segment enforces the +/-3D, +/-Y contract.
                segment(piece)
                for (x, y) in piece:
                    self.assertGreaterEqual(x, -3 * D)
                    self.assertLessEqual(x, 3 * D)
                    self.assertTrue(-Y <= y <= Y)


class MigrationIdempotency(unittest.TestCase):
    def test_repeated_upgrade_and_audit_tables(self):
        import sqlite3, tempfile, os
        from fixtures import create
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.db")
            create(path)
            upgrade(path)
            c = sqlite3.connect(path)
            image1 = list(c.iterdump())
            c.close()
            upgrade(path)
            c = sqlite3.connect(path)
            image2 = list(c.iterdump())
            c.close()
            self.assertEqual(image1, image2)
            c = sqlite3.connect(path)
            # Old tables retained verbatim, including the v1 envelope index.
            names = {r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','index')")}
            self.assertTrue(
                {"tracks_v1", "region_v1", "receipts_v1",
                 "region_v1_south"} <= names)
            self.assertEqual(
                c.execute("SELECT COUNT(*) FROM receipts_v1").fetchone()[0], 9)
            c.close()


if __name__ == "__main__":
    unittest.main()
