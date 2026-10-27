"""Bounded marching squares on a sampled scalar field, with explicit missing cells.

Ambiguous bilinear saddles use the asymptotic decider. Exact saddle crossings
terminate four branches at the critical point instead of inventing a connection.
Contours are display interpolation, not additional meteorological resolution.
"""

import math
from collections import defaultdict

import numpy as np

from packages.flight.geojson import geometry


def nice_levels(values: np.ndarray) -> list[float]:
    finite = np.asarray(values)[np.isfinite(values)]
    if not len(finite):
        return []
    lo, hi = float(finite.min()), float(finite.max())
    if not math.isfinite(hi - lo):
        raise ValueError("Scalar range exceeds finite contour arithmetic")
    if hi - lo <= max(abs(lo), abs(hi), 1) * 1e-12:
        return []
    raw = (hi - lo) / 6
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m for m in (1, 2, 2.5, 5, 10) if m >= raw / magnitude) * magnitude
    return [
        float(k * step) for k in range(math.floor(lo / step) + 1, math.ceil(hi / step)) if lo < k * step < hi
    ]


def contour_lines(longitudes, latitudes, values, levels=None) -> dict:
    x, y, z = (np.asarray(a, dtype=float) for a in (longitudes, latitudes, values))
    if (
        x.ndim != 1
        or y.ndim != 1
        or z.shape != (len(y), len(x))
        or not 2 <= len(x) <= 65
        or not 2 <= len(y) <= 65
        or not np.all(np.isfinite(x))
        or not np.all(np.isfinite(y))
        or not np.all(np.diff(x) > 0)
        or not np.all(np.diff(y) > 0)
    ):
        raise ValueError("Contours require finite increasing axes and a bounded 2–65 point rectangular grid")
    levels = nice_levels(z) if levels is None else list(levels)
    if (
        len(levels) > 12
        or not np.all(np.isfinite(levels))
        or any(b <= a for a, b in zip(levels, levels[1:], strict=False))
    ):
        raise ValueError("Contour levels must be finite, increasing and bounded to twelve")
    valid = np.isfinite(z)
    cells = valid[:-1, :-1] & valid[1:, :-1] & valid[:-1, 1:] & valid[1:, 1:]
    features = []
    for level in levels:
        nodes: dict[tuple, list[float]] = {}
        graph: dict[tuple, set[tuple]] = defaultdict(set)

        def node(i, j, vertical, level=level, nodes=nodes):
            a, b = float(z[i, j]), float(z[i + vertical, j + 1 - vertical])
            weight = (level - a) / (b - a)
            if weight == 0:
                key = (i, j, 3)
            elif weight == 1:
                key = (i + vertical, j + 1 - vertical, 3)
            else:
                key = (i, j, vertical)
            nodes[key] = [
                float(x[j] + weight * (x[j + 1 - vertical] - x[j])),
                float(y[i] + weight * (y[i + vertical] - y[i])),
            ]
            return key

        def connect(a, b, graph=graph):
            if a != b:
                graph[a].add(b)
                graph[b].add(a)

        for i, j in zip(*np.where(cells), strict=True):
            corners = [float(z[i, j]), float(z[i, j + 1]), float(z[i + 1, j + 1]), float(z[i + 1, j])]
            inside = [a >= level for a in corners]
            edges = {}
            for edge, position in enumerate(((i, j, 0), (i, j + 1, 1), (i + 1, j, 0), (i, j, 1))):
                if inside[edge] != inside[(edge + 1) % 4]:
                    edges[edge] = node(*position)
            if len(edges) == 2:
                connect(*edges.values())
            elif len(edges) == 4:
                a, b, c, d = (value - level for value in corners)
                decision = a * c - b * d
                if decision == 0:
                    coefficient = a - b - d + c
                    key = (i, j, 2)
                    sx, sy = -(d - a) / coefficient, -(b - a) / coefficient
                    nodes[key] = [float(x[j] + sx * (x[j + 1] - x[j])), float(y[i] + sy * (y[i + 1] - y[i]))]
                    for edge in edges.values():
                        connect(edge, key)
                else:
                    for a_edge, b_edge in ((0, 1), (2, 3)) if decision > 0 else ((0, 3), (1, 2)):
                        connect(edges[a_edge], edges[b_edge])
        visited: set[tuple] = set()

        def trace(start, neighbor, nodes=nodes, graph=graph, visited=visited, level=level):
            path = [nodes[start]]
            previous, current = start, neighbor
            while True:
                visited.add(tuple(sorted((previous, current))))
                path.append(nodes[current])
                if len(graph[current]) != 2:
                    break
                following = next(n for n in graph[current] if n != previous)
                if tuple(sorted((current, following))) in visited:
                    break
                previous, current = current, following
            if len(path) >= 2:
                features.append(
                    {
                        "type": "Feature",
                        "properties": {"value": float(level)},
                        "geometry": geometry(
                            [{"longitude_deg": (p[0] + 180) % 360 - 180, "latitude_deg": p[1]} for p in path]
                        ),
                    }
                )

        for start in sorted(graph, key=lambda n: (len(graph[n]) == 2, n)):
            for neighbor in sorted(graph[start]):
                if tuple(sorted((start, neighbor))) not in visited:
                    trace(start, neighbor)
    return {
        "geojson": {"type": "FeatureCollection", "features": features},
        "levels": [float(level) for level in levels],
        "valid_cells": int(cells.sum()),
        "masked_cells": int(cells.size - cells.sum()),
        "algorithm": "marching_squares_bilinear_asymptotic_decider",
    }
