"""Step 1: smooth the Shell centerline and resample to 5 m stations.

Outputs stations.csv: station_m, lat, lon, x_m, y_m, nx, ny (unit normal, left-of-travel).
Local XY frame: equirectangular around track mean (adequate over ~1.4 km extent).
"""
import math
import numpy as np
import pandas as pd
from scipy.interpolate import splprep, splev

SRC = "c:/Users/Terano/Downloads/Final_Project/data/sem_apme_2025-track_coordinates.csv"
OUT = "stations.csv"
STEP_M = 5.0

df = pd.read_csv(SRC, sep="\t")
lat0 = df.latitude.mean()
lon0 = df.longitude.mean()
MLAT = 111132.954 - 559.822 * math.cos(2 * math.radians(lat0))
MLON = 111412.84 * math.cos(math.radians(lat0))

x = (df.longitude.to_numpy() - lon0) * MLON
y = (df.latitude.to_numpy() - lat0) * MLAT

# Drop duplicate/near-duplicate consecutive points (Shell data is 1 m spaced but noisy)
keep = [0]
for i in range(1, len(x)):
    if math.hypot(x[i] - x[keep[-1]], y[i] - y[keep[-1]]) >= 0.5:
        keep.append(i)
x, y = x[keep], y[keep]
print(f"points after dedup: {len(x)} (of {len(df)})")

# Smoothing spline over the whole loop. s controls smoothness: with ~3600 pts and
# GPS noise ~2-4 m, allow average residual ~1.5 m -> s ~ n * (1.5**2)
n = len(x)
tck, u = splprep([x, y], s=n * 1.5**2, per=0)
# Arc-length resample
uu = np.linspace(0, 1, 20000)
xs, ys = splev(uu, tck)
ds = np.hypot(np.diff(xs), np.diff(ys))
s_cum = np.concatenate([[0], np.cumsum(ds)])
total = s_cum[-1]
print(f"smoothed length: {total:.1f} m (Shell said {df['distance (km)'].max()*1000:.0f} m)")

stations = np.arange(0, total, STEP_M)
xi = np.interp(stations, s_cum, xs)
yi = np.interp(stations, s_cum, ys)

# Tangent/normal via central differences
dx = np.gradient(xi)
dy = np.gradient(yi)
norm = np.hypot(dx, dy)
tx, ty = dx / norm, dy / norm
nx, ny = -ty, tx  # left of travel direction

lat = lat0 + yi / MLAT
lon = lon0 + xi / MLON

out = pd.DataFrame({
    "station_m": stations, "lat": lat, "lon": lon,
    "x_m": xi, "y_m": yi, "nx": nx, "ny": ny,
})
out.to_csv(OUT, index=False)
print(f"wrote {OUT}: {len(out)} stations every {STEP_M} m")
print("residual Shell->smoothed (sample):")
# distance from raw points to smoothed polyline (coarse check on every 50th pt)
from scipy.spatial import cKDTree
tree = cKDTree(np.c_[xs, ys])
d, _ = tree.query(np.c_[x[::50], y[::50]])
print(f"  median {np.median(d):.2f} m, p95 {np.percentile(d,95):.2f} m, max {d.max():.2f} m")
