"""Vernier calipers, as geometry. Hidden-line rendered, no GL.

The mechanism is the vernier principle: ten slider divisions span nine beam
divisions, so exactly one slider tick lines up with a beam tick, and which one
it is IS the fractional digit. A second scale makes a number exact -- which is
the page's own claim about its numbers, and belongs to no one repository.
"""
import math
from r3d import Mesh, rotx, roty, matmul, hidden_line, paths_to_d

FRONT_BEAM, FRONT_SLIDE = 0.16, 0.24


def box(x0, x1, y0, y1, z0, z1):
    v = [(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),
         (x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)]
    t = [(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),
         (1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    e = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
    return v, t, e


def merge(parts):
    V, T, E = [], [], []
    for v, t, e in parts:
        o = len(V)
        V += list(v)
        T += [(a+o, b+o, c+o) for a, b, c in t]
        E += [(a+o, b+o) for a, b in e]
    return Mesh(V, T, E)


def cyl(cx, cy, r, z0, z1, n=18):
    v, t, e = [], [], []
    for z in (z0, z1):
        for k in range(n):
            a = 2*math.pi*k/n
            v.append((cx + r*math.cos(a), cy + r*math.sin(a), z))
    c0 = len(v); v.append((cx, cy, z0))
    c1 = len(v); v.append((cx, cy, z1))
    for k in range(n):
        j = (k+1) % n
        e.append((k, j)); e.append((n+k, n+j))
        t += [(c0, j, k), (c1, n+k, n+j), (k, j, n+j), (k, n+j, n+k)]
    e += [(k, n+k) for k in range(0, n, 3)]
    return v, t, e


def caliper(slide_x, jaw_gap):
    """slide_x: slider left edge. jaw_gap: workpiece diameter being gripped."""
    parts = []
    # beam
    parts.append(box(-4.30, 4.30, -0.30, 0.30, -0.16, FRONT_BEAM))
    # fixed jaw: down-stop and the upper internal jaw
    parts.append(box(-4.30, -3.86, -2.05, 0.30, -0.16, FRONT_BEAM))
    parts.append(box(-4.30, -4.02,  0.30, 1.28, -0.16, FRONT_BEAM))
    # slider body, its lower measuring jaw and upper internal jaw
    s0, s1 = slide_x, slide_x + 1.30
    parts.append(box(s0, s1, -0.34, 0.62, -0.22, FRONT_SLIDE))
    parts.append(box(s0, s0 + 0.44, -2.05, -0.30, -0.16, FRONT_BEAM))
    parts.append(box(s0, s0 + 0.28,  0.62, 1.28, -0.16, FRONT_BEAM))
    # thumb roll
    parts.append(box(s1 - 0.10, s1 + 0.30, -0.20, 0.30, -0.10, 0.12))
    # the workpiece the jaws close on: a plain machined pin, gripped at its width
    r = jaw_gap / 2.0
    parts.append(cyl(-3.86 + r, -1.20, r, -0.10, 0.10))
    return merge(parts)


def scale_ticks(slide_x, mm_per_unit=6.0):
    """Beam ticks every 1 mm, slider ticks at 0.9 mm -- the vernier ratio.

    Returned as their own segment lists, slightly proud of the faces they sit
    on so the solid never swallows them, and so the slider's body correctly
    occludes the beam ticks it covers.
    """
    beam, vern = [], []
    x0 = -3.86
    for i in range(0, 49):
        x = x0 + i / mm_per_unit
        if x > 4.20:
            break
        long = (i % 10 == 0)
        y1 = 0.30
        y0 = 0.30 - (0.22 if long else 0.11)
        beam.append(((x, y0, FRONT_BEAM + 0.02), (x, y1, FRONT_BEAM + 0.02)))
    for k in range(11):
        x = slide_x + 0.14 + k * 0.9 / mm_per_unit
        y0 = -0.34
        y1 = -0.34 + (0.26 if k in (0, 10) else 0.15)
        vern.append(((x, y0, FRONT_SLIDE + 0.02), (x, y1, FRONT_SLIDE + 0.02)))
    return beam, vern


def with_segments(mesh, segs):
    """Append bare segments as extra edges so hidden_line z-tests them too."""
    V = list(mesh.v)
    E = list(mesh.e)
    for a, b in segs:
        i = len(V); V.append(a)
        j = len(V); V.append(b)
        E.append((i, j))
    return Mesh(V, mesh.t, E)


def frame(slide_x, gap, W, H, scale, dist, tilt, turn, samples=6, yoff=0.42):
    m = caliper(slide_x, gap)
    beam, vern = scale_ticks(slide_x)
    full = with_segments(m, beam + vern)
    M = matmul(rotx(math.radians(tilt)), roty(math.radians(turn)))
    return hidden_line(full, M, W, H, dist=dist, samples=samples, scale=scale,
                       yoff=yoff)
