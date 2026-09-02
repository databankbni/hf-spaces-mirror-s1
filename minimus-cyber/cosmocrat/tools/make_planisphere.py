"""
Rigenera assets/planisphere.png per Cosmocrat — pixel art, mare blu, orografia cartografica.

Proiezione: quella EMPIRICA del planisfero esistente, ricavata per regressione da
lat/lon -> nx/ny sui 150 sinecismi, così i marker restano allineati alle coste.
    nx = A*lon + B   (con wrap all'antimeridiano)
    ny = C*lat + D

Orografia: campo di elevazione costruito dalle PRINCIPALI CATENE MONTUOSE reali
(polilinee lat/lon con altezza e larghezza), più un lieve rialzo continentale.
È una stilizzazione ancorata alla geografia reale, non un raster di elevazione.
"""
import json, math
import numpy as np
from PIL import Image, ImageDraw

REPO = r"C:\Users\frave\Downloads\cosmocrat-repo\cosmocrat"
TOPO = REPO + r"\assets\world-110m.json"
OUT = REPO + r"\assets\planisphere.png"

A, B = 0.00266592, 0.459987
C, D = -0.00618271, 0.499970
W, H, SCALE = 1920, 960, 2   # maschera a risoluzione doppia (Italia, Manica visibili)
LW, LH = W // SCALE, H // SCALE
WRAP_PX = 360 * A * LW

# ─── TopoJSON ───
topo = json.load(open(TOPO, encoding="utf-8"))
ts, tt = topo["transform"]["scale"], topo["transform"]["translate"]

def decode(arc):
    x = y = 0; out = []
    for dx, dy in arc:
        x += dx; y += dy
        out.append((x * ts[0] + tt[0], y * ts[1] + tt[1]))
    return out
ARCS = [decode(a) for a in topo["arcs"]]

def ring_coords(idxs):
    out = []
    for i in idxs:
        arc = ARCS[~i][::-1] if i < 0 else ARCS[i]
        out.extend(arc if not out else arc[1:])
    return out

def unwrap(pts):
    """Evita le sbavature orizzontali: srotola le longitudini così che due punti
       consecutivi non saltino mai piu' di 180 gradi (bug dell'antimeridiano)."""
    if not pts: return pts
    out = [pts[0]]
    for lon, lat in pts[1:]:
        plon = out[-1][0]
        while lon - plon > 180: lon -= 360
        while lon - plon < -180: lon += 360
        out.append((lon, lat))
    return out

mask = Image.new("L", (LW, LH), 0)
dr = ImageDraw.Draw(mask)
proj = lambda lon, lat, off=0.0: ((A * lon + B) * LW + off, (C * lat + D) * LH)

for g in topo["objects"]["land"]["geometries"]:
    polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
    for poly in polys:
        for ri, ring in enumerate(poly):
            pts = unwrap(ring_coords(ring))
            for off in (-WRAP_PX, 0.0, WRAP_PX):
                pr = [proj(lo, la, off) for lo, la in pts]
                xs = [p[0] for p in pr]
                if max(xs) < -2 or min(xs) > LW + 2: continue
                dr.polygon(pr, fill=(255 if ri == 0 else 0))

M = np.array(mask) > 127

# I sinecismi insulari del Pacifico (Tahiti, Hawaii, Fiji, Samoa, Tonga, Rapa Nui,
# Guam...) non esistono nel dataset a 110m: senza di loro il marker galleggerebbe
# sul mare. Li stampiamo come piccole isole dove serve.
SIN = json.load(open(REPO + r"\data\sinecismi.json", encoding="utf-8"))["sinecismi"]
added = 0
for s in SIN:
    px = int(s["nx"] * LW); py = int(s["ny"] * LH)
    if not (0 <= px < LW and 0 <= py < LH):
        continue
    y0, y1 = max(0, py - 2), min(LH, py + 3)
    x0, x1 = max(0, px - 2), min(LW, px + 3)
    if M[y0:y1, x0:x1].any():
        continue                      # c'e' gia' terra vicina
    yy, xx = np.ogrid[-py:LH - py, -px:LW - px]
    M |= (xx * xx + yy * yy) <= 4      # isolotto di ~2 px logici
    added += 1
print("isole aggiunte per sinecismi senza terra:", added)

# ─── DENOISE: coste pulite (silhouette leggibili, non frastagliate) ───────
# Chiusura morfologica: consolida le terre e chiude insenature/buchi piu' piccoli
# di ~1 tessera, togliendo le tessere blu sparse dentro i continenti.
from PIL import ImageFilter as _IF
_m = Image.fromarray((M * 255).astype(np.uint8))
_m = _m.filter(_IF.MaxFilter(5)).filter(_IF.MinFilter(5))   # close
M = np.array(_m) > 127

# ─── RICONOSCIBILITÀ SIMBOLICA ───────────────────────────────────────────
# Non accuratezza geografica ma silhouette riconoscibili a questa risoluzione:
# si SCAVANO gli stretti iconici (mare) e si GARANTISCONO penisole/isole iconiche
# (terra), largh. ~1 tessera, cosi le forme celebri (stivale, Irlanda, NZ...) si
# leggono anche con tessere R=5.
_carve = Image.new("L", (LW, LH), 0); _cdr = ImageDraw.Draw(_carve)
_land = Image.new("L", (LW, LH), 0); _ldr = ImageDraw.Draw(_land)
def _pxs(seg): return [((A * lo + B) * LW, (C * la + D) * LH) for lo, la in seg]
def carve(seg, w): _cdr.line(_pxs(seg), fill=255, width=max(1, int(w)))
def land(seg, w):  _ldr.line(_pxs(seg), fill=255, width=max(1, int(w)))
# stretti da aprire (mare)
carve([(-5.2, 50.0), (1.7, 51.1)], 5)         # Manica: Gran Bretagna staccata
carve([(-6.3, 52.0), (-5.0, 54.8)], 5)        # Mare d'Irlanda: Irlanda staccata
carve([(174.2, -40.4), (175.0, -41.7)], 4)    # Stretto di Cook: NZ in due isole
carve([(-5.7, 35.8), (-5.1, 36.2)], 3)        # Gibilterra
carve([(129.2, 34.6), (131.1, 33.8)], 3)      # Stretto di Corea: Giappone staccato
carve([(145.8, -39.4), (147.6, -40.9)], 3)    # Stretto di Bass: Tasmania
carve([(15.1, 38.5), (15.8, 37.9)], 2)        # Stretto di Messina: Sicilia
carve([(-64.0, 18.0), (-60.5, 12.0)], 2)      # arco delle Piccole Antille
# terre/penisole da garantire (silhouette)
land([(12.3, 45.6), (13.6, 43.0), (15.6, 41.2), (17.2, 41.0), (18.5, 40.0)], 5)  # stivale d'Italia
land([(15.5, 38.2), (16.4, 38.7)], 4)         # punta della Calabria
land([(-9.5, 52.0), (-6.0, 55.0), (-8.5, 55.2)], 6)   # Irlanda
land([(172.6, -35.5), (175.5, -38.0), (177.5, -38.7)], 5)  # NZ isola nord
land([(167.5, -44.5), (170.5, -45.8), (173.5, -42.0)], 5)  # NZ isola sud
land([(-20.0, 63.8), (-13.5, 65.6), (-22.5, 66.2)], 6)     # Islanda
land([(-81.5, 23.0), (-78.0, 22.0)], 4)       # Cuba
land([(46.0, -16.0), (49.5, -18.0), (47.0, -25.0)], 6)     # Madagascar
M = (M | (np.array(_land) > 127)) & ~(np.array(_carve) > 127)

# ─── griglie lon/lat ───
cols = np.arange(LW); rows = np.arange(LH)
lon_of_col = (((cols + 0.5) / LW) - B) / A
lat_of_row = (((rows + 0.5) / LH) - D) / C
LON = np.repeat(lon_of_col[None, :], LH, axis=0)
LAT = np.repeat(lat_of_row[:, None], LW, axis=1)

# ─── distanza dalla costa (chamfer, senza scipy) ───
def chamfer(binary):
    INF = 1e9
    d = np.where(binary, INF, 0.0); h, w = d.shape
    for y in range(h):
        r, rp = d[y], (d[y-1] if y else None)
        for x in range(w):
            if r[x] == 0: continue
            b = r[x]
            if rp is not None:
                b = min(b, rp[x] + 1)
                if x:      b = min(b, rp[x-1] + 1.414)
                if x < w-1: b = min(b, rp[x+1] + 1.414)
            if x: b = min(b, r[x-1] + 1)
            r[x] = b
    for y in range(h-1, -1, -1):
        r, rn = d[y], (d[y+1] if y < h-1 else None)
        for x in range(w-1, -1, -1):
            if r[x] == 0: continue
            b = r[x]
            if rn is not None:
                b = min(b, rn[x] + 1)
                if x:      b = min(b, rn[x-1] + 1.414)
                if x < w-1: b = min(b, rn[x+1] + 1.414)
            if x < w-1: b = min(b, r[x+1] + 1)
            r[x] = b
    return d

dist_land = chamfer(M)
dist_sea = chamfer(~M)

# ─── catene montuose reali: (waypoints lon/lat, altezza 0-1, larghezza in gradi) ───
RANGES = [
    ([(72,36),(76,35),(80,32),(86,28),(91,28),(95,29)], 1.00, 3.2),   # Himalaya-Karakoram
    ([(80,33),(87,33),(94,32)],                          0.58, 7.0),   # altopiano tibetano (bruno, non neve)
    ([(68,35),(72,36)],                                  0.86, 2.2),   # Hindu Kush
    ([(74,42),(80,42),(86,43)],                          0.80, 2.6),   # Tien Shan
    ([(88,49),(94,51),(100,52)],                         0.68, 3.0),   # Altai-Sayan
    ([(46,36),(51,33),(56,28)],                          0.70, 2.4),   # Zagros
    ([(51,36),(56,36)],                                  0.70, 1.5),   # Elburz
    ([(40,43),(45,42)],                                  0.78, 1.6),   # Caucaso
    ([(30,37),(36,38),(41,39)],                          0.60, 2.0),   # Tauro-Anatolia
    ([(60,66),(59,58),(58,51)],                          0.48, 2.0),   # Urali
    ([(6,45.8),(10,47),(14,47)],                         0.74, 1.8),   # Alpi
    ([(-1.5,42.8),(1,42.6)],                             0.58, 1.2),   # Pirenei
    ([(19,49.5),(24,47.5)],                              0.52, 1.5),   # Carpazi
    ([(8,61),(14,66),(20,69)],                           0.55, 2.0),   # Scandi
    ([(-8,31),(-3,32),(3,36),(9,36.5)],                  0.58, 1.7),   # Atlante
    ([(37,9),(39,13),(38,6)],                            0.52, 2.6),   # altopiano etiopico
    ([(29,-2),(35,-6),(30,-10)],                         0.58, 2.4),   # rift africano
    ([(28,-29),(30,-26)],                                0.56, 1.8),   # Drakensberg
    ([(-115,60),(-116,50),(-110,43),(-106,37),(-108,32)],0.80, 3.2),   # Montagne Rocciose
    ([(-122,48),(-120,40),(-118,36)],                    0.72, 1.8),   # Cascate-Sierra
    ([(-80,36),(-78,40),(-71,45)],                       0.42, 2.2),   # Appalachi
    ([(-73,10),(-76,2),(-77,-9),(-70,-18),(-70,-30),(-71,-42),(-73,-52)], 0.95, 2.6),  # Ande
    ([(-46,-18),(-42,-21),(-51,-16)],                    0.46, 4.5),   # altopiano brasiliano
    ([(-61,4),(-56,3)],                                  0.46, 2.6),   # scudo della Guiana
    ([(146,-19),(148,-27),(150,-35)],                    0.52, 1.8),   # Great Dividing Range
    ([(139,-4),(145,-6)],                                0.78, 1.8),   # Nuova Guinea
    ([(137,36),(139,36)],                                0.58, 1.3),   # Alpi giapponesi
    ([(158,55),(160,60)],                                0.56, 1.8),   # Kamchatka
    ([(128,66),(140,68)],                                0.52, 2.6),   # Verkhoyansk
    ([(96,20),(100,25),(104,29)],                        0.60, 2.2),   # Birmania-Yunnan
    ([(174,-41),(170,-44)],                              0.58, 1.2),   # Alpi neozelandesi
]

def seg_dist(lon, lat, p1, p2):
    """distanza approssimata (in gradi, corretta per la latitudine) da un segmento"""
    dlon = ((lon - p1[0] + 180) % 360) - 180
    k = np.cos(np.radians(lat))
    ax, ay = dlon * k, lat - p1[1]
    bx = (((p2[0] - p1[0] + 180) % 360) - 180) * np.cos(math.radians((p1[1] + p2[1]) / 2))
    by = p2[1] - p1[1]
    L2 = bx * bx + by * by
    t = np.clip((ax * bx + ay * by) / L2, 0, 1) if L2 > 0 else 0
    return np.hypot(ax - t * bx, ay - t * by)

elev = np.zeros((LH, LW), dtype=float)
for pts, peak, width in RANGES:
    for p1, p2 in zip(pts, pts[1:]) if len(pts) > 1 else [(pts[0], pts[0])]:
        d = seg_dist(LON, LAT, p1, p2)
        elev = np.maximum(elev, peak * np.exp(-(d / width) ** 2))

# lieve rialzo continentale (interni un po' piu' alti delle coste), senza dominare
elev = np.maximum(elev, 0.16 * np.clip(dist_land / 14.0, 0, 1))
elev[~M] = 0

# ─── grandi deserti: (lon_c, lat_c, semiasse_lon, semiasse_lat) ───
DESERTS = [
    (10, 23, 26, 8.5),    # Sahara
    (47, 22, 9, 6),       # Arabico
    (104, 43, 9, 4.5),    # Gobi
    (83, 39, 7, 3),        # Taklamakan
    (61, 41, 8, 4),        # Karakum-Kyzylkum
    (71.5, 27, 3.5, 3),    # Thar
    (20, -23, 6, 5),       # Kalahari-Namib
    (132, -25, 11, 6),     # interno australiano
    (-69, -23, 2.2, 5),    # Atacama
    (-113, 37, 6, 5),      # Great Basin-Sonora
    (-69, -45, 3.5, 6),    # steppa patagonica
]
arid = np.zeros((LH, LW), float)
for clon, clat, rlon, rlat in DESERTS:
    dlon = ((LON - clon + 180) % 360) - 180
    arid = np.maximum(arid, np.exp(-((dlon / rlon) ** 2 + ((LAT - clat) / rlat) ** 2)))

# rumore a bassa frequenza: spezza le ellissi perfette dei deserti e i bordi
# troppo regolari del rilievo, senza cambiarne la posizione geografica
rng = np.random.default_rng(7)
def value_noise(shape, cells):
    g = rng.random((cells + 1, cells * 2 + 1))
    return np.array(Image.fromarray((g * 255).astype(np.uint8)).resize(
        (shape[1], shape[0]), Image.BICUBIC), dtype=float) / 255.0
n1 = value_noise((LH, LW), 14)
n2 = value_noise((LH, LW), 34)
noise = 0.65 * n1 + 0.35 * n2
arid = np.clip(arid + (noise - 0.5) * 0.42, 0, 1)
elev = np.clip(elev + (noise - 0.5) * 0.05, 0, None)

# ─── palette ipsometrica realistica ───
# mare: da acque basse (chiare) al fondale profondo
SEA = [(1, (58, 118, 168)), (3, (40, 92, 140)), (7, (26, 66, 108)), (1e9, (16, 44, 78))]
# terra: verde costiero -> prateria -> pedemontano -> roccia -> neve (solo picchi)
LAND = [(0.06, (60, 100, 60)),    # foresta costiera
        (0.16, (96, 126, 66)),    # bassopiano verde
        (0.30, (140, 150, 82)),   # prateria/savana
        (0.44, (156, 132, 84)),   # pedemontano
        (0.60, (140, 104, 62)),   # bruno
        (0.76, (120, 98, 82)),    # roccia bruno-grigia
        (0.90, (156, 146, 138)),  # alta roccia grigia
        (2.0,  (238, 242, 247))]  # neve: solo i picchi piu' alti (>0.90)
# deserti: sabbia naturale
SAND = [(0.16, (200, 180, 120)), (0.34, (188, 164, 104)), (2.0, (172, 146, 92))]
ICE, ICE_EDGE = (226, 236, 244), (188, 208, 222)

img = np.zeros((LH, LW, 3), np.uint8)
rem = ~M
for thr, col in SEA:
    sel = rem & (dist_sea <= thr); img[sel] = col; rem &= ~sel
rem = M.copy()
for thr, col in LAND:
    sel = rem & (elev <= thr); img[sel] = col; rem &= ~sel
# i deserti ritingono le quote basse; le montagne restano
dry = M & (arid > 0.45) & (elev < 0.42)
rem = dry.copy()
for thr, col in SAND:
    sel = rem & (elev <= thr); img[sel] = col; rem &= ~sel

# ghiaccio: SOLO Antartide e Groenlandia (niente fascia dritta di latitudine)
greenland = (LON > -73) & (LON < -11) & (LAT > 59) & (LAT < 85)
ice = M & ((LAT < -62) | greenland)
img[ice] = ICE
img[ice & (dist_land <= 1.5)] = ICE_EDGE
coast = M & (dist_land <= 1.0)
img[coast] = (54, 80, 58)
img[coast & dry] = (150, 128, 78)
img[coast & ice] = ICE_EDGE

# ─── HEXEL-ART: tessere esagonali colorate per isoipse, SENZA contorni ───
# Nessun bordo oro: il perimetro di ogni tessera e' dello stesso colore del
# riempimento (niente fessure fra le tessere). SUPERSAMPLING 3x + downscale
# LANCZOS -> bordi puliti e anti-aliasati, non a zig-zag.
SS = 3                  # fattore di supersampling per bordi puliti
def hexelize(small, out_w, out_h, R):
    sh, sw, _ = small.shape
    W2, H2, R2 = out_w * SS, out_h * SS, R * SS
    canvas = Image.new("RGB", (W2, H2), (11, 33, 62))  # mare profondo di fondo
    dr = ImageDraw.Draw(canvas)
    hw = math.sqrt(3) * R2; vs = 1.5 * R2
    corners = [(math.cos(math.radians(60 * k - 90)), math.sin(math.radians(60 * k - 90))) for k in range(6)]
    sx, sy = W2 / sw, H2 / sh
    row = 0
    while row * vs - R2 <= H2:
        cy = row * vs; xoff = (hw / 2) if row % 2 else 0
        col = 0
        while col * hw + xoff - hw <= W2:
            cx = col * hw + xoff
            ix = min(sw - 1, max(0, int(cx / sx))); iy = min(sh - 1, max(0, int(cy / sy)))
            c = tuple(int(v) for v in small[iy, ix])
            poly = [(cx + R2 * dx, cy + R2 * dy) for dx, dy in corners]
            dr.polygon(poly, fill=c, outline=c)   # bordo = riempimento: nessun contorno visibile
            col += 1
        row += 1
    return canvas.resize((out_w, out_h), Image.LANCZOS)         # bordi puliti

hexelize(img, W, H, 5).save(OUT)   # R=5 px: tessere piu' fini -> geografia leggibile
print("saved (hexel)", OUT, "| land px:", int(M.sum()), "| max elev:", round(float(elev.max()), 2))

# ═══ PUNTEGGI RISORSE per hexad -> data/sinecismi.json ═══════════════════
# Derivati dalla stessa geografia della mappa (elevazione, aridita', costa) piu'
# due strati fini: BACINI FLUVIALI e CORRIDOI di transumanza/migrazione endemica
# (polilinee di prossimita', come le catene montuose).
RIVERS = [
    [(30,31),(31,27),(32,24),(33,15),(32,9),(31,4)],       # Nilo
    [(-49,-1),(-58,-3),(-67,-4),(-73,-6)],                 # Rio delle Amazzoni
    [(-90,29),(-90,37),(-93,43),(-95,47)],                 # Mississippi-Missouri
    [(121,32),(114,30),(107,30),(101,29),(97,32)],         # Yangtze
    [(88,22),(84,25),(80,27),(78,30)],                     # Gange
    [(67,24),(69,27),(72,31),(75,35)],                     # Indo
    [(29,45),(24,44),(19,45),(13,48),(9,48)],              # Danubio
    [(48,46),(45,49),(45,54),(40,57),(37,57)],             # Volga
    [(12,-6),(17,-1),(24,1),(29,-2)],                      # Congo
    [(5,4),(4,8),(0,13),(-4,17),(-8,13)],                  # Niger
    [(48,30),(45,32),(42,35),(39,37)],                     # Tigri-Eufrate
    [(106,10),(105,15),(101,20),(99,25),(97,29)],          # Mekong
    [(-58,-27),(-60,-32),(-58,-34)],                       # Parana
    [(6,52),(7,50),(8,47)],                                # Reno
    [(139,-35),(144,-35),(148,-36)],                       # Murray
]
CORRIDORS = [
    [(35,36),(48,38),(63,40),(80,42),(95,41),(110,36),(118,34)],  # Via della Seta
    [(-8,32),(-2,26),(4,18),(9,14),(15,13)],                      # Trans-sahariano
    [(28,50),(45,50),(62,49),(80,48),(98,47),(112,45)],           # Steppa eurasiatica
    [(43,13),(55,16),(66,22),(73,17),(80,8),(90,10),(98,14)],     # Monsone Oceano Indiano
    [(12,54),(13,50),(13,46)],                                    # Ambra (Baltico-Adriatico)
    [(-75,2),(-73,-9),(-71,-18),(-70,-27)],                       # Verticale andina
    [(-99,19),(-92,16),(-88,17)],                                 # Mesoamericano
    [(77,29),(82,26),(86,24),(89,23)],                            # Grand Trunk (India)
    [(31,31),(35,33),(36,36)],                                    # Via del Levante
]
def line_field(polys, width):
    f = np.zeros((LH, LW), float)
    for pts in polys:
        for p1, p2 in zip(pts, pts[1:]):
            f = np.maximum(f, np.exp(-((seg_dist(LON, LAT, p1, p2)) / width) ** 2))
    return f
river_f = line_field(RIVERS, 2.2)
corridor_f = line_field(CORRIDORS, 4.5)

doc = json.load(open(REPO + r"\data\sinecismi.json", encoding="utf-8"))
arr = doc["sinecismi"]
NX = np.array([s["nx"] for s in arr]); NY = np.array([s["ny"] for s in arr])
def samp(F, nx, ny):
    x = min(LW - 1, max(0, int(nx * LW))); y = min(LH - 1, max(0, int(ny * LH)))
    return float(F[y, x])
cl = lambda v: 0.0 if v < 0 else (1.0 if v > 1 else v)
R0 = 0.05
for s in arr:
    nx, ny = s["nx"], s["ny"]
    e = samp(elev, nx, ny); a = samp(arid, nx, ny); dl = samp(dist_land, nx, ny)
    riv = samp(river_f, nx, ny); cor = samp(corridor_f, nx, ny); lat = samp(LAT, nx, ny)
    coastal = cl(1 - dl / 6.0)
    tempAgri = math.exp(-(((abs(lat) - 38) / 22.0) ** 2))   # picco temperato ~35-45°
    dx = (NX - nx) * 2; dy = (NY - ny)                        # nx scalato per l'aspetto 2:1
    deg = int(np.sum((dx * dx + dy * dy) <= R0 * R0) - 1)     # hub-ness (vicini)
    degn = cl(deg / 8.0)
    dif = 10 * cl(0.62 * e + 0.38 * coastal)                              # montagne + barriera marina
    com = 10 * cl(0.30 * coastal + 0.26 * cor + 0.20 * degn + 0.12 * riv + 0.10 * (1 - e) - 0.15 * a)
    agr = 10 * cl(tempAgri * (1 - a) * (1 - 0.6 * e) + 0.35 * riv)
    minr = 10 * cl(0.88 * e + 0.12 * cl(e * 1.3))
    s["risorse"] = {"dif": round(dif, 1), "com": round(com, 1), "agr": round(agr, 1), "min": round(minr, 1)}
json.dump(doc, open(REPO + r"\data\sinecismi.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("risorse calcolate per", len(arr), "hexad")
