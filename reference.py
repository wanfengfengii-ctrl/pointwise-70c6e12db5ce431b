"""Independent periodic-longitude intersection reference.

This judge is written from the contract geometry, not from either SDK and not
from covering.py: it never imports vendor.periodic1, vendor.plane2 or the
covering conversion. It reasons directly on the longitude circle with exact
Fraction algebra, so it also accepts non-integer (rational) window boundaries.

Method per adjacent segment:
  * fold the raw longitude step to the shortest signed arc; an exact +/-period
    tie keeps the sign of the raw difference (contract tie rule);
  * -180/+180 are one meridian, so a folded zero step is a degenerate segment;
  * collect every segment parameter t in [0,1] that can produce a boundary
    contact (endpoints, latitude edges s/n, the two boundary meridians) and
    test the interpolated point against the closed latitude band and the
    circular longitude arc of the window.

It only shares the model.D constant with the rest of the project.
"""
from fractions import Fraction

from model import D

PERIOD = 2 * D


def _fraction(value):
    return value if isinstance(value, Fraction) else Fraction(value)


def ref_intersects(points, rect):
    w, s, e, n = (_fraction(v) for v in rect)
    full = w == -D and e == D
    width = (e - w) % PERIOD
    pts = [(_fraction(x), _fraction(y)) for x, y in points]

    def longitude_inside(x):
        return full or (x - w) % PERIOD <= width

    def latitude_inside(y):
        return s <= y <= n

    def point_inside(p):
        return latitude_inside(p[1]) and longitude_inside(p[0])

    for (x, y), (xx, yy) in zip(pts, pts[1:]):
        if point_inside((x, y)) or point_inside((xx, yy)):
            return True
        dx = xx - x
        if dx > D:
            dx -= PERIOD
        elif dx < -D:
            dx += PERIOD
        dy = yy - y
        candidates = {Fraction(0), Fraction(1)}
        if dy:
            for latitude in (s, n):
                candidates.add((latitude - y) / dy)
        if dx:
            for meridian in (w, e):
                if dx > 0:
                    distance = (meridian - x) % PERIOD
                else:
                    distance = -((x - meridian) % PERIOD)
                candidates.add(distance / dx)
        for t in candidates:
            if 0 <= t <= 1:
                px, py = x + dx * t, y + dy * t
                if latitude_inside(py) and longitude_inside(px):
                    return True
    return False
