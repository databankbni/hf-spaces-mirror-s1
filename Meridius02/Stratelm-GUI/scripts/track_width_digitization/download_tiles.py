"""Step 2: download Esri World Imagery tiles (z20) covering a +-35 m corridor
around the centerline stations. Tiles cached to tiles/ as z_x_y.jpg."""
import math
import os
import time
import urllib.request

import numpy as np
import pandas as pd

Z = 19
CORRIDOR_M = 35.0
URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
HDRS = {"User-Agent": "SEM-DigitalTwin-research/1.0"}

st = pd.read_csv("stations.csv")


def tile_of(lat, lon, z=Z):
    n = 2 ** z
    xt = int((lon + 180.0) / 360.0 * n)
    yt = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return xt, yt


MLAT = 111132.954 - 559.822 * math.cos(2 * math.radians(st.lat.mean()))
MLON = 111412.84 * math.cos(math.radians(st.lat.mean()))

tiles = set()
for _, r in st.iterrows():
    for off in np.arange(-CORRIDOR_M, CORRIDOR_M + 1, 10.0):
        la = r.lat + (off * r.ny) / MLAT
        lo = r.lon + (off * r.nx) / MLON
        xt, yt = tile_of(la, lo)
        # include 3x3 neighborhood to be safe at tile borders
        for ddx in (-1, 0, 1):
            for ddy in (-1, 0, 1):
                tiles.add((xt + ddx, yt + ddy))

print(f"tiles needed: {len(tiles)}")
os.makedirs("tiles", exist_ok=True)
ok = fail = skip = 0
for i, (xt, yt) in enumerate(sorted(tiles)):
    path = f"tiles/{Z}_{xt}_{yt}.jpg"
    if os.path.exists(path) and os.path.getsize(path) > 0:
        skip += 1
        continue
    url = URL.format(z=Z, x=xt, y=yt)
    try:
        req = urllib.request.Request(url, headers=HDRS)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
        ok += 1
    except Exception as e:
        print(f"  FAIL {xt},{yt}: {e}")
        fail += 1
    if (ok + fail) % 100 == 0 and (ok + fail) > 0:
        print(f"  progress: {ok} ok, {fail} fail, {skip} cached")
        time.sleep(0.5)

print(f"done: {ok} downloaded, {fail} failed, {skip} cached")
