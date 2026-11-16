import json
from contextlib import contextmanager

D = 180000000
Y = 90000000

def name(value):
    if not isinstance(value, str) or not value:
        raise ValueError("nonempty identifier required")
    return value

def points(value):
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise ValueError("at least two points required")
    result = []
    for p in value:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise ValueError("coordinate pair required")
        x, y = p
        if type(x) is not int or type(y) is not int or not -D <= x <= D or not -Y <= y <= Y:
            raise ValueError("integer coordinate out of bounds")
        result.append([x, y])
    return result

def window(w, s, e, n):
    if any(type(v) is not int for v in (w, s, e, n)):
        raise ValueError("integer window required")
    if not (-D <= w <= D and -D <= e <= D and -Y <= s <= n <= Y):
        raise ValueError("window out of bounds")
    return w, s, e, n

def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

def payload(track_id, ps):
    return dump([name(track_id), points(ps)])

@contextmanager
def transaction(conn):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
