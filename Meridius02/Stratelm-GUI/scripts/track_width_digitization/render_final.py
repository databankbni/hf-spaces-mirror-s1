"""Final QA: overview with rebuilt centerline + edge polylines, and a few
sample closeups."""
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

import mosaic

d = pd.read_csv("track_edges_final.csv")
st = pd.read_csv("stations.csv")
MLAT = 111132.954 - 559.822 * np.cos(2 * np.radians(d.lat.mean()))
MLON = 111412.84 * np.cos(np.radians(d.lat.mean()))

# edge polylines in lat/lon (normals from the ORIGINAL stations, offsets L/R
# reconstructed from centerline shift +- half width)
nx, ny = st.nx.to_numpy(), st.ny.to_numpy()
latL = d.lat + (d.w_left_m * ny) / MLAT
lonL = d.lon + (d.w_left_m * nx) / MLON
latR = d.lat - (d.w_right_m * ny) / MLAT
lonR = d.lon - (d.w_right_m * nx) / MLON

pxC, pyC = mosaic.latlon_to_gpx(d.lat.to_numpy(), d.lon.to_numpy())
pxL, pyL = mosaic.latlon_to_gpx(latL.to_numpy(), lonL.to_numpy())
pxR, pyR = mosaic.latlon_to_gpx(latR.to_numpy(), lonR.to_numpy())

pad = 200
x0, y0 = pxC.min() - pad, pyC.min() - pad
x1, y1 = pxC.max() + pad, pyC.max() + pad
img = mosaic.get_crop(x0, y0, x1, y1)
im = Image.fromarray(img)
dr = ImageDraw.Draw(im)
dr.line(list(zip(pxL - int(x0), pyL - int(y0))), fill=(0, 255, 0), width=2)
dr.line(list(zip(pxR - int(x0), pyR - int(y0))), fill=(0, 200, 255), width=2)
dr.line(list(zip(pxC - int(x0), pyC - int(y0))), fill=(255, 255, 0), width=2)
im.reduce(3).save("final_overview.png")
print("final_overview.png", im.size)

# closeups
for s_m in [850, 1100, 1250, 1430, 2270, 2450]:
    i = (d.station_shell_m - s_m).abs().idxmin()
    half = 55 / mosaic.meters_per_pixel(d.lat[i])
    cx, cy = pxC[i], pyC[i]
    img = mosaic.get_crop(cx - half, cy - half, cx + half, cy + half)
    im = Image.fromarray(img).resize((int(2 * half * 1.5), int(2 * half * 1.5)))
    sc = 1.5
    dr = ImageDraw.Draw(im)
    m = (np.abs(pxC - cx) < half * 1.4) & (np.abs(pyC - cy) < half * 1.4)
    for px, py, col in ((pxL, pyL, (0, 255, 0)), (pxR, pyR, (0, 200, 255)), (pxC, pyC, (255, 255, 0))):
        pts = [((px[j] - int(cx - half)) * sc, (py[j] - int(cy - half)) * sc) for j in np.where(m)[0]]
        if len(pts) > 1:
            dr.line(pts, fill=col, width=2)
    im.save(f"final_zoom_{s_m:04d}.png")
print("closeups saved")
