"""Periodic longitude -> planar representation shared by migration, compatible
writes and region queries after the SDK2 switch.

Representation invariant
------------------------
1. Original coordinates are never rewritten: sdk2_tracks.original_json keeps the
   exact integer point lists that the business API received.
2. Geometry is expressed on the universal cover of the longitude circle. The
   raw longitude step of each adjacent pair is folded into the shortest signed
   arc, exactly as SDK1 folds dx (a step outside [-D, D] is shifted by one
   period):
   - an exact +/- period tie therefore keeps the sign of the *raw* difference;
   - -180 and +180 are the same meridian: their raw difference folds to zero
     and the pair becomes a degenerate segment on that meridian.
3. A folded arc that leaves the base band [-D, D] through a dateline boundary
   is split at that boundary and continued from the equivalent opposite
   meridian, preserving travel order and linear latitude interpolation. Every
   stored piece therefore lies wholly inside [-D, D] (and y inside [-Y, Y]),
   which:
   - keeps every coordinate inside plane2's accepted +/-3D limit for tracks of
     any length and any number of fold-backs;
   - guarantees no stored segment can straddle a planar query-box vertical
     boundary outside the box's latitude span, which is the one orientation
     plane2.intersects does not classify generically;
   - keeps the periodic track continuous: the two split pieces meet at
     period-equivalent (+D/-D) meridians.
4. A periodic query window maps to closed planar boxes shifted by k*period.
   k in {-1, 0, 1} covers every piece coordinate that can exist; a global
   window is one [-3D, 3D] box. Local windows never use a global box. The
   circular width handles w > e (crossing windows) explicitly. Candidates come
   exclusively from plane2.candidates (RTree) and are filtered by
   plane2.intersects; callers sort and de-duplicate track ids.

This module is the single owner of the periodic->planar conventions. It uses
plain integer arithmetic only; SDK1 (vendor.periodic1) is never imported here.
"""
from fractions import Fraction

from model import D

PERIOD = 2 * D
PLANAR_LIMIT = 3 * D


def base_longitude(x):
    """Representative of a raw longitude inside the base band [-D, D]."""
    r = x % PERIOD
    if r > D:
        r -= PERIOD
    return r


def folded_step(x0, x1):
    """Shortest signed longitude arc from raw x0 to raw x1.

    The fold uses the RAW endpoint difference, exactly mirroring SDK1's dx
    rule: a step of +D or -D is an exact tie and is NOT shifted, so the sign of
    the original longitude difference decides direction. Rebasing x0 first
    would invert a +/-180 tie (e.g. -180 -> 0 has raw dx +D and must keep the
    positive arc through -180deg, not become a -D sweep from +180deg).
    """
    delta = x1 - x0
    if delta > D:
        delta -= PERIOD
    elif delta < -D:
        delta += PERIOD
    return delta


def segment_pieces(p0, p1):
    """Planar pieces for one adjacent original pair.

    The folded arc starts at the base-band representative of p0 and follows
    SDK1's signed shortest arc. Returns one piece when it stays in the base
    band, otherwise two pieces split at the crossed dateline boundary.
    """
    x0, y0 = p0
    x1, y1 = p1
    start = base_longitude(x0)
    delta = folded_step(x0, x1)
    end = start + delta
    if -D <= min(start, end) and max(start, end) <= D:
        return [[[start, y0], [end, y1]]]
    boundary = D if delta > 0 else -D
    f = Fraction(boundary - start, delta)
    y_cut = y0 + (y1 - y0) * f
    other = -boundary
    far_end = end + (-PERIOD if delta > 0 else PERIOD)
    return [
        [[start, y0], [boundary, _int_or_fraction(y_cut)]],
        [[other, _int_or_fraction(y_cut)], [far_end, y1]],
    ]


def _int_or_fraction(value):
    if value.denominator == 1:
        return int(value)
    return value


def pieces(ps):
    """All planar pieces for a validated original track."""
    out = []
    for p0, p1 in zip(ps, ps[1:]):
        out.extend(segment_pieces(p0, p1))
    return out


def _circular_width(w, e):
    """Width of the closed arc from w to e along increasing longitude.

    Unlike a bare Python modulo, this stays correct when w > e (crossing
    window): the arc wraps through +/-D. w == e is a single meridian (0),
    w=-D,e=D is the full period (handled by the caller as global).
    """
    width = e - w
    if width < 0:
        width += PERIOD
    return width


def query_boxes(w, s, e, n):
    """Translate a validated periodic window into closed planar boxes.

    Returns (w2, s, e2, n) rectangles whose union on the cover is exactly the
    window. Global windows produce one full-cover box; every other window
    produces three period-shifted local boxes.
    """
    if w == -D and e == D:
        return [(-PLANAR_LIMIT, s, PLANAR_LIMIT, n)]
    width = _circular_width(w, e)
    return [(w + k * PERIOD, s, w + width + k * PERIOD, n)
            for k in (-1, 0, 1)]
