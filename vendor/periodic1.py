"""SDK1: direct periodic edge-crossing evaluator; no planar storage API."""
from fractions import Fraction
from model import D

CALLS = []

def intersects(points, rect):
    CALLS.append("intersects")
    w, s, e, n = rect
    full = w == -D and e == D
    period = 2 * D
    width = (e-w) % period
    def longitude(x):
        return full or (x-w) % period <= width
    for (x, y), (xx, yy) in zip(points, points[1:]):
        if full:
            if min(y,yy) <= n and max(y,yy) >= s:
                return True
            continue
        if (s <= y <= n and longitude(x)) or (s <= yy <= n and longitude(xx)):
            return True
        dx, dy = xx-x, yy-y
        if dx > D:
            dx -= period
        elif dx < -D:
            dx += period
        # Cross latitude edges directly in the periodic coordinate system.
        if dy:
            for latitude in (s,n):
                t = Fraction(latitude-y,dy)
                if 0 <= t <= 1 and longitude(x+dx*t):
                    return True
        # Cross the two meridians in the direction of travel.
        if dx:
            for meridian in (w,e):
                distance = (meridian-x) % period if dx > 0 else -((x-meridian) % period)
                t = Fraction(distance,dx)
                if 0 <= t <= 1 and s <= y+dy*t <= n:
                    return True
    return False
