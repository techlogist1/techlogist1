"""Headless hidden-line 3D. Pure standard library -- no numpy, no GL, no browser.

This repository has no third-party dependency and `verify.py` advertises that it
runs in CI with nothing installed. A renderer that needed numpy would quietly end
that, and the workflow has no pip step, so the daily run would go red on the one
image that must never break. The meshes here are ~100 vertices, so plain Python
is fast enough and the dependency is not worth buying.
"""
import math


def matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
            for i in range(3)]


def rotx(t):
    c, s = math.cos(t), math.sin(t)
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def roty(t):
    c, s = math.cos(t), math.sin(t)
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


def rotz(t):
    c, s = math.cos(t), math.sin(t)
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


class Mesh:
    """Triangles are for occlusion only; edges are what actually get drawn."""

    def __init__(self, verts, tris, edges):
        self.v = [tuple(map(float, p)) for p in verts]
        self.t = [tuple(t) for t in tris]
        self.e = list(edges)


def project(v3, w, h, dist, scale):
    """Perspective divide to screen space. Returns [(x, y)] and [depth]."""
    pts, zs = [], []
    for (x, y, z) in v3:
        d = dist - z
        if d < 1e-3:
            d = 1e-3
        pts.append((w * 0.5 + (x / d) * scale, h * 0.5 - (y / d) * scale))
        zs.append(d)
    return pts, zs


def hidden_line(mesh, M, w, h, dist=7.0, samples=6, scale=100.0, bias=0.012,
                yoff=0.0):
    """Rotate, project, split each edge into samples, keep the visible runs.

    No back-face culling and no per-face mean depth: every triangle is z-tested
    with the depth interpolated at the sample point. Back-facing triangles are
    by construction farther than the front surface at that pixel, so they never
    occlude wrongly -- which makes the result independent of winding order. The
    first version culled by winding and ate its own silhouette.

    A screen-space bounding box rejects almost every face before the barycentric
    test, which is what keeps this quick without numpy.
    """
    v3 = []
    for (x, y, z) in mesh.v:
        v3.append((M[0][0]*x + M[0][1]*(y + yoff) + M[0][2]*z,
                   M[1][0]*x + M[1][1]*(y + yoff) + M[1][2]*z,
                   M[2][0]*x + M[2][1]*(y + yoff) + M[2][2]*z))
    p2, z = project(v3, w, h, dist, scale)

    faces = []
    for (i, j, k) in mesh.t:
        a, b, c = p2[i], p2[j], p2[k]
        x0 = min(a[0], b[0], c[0]); x1 = max(a[0], b[0], c[0])
        y0 = min(a[1], b[1], c[1]); y1 = max(a[1], b[1], c[1])
        den = (b[0]-a[0]) * (c[1]-a[1]) - (c[0]-a[0]) * (b[1]-a[1])
        if abs(den) < 1e-9:
            continue
        faces.append((a, b, c, z[i], z[j], z[k], den, x0, x1, y0, y1,
                      i, j, k))

    out = []
    for (i, j) in mesh.e:
        P, Q = p2[i], p2[j]
        zi, zj = z[i], z[j]
        run = None
        for s in range(samples):
            t0 = s / samples
            t1 = (s + 1) / samples
            ax = P[0] + (Q[0]-P[0]) * t0; ay = P[1] + (Q[1]-P[1]) * t0
            bx = P[0] + (Q[0]-P[0]) * t1; by = P[1] + (Q[1]-P[1]) * t1
            tm = (t0 + t1) * 0.5
            mx = P[0] + (Q[0]-P[0]) * tm; my = P[1] + (Q[1]-P[1]) * tm
            zm = zi + (zj - zi) * tm

            hidden = False
            for (a, b, c, za, zb, zc, den, x0, x1, y0, y1, fi, fj, fk) in faces:
                if mx < x0 or mx > x1 or my < y0 or my > y1:
                    continue
                if i == fi or i == fj or i == fk or j == fi or j == fj or j == fk:
                    continue                    # its own face cannot hide it
                vx = mx - a[0]; vy = my - a[1]
                u = (vx * (c[1]-a[1]) - (c[0]-a[0]) * vy) / den
                if u < -1e-4:
                    continue
                v = ((b[0]-a[0]) * vy - vx * (b[1]-a[1])) / den
                if v < -1e-4 or u + v > 1 + 1e-4:
                    continue
                if za + u * (zb - za) + v * (zc - za) < zm - bias:
                    hidden = True
                    break

            if hidden:
                if run:
                    out.append((run[0], run[1]))
                    run = None
            else:
                run = [(ax, ay), (bx, by)] if run is None else [run[0], (bx, by)]
        if run:
            out.append((run[0], run[1]))
    return out


def paths_to_d(segs, prec=1, join=0.6):
    """Segments to a path `d`, relative-encoded.

    Absolute coordinates on a 556-wide plate run to three or four significant
    digits; the deltas between consecutive points are nearly all one or two.
    Relative commands therefore cut the string by about a third at identical
    precision, which is a better trade than dropping to integer coordinates --
    integers would round the sliding vernier ticks differently frame to frame
    and set them wobbling against the fixed ticks they are read against.
    """
    if not segs:
        return ""
    f = "%." + str(prec) + "f"

    def n(v):
        t = f % v
        if "." in t:
            t = t.rstrip("0").rstrip(".")
        return "0" if t in ("-0", "", "-") else t

    out, cx, cy = [], None, None
    for a, b in segs:
        if cx is None or abs(cx - a[0]) > join or abs(cy - a[1]) > join:
            out.append("M" + n(a[0]) + " " + n(a[1]))
            cx, cy = a
        out.append("l" + n(b[0] - cx) + " " + n(b[1] - cy))
        cx, cy = b
    return "".join(out).replace(" -", "-")
