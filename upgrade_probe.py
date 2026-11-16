"""Public acceptance probe for the future migration, not a migration implementation."""
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from archive import Store
from fixtures import create
from vendor import periodic1, plane2
import checks

def sql_image(path):
    c = sqlite3.connect(path)
    try:
        return list(c.iterdump())
    finally:
        c.close()

def audit_rows(c):
    return {t:list(c.execute("SELECT * FROM "+t+" ORDER BY 1"))
            for t in ("tracks_v1","region_v1","receipts_v1")}

def run(demo=False):
    from migration import upgrade
    # Preserve every legacy/SDK regression and add the delivery's boundary
    # suite (independent periodic reference, index path, migration edges).
    import boundary_tests
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromModule(checks),
        unittest.defaultTestLoader.loadTestsFromModule(boundary_tests),
    ])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    assert result.wasSuccessful()
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp)/"archive.db")
        create(path)
        before = sql_image(path)
        def broken(phase):
            assert phase == "before_commit"
            raise RuntimeError("injected before commit")
        try:
            upgrade(path, checkpoint=broken)
        except RuntimeError as exc:
            assert str(exc) == "injected before commit"
        else:
            raise AssertionError("checkpoint exception was swallowed")
        assert sql_image(path) == before
        child = subprocess.run([sys.executable,"-B",__file__,"kill",path],capture_output=True)
        assert child.returncode == -signal.SIGKILL, (child.returncode,child.stderr.decode())
        assert sql_image(path) == before

        s = Store(path)  # This same already-open object must observe the switch.
        originals = dict(s.conn.execute("SELECT track_id,points_json FROM tracks_v1"))
        audit = audit_rows(s.conn)
        windows = [
            (179500000,400000,-179500000,600000),
            (500000,500000,500000,500000),
            (-180000000,-90000000,180000000,90000000),
            (-180000000,500000,-180000000,500000),
            (180000000,500000,180000000,500000),
            (0,10000000,0,10000000),
            (180000000,10000000,180000000,10000000),
            (180000000,20500000,180000000,21500000),
            (180000000,-7000000,-180000000,-7000000),
        ]
        expected = [s.search(*w) for w in windows]
        upgrade(path)
        assert s.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == 2
        switched = sql_image(path)
        upgrade(path)
        assert sql_image(path) == switched
        assert audit_rows(s.conn) == audit
        assert list(s.conn.execute("SELECT * FROM sdk2_receipts ORDER BY 1")) == audit["receipts_v1"]

        old_intersects = periodic1.intersects
        def forbidden(*args,**kwargs):
            raise AssertionError("SDK1 used after switch")
        periodic1.intersects = forbidden
        try:
            for tid, raw in originals.items():
                assert s.get(tid) == json.loads(raw)
            assert [s.search(*w) for w in windows] == expected
            assert s.put("r7","replace",[[179000000,40000000],[-179000000,40000000]])["revision"] == 7
            assert s.get("replace") == [[0,40000000],[1000000,40000000]]
            s.put("r10","cross",[[0,30000000],[1000000,30000000]])
            assert s.search(*windows[0]) == ["clone","edge"]
            ordinary = [[30000000,-20000000],[31000000,-19000000]]
            receipt = plane2.native_put(s.conn,"native1","native",ordinary,[ordinary])
            assert receipt["revision"] == 11
            assert s.get("native") == ordinary
            assert s.search(30500000,-19500000,30500000,-19500000) == ["native"]
            assert audit_rows(s.conn) == audit
            plan = s.conn.execute("EXPLAIN QUERY PLAN SELECT piece_id FROM sdk2_box WHERE minx<=1 AND maxx>=0").fetchall()
            assert any("VIRTUAL TABLE INDEX" in str(r) for r in plan)
            assert s.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            if demo:
                print(json.dumps({"schema":2,"crossing_before":expected[0],
                    "crossing_after_replacement":s.search(*windows[0]),
                    "native":s.get("native"),"native_receipt":receipt,
                    "audit_tracks":len(audit["tracks_v1"])},sort_keys=True))
        finally:
            periodic1.intersects = old_intersects
            s.close()
    print("MIGRATION_PROBE_OK")

if __name__ == "__main__":
    if len(sys.argv)>1 and sys.argv[1] == "kill":
        from migration import upgrade
        def kill(phase):
            if phase != "before_commit":
                raise AssertionError(phase)
            os.kill(os.getpid(),signal.SIGKILL)
        upgrade(sys.argv[2],checkpoint=kill)
        raise AssertionError("missing before_commit checkpoint")
    run(demo=len(sys.argv)>1 and sys.argv[1] == "demo")
