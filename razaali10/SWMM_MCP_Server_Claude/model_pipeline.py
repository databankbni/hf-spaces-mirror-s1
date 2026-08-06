"""Headless SWMM model pipeline: INP parsing and result-summary builders.

Extracted verbatim from the SWMM6 GIS Tool (Rev 23.2) Streamlit app so the
same deterministic logic serves the MCP/REST server without a Streamlit
dependency. Includes the Rev 23.2 fix resolving IRREGULAR-section full depth
from [TRANSECTS] GR data.
"""
from __future__ import annotations

import pandas as pd
import numpy as np

def parse_inp_sections(inp_path):
    sections = {}
    current = None
    with open(inp_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            if line.startswith("["):
                try:
                    current = line[1:line.index("]")]
                    sections[current] = []
                except ValueError:
                    pass
            elif current is not None:
                sections[current].append(line.split())
    return sections

def parse_node_types(sections):
    types = {}
    for sname, ntype in [("JUNCTIONS", "junction"), ("OUTFALLS", "outfall"),
                          ("STORAGE", "storage"), ("DIVIDERS", "divider")]:
        for row in sections.get(sname, []):
            if row:
                types[row[0]] = ntype
    return types

def parse_link_topology(sections):
    """Return {link_id: (from_node, to_node, type)} dict."""
    topo = {}
    for sname, ltype in [("CONDUITS", "conduit"), ("PUMPS", "pump"),
                          ("ORIFICES", "orifice"), ("WEIRS", "weir"), ("OUTLETS", "outlet")]:
        for row in sections.get(sname, []):
            if len(row) >= 3:
                topo[row[0]] = (row[1], row[2], ltype)
    return topo

def parse_conduit_geometry(sections):
    """Return {conduit_id: {length, roughness, xsect_params}} dict."""
    geom = {}
    for row in sections.get("CONDUITS", []):
        if len(row) >= 6:
            try:
                geom[row[0]] = {"length": float(row[3]), "roughness": float(row[4])}
            except ValueError:
                pass
    # Full depth of IRREGULAR sections comes from the referenced transect's
    # GR rows (max station elevation - min station elevation), matching the
    # engine's Cross Section Summary "Full Depth". Previously float() failed
    # on the transect NAME in geom1 and the depth silently defaulted to
    # 1.0 m downstream, distorting depth ratios for street/overland links.
    transect_full_depth = {}
    current_transect = None
    for row in sections.get("TRANSECTS", []):
        tag = str(row[0]).upper()
        if tag == "X1" and len(row) >= 2:
            current_transect = row[1]
            transect_full_depth.setdefault(current_transect, [])
        elif tag == "GR" and current_transect is not None:
            # GR rows are (elev, station) pairs.
            for i in range(1, len(row) - 1, 2):
                try:
                    transect_full_depth[current_transect].append(float(row[i]))
                except ValueError:
                    pass
    transect_full_depth = {
        name: (max(elevs) - min(elevs)) for name, elevs in transect_full_depth.items() if elevs
    }
    for row in sections.get("XSECTIONS", []):
        if len(row) >= 3 and row[0] in geom:
            geom[row[0]]["shape"] = row[1]
            if str(row[1]).upper() == "IRREGULAR":
                geom[row[0]]["transect"] = row[2]
                full = transect_full_depth.get(row[2])
                if full and full > 0:
                    geom[row[0]]["diameter"] = full
            else:
                try:
                    geom[row[0]]["diameter"] = float(row[2])
                except (ValueError, IndexError):
                    pass
    return geom

def parse_subcatchment_attrs(sections):
    attrs = {}
    for row in sections.get("SUBCATCHMENTS", []):
        if len(row) >= 6:
            try:
                attrs[row[0]] = {
                    "gage": row[1],
                    "outlet": row[2],
                    "area": float(row[3]),
                    "pct_imp": float(row[4]),
                    "width": float(row[5]) if len(row) > 5 else 0.0,
                    "slope": float(row[6]) if len(row) > 6 else 0.0,
                }
            except (ValueError, IndexError):
                pass
    return attrs

def parse_gis(sections):
    """Extract node coords, link vertices, sub polygons from INP."""
    dims = get_map_dimensions(sections)

    # Node coordinates
    raw_coords = {}
    for row in sections.get("COORDINATES", []):
        if len(row) >= 3:
            try:
                raw_coords[row[0]] = (float(row[1]), float(row[2]))
            except ValueError:
                pass

    node_coords = normalize_coords(raw_coords, dims)

    # Link vertices
    raw_verts = {}
    for row in sections.get("VERTICES", []):
        if len(row) >= 3:
            try:
                raw_verts.setdefault(row[0], []).append((float(row[1]), float(row[2])))
            except ValueError:
                pass

    # Normalize vertices using same scale
    if raw_coords and dims:
        xmin, ymin, xmax, ymax = dims
        cx = (xmin + xmax) / 2
        cy = (ymin + ymax) / 2
        rx = max(xmax - xmin, 1e-9)
        ry = max(ymax - ymin, 1e-9)
        scale = 0.005 / max(rx, ry)
    elif raw_coords:
        xs = [v[0] for v in raw_coords.values()]
        ys = [v[1] for v in raw_coords.values()]
        cx = (min(xs) + max(xs)) / 2
        cy = (min(ys) + max(ys)) / 2
        scale = 0.005 / max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
    else:
        cx, cy, scale = 0, 0, 1

    link_vertices = {}
    for lid, verts in raw_verts.items():
        link_vertices[lid] = [((x - cx) * scale, (y - cy) * scale) for x, y in verts]

    # Subcatchment polygons
    raw_polys = {}
    for row in sections.get("Polygons", []):
        if len(row) >= 3:
            try:
                raw_polys.setdefault(row[0], []).append((float(row[1]), float(row[2])))
            except ValueError:
                pass

    sub_polygons = {}
    for sid, pts in raw_polys.items():
        sub_polygons[sid] = [((x - cx) * scale, (y - cy) * scale) for x, y in pts]

    return node_coords, link_vertices, sub_polygons

def build_node_summary(node_ts, node_types, flood_thresh, depth_ratio_thresh):
    rows = []
    for nid, d in node_ts.items():
        depths = d.get("depth", [0])
        floods = d.get("flooding", [0])
        inflows = d.get("inflow", [0])
        invert = d.get("invert_elevation", 0)
        full_d = d.get("full_depth", 1) or 1

        pk_depth = max(depths) if depths else 0
        pk_flood = max(floods) if floods else 0
        pk_inflow = max(inflows) if inflows else 0
        depth_ratio = pk_depth / full_d

        if pk_flood > flood_thresh:
            status = "🚨 Flooded"
        elif depth_ratio > depth_ratio_thresh:
            status = "⚠️ Near Capacity"
        else:
            status = "✅ OK"

        rows.append({
            "Node ID": nid,
            "Type": node_types.get(nid, "junction"),
            "Invert (m)": round(invert, 3),
            "Full Depth (m)": round(full_d, 3),
            "Peak Depth (m)": round(pk_depth, 4),
            "Depth Ratio": round(depth_ratio, 3),
            "Peak Flooding (m³/s)": round(pk_flood, 6),
            "Peak Inflow (m³/s)": round(pk_inflow, 6),
            "Status": status,
        })
    return pd.DataFrame(rows)

def build_link_summary(link_ts, link_topo, conduit_geom, depth_ratio_thresh, vel_thresh):
    rows = []
    for lid, d in link_ts.items():
        flows = d.get("flow", [0])
        depths = d.get("depth", [0])
        velocities = d.get("velocity", [0])
        topo = link_topo.get(lid, ("?", "?", "conduit"))
        geom = conduit_geom.get(lid, {})

        pk_flow = max(flows) if flows else 0
        pk_depth = max(depths) if depths else 0
        pk_velocity = max((abs(v) for v in velocities), default=0)
        diam = geom.get("diameter", 1) or 1
        length = geom.get("length", 0)
        depth_ratio = pk_depth / diam

        if depth_ratio >= 1.0:
            status = "Pressurised"
        elif depth_ratio > depth_ratio_thresh:
            status = "Surcharging"
        elif pk_velocity > vel_thresh:
            status = "High Velocity"
        elif depth_ratio > 0.5:
            status = "Filling"
        else:
            status = "Free-flow"

        rows.append({
            "Link ID": lid,
            "Type": topo[2],
            "From Node": topo[0],
            "To Node": topo[1],
            "Length (m)": round(length, 1),
            "Diameter (m)": round(diam, 3),
            "Peak Flow (m³/s)": round(pk_flow, 6),
            "Peak Depth (m)": round(pk_depth, 4),
            "Depth Ratio": round(depth_ratio, 3),
            "Peak Velocity (m/s)": round(pk_velocity, 3),
            "Status": status,
        })
    return pd.DataFrame(rows)

def build_sub_summary(sub_ts, sub_attrs, times=None, flow_units="CMS"):
    """Build subcatchment summary with time-integrated runoff volume.

    Values remain in the SWMM model unit system. The legacy internal column name
    ``Total Runoff (m³)`` is retained for database compatibility, but its value is
    flow integrated over time in the native flow-volume basis (e.g., ft³ for CFS,
    m³ for CMS, litres for LPS). The report engine assigns the correct label.
    """
    rows = []
    flow_units = str(flow_units or "CMS").upper()

    def _integrate(values, timestamps):
        if not values:
            return 0.0
        if timestamps and len(timestamps) == len(values) and len(values) > 1:
            total = 0.0
            for i in range(1, len(values)):
                try:
                    dt = (timestamps[i] - timestamps[i - 1]).total_seconds()
                except Exception:
                    dt = 0.0
                if dt > 0:
                    total += 0.5 * (float(values[i - 1]) + float(values[i])) * dt
            return total
        return float(sum(values))

    def _rain_depth(values, timestamps):
        # Rainfall is an intensity (in/hr for US, mm/hr for SI).
        return _integrate(values, timestamps) / 3600.0

    for sid, d in sub_ts.items():
        runoffs = d.get("runoff", [0])
        rainfalls = d.get("rainfall", [0])
        attrs = sub_attrs.get(sid, {})
        area = d.get("area", attrs.get("area", 0))
        pct_imp = d.get("pct_imp", attrs.get("pct_imp", 0))

        pk_runoff = max(runoffs) if runoffs else 0
        pk_rainfall = max(rainfalls) if rainfalls else 0
        integrated_flow_seconds = _integrate(runoffs, times)
        total_rain_depth = _rain_depth(rainfalls, times)

        # Convert integrated native flow to the native report volume basis.
        if flow_units == "CFS":
            total_runoff_vol = integrated_flow_seconds  # ft³
            runoff_depth = (total_runoff_vol / (area * 43560.0) * 12.0) if area > 0 else 0.0
        elif flow_units == "CMS":
            total_runoff_vol = integrated_flow_seconds  # m³
            runoff_depth = (total_runoff_vol / (area * 10000.0) * 1000.0) if area > 0 else 0.0
        elif flow_units == "LPS":
            total_runoff_vol = integrated_flow_seconds  # litres
            runoff_depth = ((total_runoff_vol / 1000.0) / (area * 10000.0) * 1000.0) if area > 0 else 0.0
        else:
            total_runoff_vol = integrated_flow_seconds
            runoff_depth = 0.0

        rc = (runoff_depth / total_rain_depth) if total_rain_depth > 0 else 0.0

        rows.append({
            "Sub ID": sid,
            "Area (ha)": round(area, 3),
            "% Impervious": round(pct_imp, 1),
            "Connected To": attrs.get("outlet", "?"),
            "Peak Runoff (m³/s)": round(pk_runoff, 6),
            "Total Runoff (m³)": round(total_runoff_vol, 3),
            "Peak Rainfall (mm/h)": round(pk_rainfall, 4),
            "Total Rainfall Depth": round(total_rain_depth, 4),
            "Runoff Depth": round(runoff_depth, 4),
            "Runoff Coefficient": round(rc, 3),
        })
    return pd.DataFrame(rows)
