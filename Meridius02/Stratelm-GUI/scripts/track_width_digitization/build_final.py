"""Step 5: apply manual overrides from the visual QA pass, clean outliers,
rebuild the true centerline as the edge midpoint, and export the final
per-point width dataset.

Override anchors were read off the straightened strip maps (grid = meters,
offsets relative to the smoothed Shell centerline, +left of travel).
Sections not listed keep the v2 detector output.
"""
import numpy as np
import pandas as pd

ed = pd.read_csv("edges_raw.csv")
st = pd.read_csv("stations.csv")
s = ed.station_m.to_numpy()

# ---- manual override anchor tables: list of (station, offset); linear interp
# applied over each anchor span. Sides handled independently.
L_OVR = [
    [(800, +4.0), (830, +2.0), (855, 0.0), (880, +3.0), (900, +1.0)],   # kart-junction red tongue
    [(1030, +2.0), (1065, +4.0), (1100, +7.0)],                          # road-fork upper edge
    [(1110, +6.0), (1150, +6.5)],                                        # dash-line dip
    [(1150, +6.0), (1180, +4.5), (1200, +3.5), (1250, +2.5), (1300, +1.5), (1360, +1.0), (1434, +1.0)],  # sand edge incl. blue lane (GT 11.47 m)
    [(1580, +2.0), (1620, +2.5)],                                        # lamppost wobble
    [(2250, +13.0), (2310, +12.0)],                                      # corner: anchor sat in service strip
    [(2400, +13.0), (2450, +13.0), (2500, +10.0)],                       # same failure mode
]
R_OVR = [
    [(300, -9.0), (355, -7.0)],                                          # pit-exit merge: keep pit band line
    [(830, -9.0), (895, -13.0)],                                         # kart junction -> sand edge
    [(1050, -7.0), (1075, -4.0), (1100, -0.5)],                          # road fork: stay on upper branch
    [(1100, -0.5), (1150, -1.0)],                                        # narrow road, own carriageway only
    [(1150, -1.5), (1180, -7.0), (1200, -8.0)],                          # merge at gate: widens to ~11.5 m (user GT 11.47)
    [(1200, -8.0), (1250, -9.5), (1300, -11.0)],                         # road right of blue lane
    [(1300, -11.0), (1350, -13.0), (1440, -13.0)],                       # pre-merge road
    [(170, -6.0), (190, -6.0)],                                          # band faded 175-185
    [(1535, -16.0), (1575, -18.0), (1620, -20.0)],                       # posts misread as edge
    [(2040, -5.0), (2100, -2.5)],                                        # kart entry tightening
    [(2250, +1.0), (2310, 0.0)],                                         # corner (see L)
    [(2400, 0.0), (2500, +1.0)],                                         # corner (see L)
    [(2700, -1.0), (2790, -2.0)],                                        # block curb, not beyond
    [(3200, -5.0), (3245, -5.0)],                                        # faint band section
    [(3300, -6.0), (3665, -5.5)],                                        # pit separation band, final straight
]


def apply_overrides(vals, tables):
    out = vals.copy()
    for anchors in tables:
        s0, s1 = anchors[0][0], anchors[-1][0]
        m = (s >= s0) & (s <= s1)
        xs = [a[0] for a in anchors]; ys = [a[1] for a in anchors]
        out[m] = np.interp(s[m], xs, ys)
    return out


L = apply_overrides(ed.off_left_m.to_numpy(), L_OVR)
R = apply_overrides(ed.off_right_m.to_numpy(), R_OVR)

# ---- outlier cleanup: rolling median (5 stations) with deviation clamp,
# run twice; known genuine discontinuity at the 1435 m merge is preserved
# by the override span ending there.
def clean(v):
    x = pd.Series(v)
    for _ in range(2):
        med = x.rolling(5, center=True, min_periods=1).median()
        dev = (x - med).abs()
        x = x.where(dev <= 2.0, med)
    return x.to_numpy()


L = clean(L)
R = clean(R)
width = L - R
print("width after cleanup (m):")
print(pd.Series(width).describe().round(2))

# plausibility floor/cap
bad = (width < 4) | (width > 30)
print(f"stations outside 4-30 m: {bad.sum()}")

# ---- rebuild centerline: midpoint of edges in map space
MLAT = 111132.954 - 559.822 * np.cos(2 * np.radians(st.lat.mean()))
MLON = 111412.84 * np.cos(np.radians(st.lat.mean()))
mid_off = (L + R) / 2.0
lat_c = st.lat.to_numpy() + (mid_off * st.ny.to_numpy()) / MLAT
lon_c = st.lon.to_numpy() + (mid_off * st.nx.to_numpy()) / MLON

# smooth the new centerline lightly (5-station rolling mean on the offset,
# then recompute; edges stay put -- only the reference line is smoothed)
mid_s = pd.Series(mid_off).rolling(5, center=True, min_periods=1).mean().to_numpy()
lat_c = st.lat.to_numpy() + (mid_s * st.ny.to_numpy()) / MLAT
lon_c = st.lon.to_numpy() + (mid_s * st.nx.to_numpy()) / MLON
w_left = L - mid_s
w_right = mid_s - R

# new arc length along rebuilt centerline
x = (lon_c - lon_c[0]) * MLON
y = (lat_c - lat_c[0]) * MLAT
ds = np.hypot(np.diff(x), np.diff(y))
s_new = np.concatenate([[0], np.cumsum(ds)])
print(f"rebuilt centerline length: {s_new[-1]:.1f} m (was {s[-1]:.0f} on Shell line)")

out = pd.DataFrame({
    "station_shell_m": s,            # station along the smoothed Shell reference
    "station_new_m": s_new,          # arc length along the rebuilt centerline
    "lat": lat_c, "lon": lon_c,
    "w_left_m": w_left, "w_right_m": w_right,
    "width_m": width,
    "centerline_shift_m": mid_s,     # how far the rebuilt centerline moved (+left)
})
out.to_csv("track_edges_final.csv", index=False)
print("wrote track_edges_final.csv")
print("\nwidth percentiles: p5=%.1f p25=%.1f p50=%.1f p75=%.1f p95=%.1f" % tuple(
    np.percentile(width, [5, 25, 50, 75, 95])))
print("centerline shift: median %.1f m, p95 %.1f m, max %.1f m" % (
    np.median(np.abs(mid_s)), np.percentile(np.abs(mid_s), 95), np.abs(mid_s).max()))
