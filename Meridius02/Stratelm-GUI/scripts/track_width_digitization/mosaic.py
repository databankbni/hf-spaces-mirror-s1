"""Shared imagery access: lat/lon <-> global z20 pixel coords, tile cache,
crop extraction, and bilinear sampling of brightness along arbitrary lines."""
import math
import os

import numpy as np
from PIL import Image

Z = 19
TILE = 256
N = 2 ** Z
TDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tiles")

_cache = {}


def latlon_to_gpx(lat, lon):
    """lat/lon -> global pixel (float) at zoom Z. Returns (px, py)."""
    px = (lon + 180.0) / 360.0 * N * TILE
    py = (1.0 - np.arcsinh(np.tan(np.radians(lat))) / math.pi) / 2.0 * N * TILE
    return px, py


def gpx_to_latlon(px, py):
    lon = px / (N * TILE) * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(math.pi * (1 - 2 * py / (N * TILE)))))
    return lat, lon


def meters_per_pixel(lat):
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** Z)


def get_tile(xt, yt):
    key = (xt, yt)
    if key not in _cache:
        path = os.path.join(TDIR, f"{Z}_{xt}_{yt}.jpg")
        if os.path.exists(path):
            _cache[key] = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
        else:
            _cache[key] = np.zeros((TILE, TILE, 3), dtype=np.uint8)
    return _cache[key]


def get_crop(px_min, py_min, px_max, py_max):
    """Return RGB array covering the global-pixel box (int coords)."""
    px_min, py_min = int(px_min), int(py_min)
    px_max, py_max = int(px_max), int(py_max)
    w, h = px_max - px_min, py_max - py_min
    out = np.zeros((h, w, 3), dtype=np.uint8)
    t0x, t0y = px_min // TILE, py_min // TILE
    t1x, t1y = (px_max - 1) // TILE, (py_max - 1) // TILE
    for ty in range(t0y, t1y + 1):
        for tx in range(t0x, t1x + 1):
            tile = get_tile(tx, ty)
            gx0, gy0 = tx * TILE, ty * TILE
            sx0 = max(px_min, gx0); sy0 = max(py_min, gy0)
            sx1 = min(px_max, gx0 + TILE); sy1 = min(py_max, gy0 + TILE)
            if sx1 <= sx0 or sy1 <= sy0:
                continue
            out[sy0 - py_min:sy1 - py_min, sx0 - px_min:sx1 - px_min] = \
                tile[sy0 - gy0:sy1 - gy0, sx0 - gx0:sx1 - gx0]
    return out


def sample_rgb(px, py):
    """Bilinear sample RGB at arrays of global pixel coords."""
    px = np.asarray(px); py = np.asarray(py)
    x0 = np.floor(px).astype(np.int64); y0 = np.floor(py).astype(np.int64)
    fx = px - x0; fy = py - y0
    out = np.zeros(px.shape + (3,), dtype=np.float64)
    for dy in (0, 1):
        for dx in (0, 1):
            w = (fx if dx else 1 - fx) * (fy if dy else 1 - fy)
            xs = x0 + dx; ys = y0 + dy
            vals = np.zeros(px.shape + (3,))
            # group by tile
            txs = xs // TILE; tys = ys // TILE
            for tx, ty in set(zip(txs.ravel().tolist(), tys.ravel().tolist())):
                m = (txs == tx) & (tys == ty)
                tile = get_tile(tx, ty)
                vals[m] = tile[ys[m] - ty * TILE, xs[m] - tx * TILE]
            out += w[..., None] * vals
    return out
