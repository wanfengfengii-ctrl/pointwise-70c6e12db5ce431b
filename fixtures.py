"""Frozen v1 fixture builder. Does not call current Store or SDK code."""
import sqlite3

SQL = """
CREATE TABLE meta(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
INSERT INTO meta VALUES('schema_version',1),('generation',9);
CREATE TABLE tracks_v1(track_id TEXT PRIMARY KEY,points_json TEXT NOT NULL);
CREATE TABLE region_v1(track_id TEXT PRIMARY KEY,south INTEGER NOT NULL,north INTEGER NOT NULL);
CREATE INDEX region_v1_south ON region_v1(south);
CREATE TABLE receipts_v1(request_id TEXT PRIMARY KEY,payload TEXT NOT NULL,receipt TEXT NOT NULL);
INSERT INTO tracks_v1 VALUES
('ordinary','[[0,0],[2000000,2000000]]'),
('cross','[[179000000,0],[-179000000,1000000]]'),
('clone','[[179000000,0],[-179000000,1000000]]'),
('tie','[[90000000,10000000],[-90000000,10000000]]'),
('edge','[[180000000,-5000000],[180000000,5000000]]'),
('bent','[[178000000,20000000],[-178000000,21000000],[178000000,22000000]]'),
('replace','[[0,40000000],[1000000,40000000]]'),
('point','[[-180000000,-7000000],[180000000,-7000000]]');
INSERT INTO region_v1 VALUES
('ordinary',0,2000000),('cross',0,1000000),('clone',0,1000000),
('tie',10000000,10000000),('edge',-5000000,5000000),
('bent',20000000,22000000),('replace',40000000,40000000),('point',-7000000,-7000000);
INSERT INTO receipts_v1 VALUES
('r1','["ordinary",[[0,0],[2000000,2000000]]]','{"request_id":"r1","revision":1,"track_id":"ordinary"}'),
('r2','["cross",[[179000000,0],[-179000000,1000000]]]','{"request_id":"r2","revision":2,"track_id":"cross"}'),
('r3','["clone",[[179000000,0],[-179000000,1000000]]]','{"request_id":"r3","revision":3,"track_id":"clone"}'),
('r4','["tie",[[90000000,10000000],[-90000000,10000000]]]','{"request_id":"r4","revision":4,"track_id":"tie"}'),
('r5','["edge",[[180000000,-5000000],[180000000,5000000]]]','{"request_id":"r5","revision":5,"track_id":"edge"}'),
('r6','["bent",[[178000000,20000000],[-178000000,21000000],[178000000,22000000]]]','{"request_id":"r6","revision":6,"track_id":"bent"}'),
('r7','["replace",[[179000000,40000000],[-179000000,40000000]]]','{"request_id":"r7","revision":7,"track_id":"replace"}'),
('r8','["replace",[[0,40000000],[1000000,40000000]]]','{"request_id":"r8","revision":8,"track_id":"replace"}'),
('r9','["point",[[-180000000,-7000000],[180000000,-7000000]]]','{"request_id":"r9","revision":9,"track_id":"point"}');
"""

def seed(conn):
    conn.executescript(SQL)

def create(path):
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        seed(conn)
    finally:
        conn.close()

if __name__ == "__main__":
    import sys
    create(sys.argv[1])
