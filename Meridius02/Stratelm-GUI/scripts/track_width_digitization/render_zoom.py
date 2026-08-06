"""Plan-view closeups for ambiguous zones, with centerline, station labels
and detected edge points overlaid in map space."""
import sys

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

import mosaic

CENTERS = [int(a) for a in sys.argv[1:]] or [860, 920, 1250, 1350, 1450, 1650, 3050, 3150]
HALF_M = 32.0

st = pd.read_csv("stations.csv")
ed = pd.read_csv("edges_raw.csv").merge(st, on="station_m")
MLAT = 111132.954 - 559.822 * np.cos(2 * np.radians(st.lat.mean()))
MLON = 111412.84 * np.cos(np.radians(st.lat.mean()))

px_all, py_all = mosaic.latlon_to_gpx(st.lat.to_numpy(), st.lon.to_numpy())

for c_m in CENTERS:
    i = (st.station_m - c_m).abs().idxmin()
    mpp = mosaic.meters_per_pixel(st.lat[i])
    half = HALF_M / mpp
    cx, cy = px_all[i], py_all[i]
    x0, y0 = int(cx - half), int(cy - half)
    img = mosaic.get_crop(cx - half, cy - half, cx + half, cy + half)
    # upscale 2x for readability
    im = Image.fromarray(img).resize((img.shape[1] * 2, img.shape[0] * 2), Image.LANCZOS)
    dr = ImageDraw.Draw(im)

    def to_img(px, py):
        return (px - x0) * 2, (py - y0) * 2

    m = (np.abs(px_all - cx) < half * 1.2) & (np.abs(py_all - cy) < half * 1.2)
    pts = [to_img(px_all[j], py_all[j]) for j in np.where(m)[0]]
    if len(pts) > 1:
        dr.line(pts, fill=(255, 255, 0), width=2)
    for j in np.where(m)[0]:
        if st.station_m[j] % 50 == 0:
            x, y = to_img(px_all[j], py_all[j])
            dr.ellipse([x - 4, y - 4, x + 4, y + 4], outline=(255, 255, 0), width=2)
            dr.text((x + 6, y - 6), str(int(st.station_m[j])), fill=(255, 255, 0))
    # edge points
    for _, r in ed[m].iterrows():
        for off, col in ((r.off_left_m, (255, 0, 255)), (r.off_right_m, (0, 255, 255))):
            la = r.lat + (off * r.ny) / MLAT
            lo = r.lon + (off * r.nx) / MLON
            ppx, ppy = mosaic.latlon_to_gpx(la, lo)
            x, y = to_img(ppx, ppy)
            dr.ellipse([x - 3, y - 3, x + 3, y + 3], fill=col)
    im.save(f"zoom_{c_m:04d}.png")
    print(f"zoom_{c_m:04d}.png")
