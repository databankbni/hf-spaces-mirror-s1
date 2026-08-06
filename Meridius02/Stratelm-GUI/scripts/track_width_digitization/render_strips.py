"""Step 4 prep: render straightened strip maps (along-track x across-track)
at 0.2 m/px, 100 m per strip, with detected edges, centerline and a meter
grid overlaid. These are the images used for eyeball QA + manual overrides.

Strip orientation: TOP of image = LEFT of travel direction (+normal).
Vertical yellow line every 10 m along; horizontal gray grid every 5 m across.
Magenta = detected left edge, cyan = detected right edge, yellow center dots.
"""
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

import mosaic

RES = 0.2          # m per pixel
CHUNK_M = 100.0
ACROSS_M = 30.0    # +- range across track

st = pd.read_csv("stations.csv")
ed = pd.read_csv("edges_raw.csv")
MLAT = 111132.954 - 559.822 * np.cos(2 * np.radians(st.lat.mean()))
MLON = 111412.84 * np.cos(np.radians(st.lat.mean()))

# dense along-track interpolation (1 m) of position and normal
s_st = st.station_m.to_numpy()
s_d = np.arange(0, s_st[-1], 1.0)


def interp(col):
    return np.interp(s_d, s_st, st[col].to_numpy())


lat_d, lon_d = interp("lat"), interp("lon")
nx_d, ny_d = interp("nx"), interp("ny")
nrm = np.hypot(nx_d, ny_d)
nx_d, ny_d = nx_d / nrm, ny_d / nrm

acr = np.arange(ACROSS_M, -ACROSS_M - 1e-9, -RES)  # top row = +ACROSS (left)
n_acr = len(acr)

n_chunks = int(np.ceil(s_d[-1] / CHUNK_M))
for c in range(n_chunks):
    m0, m1 = c * CHUNK_M, min((c + 1) * CHUNK_M, s_d[-1])
    sel = (s_d >= m0) & (s_d < m1)
    idx = np.where(sel)[0]
    # supersample along at RES too
    s_loc = np.arange(m0, m1, RES)
    la = np.interp(s_loc, s_d, lat_d); lo = np.interp(s_loc, s_d, lon_d)
    nx = np.interp(s_loc, s_d, nx_d); ny = np.interp(s_loc, s_d, ny_d)

    LA = la[None, :] + (acr[:, None] * ny[None, :]) / MLAT
    LO = lo[None, :] + (acr[:, None] * nx[None, :]) / MLON
    px, py = mosaic.latlon_to_gpx(LA, LO)
    img = mosaic.sample_rgb(px, py).astype(np.uint8)

    im = Image.fromarray(img)
    dr = ImageDraw.Draw(im)
    W, H = im.size

    def y_of(off):  # across offset (m, +left) -> row
        return int(round((ACROSS_M - off) / RES))

    def x_of(s_m):
        return int(round((s_m - m0) / RES))

    # grid: vertical every 10 m along
    for s_g in np.arange(np.ceil(m0 / 10) * 10, m1, 10):
        x = x_of(s_g)
        dr.line([(x, 0), (x, H)], fill=(255, 255, 0), width=1)
        dr.text((x + 2, 2), f"{int(s_g)}", fill=(255, 255, 0))
    # horizontal every 5 m across
    for a_g in np.arange(-ACROSS_M + 5, ACROSS_M, 5):
        y = y_of(a_g)
        col = (255, 255, 0) if a_g == 0 else (160, 160, 160)
        dr.line([(0, y), (W, y)], fill=col, width=1)
        dr.text((2, y - 12), f"{int(a_g):+d}", fill=col)

    # detected edges
    m = (ed.station_m >= m0 - 5) & (ed.station_m <= m1 + 5)
    for _, r in ed[m].iterrows():
        x = x_of(r.station_m)
        dr.ellipse([x - 2, y_of(r.off_left_m) - 2, x + 2, y_of(r.off_left_m) + 2],
                   fill=(255, 0, 255))
        dr.ellipse([x - 2, y_of(r.off_right_m) - 2, x + 2, y_of(r.off_right_m) + 2],
                   fill=(0, 255, 255))

    im.save(f"strip_{int(m0):04d}.png")
print(f"saved {n_chunks} strips")
