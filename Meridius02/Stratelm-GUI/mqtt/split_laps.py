"""
split_laps.py — pecah CSV cleaned+lapped menjadi satu CSV per lap, dengan
kolom wajib permintaan divisi riset dijamin ada di setiap file.

Kolom wajib (ditambahkan/dihitung jika logger tidak merekamnya):
  1. arus_A                — currentBattery/arus asli; jika tidak ada
                             diestimasi dari konsumsi_realtime_W / vinBattery
  2. kecepatan_kmh         — velocity/speed asli
  3. mode_gas_glide        — 'gas'/'glide' per baris (dari `mode` jika ada,
                             jika tidak dari ambang arus); plus gas_pct &
                             glide_pct (persentase untuk lap itu, konstan)
  4. konsumsi_realtime_W   — daya real-time, dipilih dari cascade prioritas:
                             powerW asli → vinBattery×currentBattery → dEnergyWh/dt →
                             velocity/kmPerkWh (proksi) → NaN
  5. waktu_lap_s           — detik sejak awal lap (per baris); plus
                             durasi_lap_s (durasi total lap itu, konstan)
  6. efisiensi_km_per_kWh  — efisiensi lap itu (konstan): dari energyWh jika
                             ada (terukur), jika tidak rata-rata kmPerkWh

Semua kolom asli lainnya DIPERTAHANKAN apa adanya. Kolom `sumber_data`
terakhir mencatat mana yang terukur langsung vs estimasi.

Pakai:  python split_laps.py            (path diatur di bawah)
        python split_laps.py input.csv --out folder/   (override via CLI)
"""

# ==== KONFIGURASI: atur path di sini ========================================
INPUT_CSV  = "data/race_day/exampleAttempt/example_attempt_cleaned_laps.csv"
OUTPUT_DIR = "data/race_day/exampleAttempt/laps_split"
# ============================================================================

import argparse
import os
import re
import sys

import numpy as np
import pandas as pd


def norm(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def find_col(df, *names):
    lookup = {norm(c): c for c in df.columns}
    for n in names:
        if norm(n) in lookup:
            return lookup[norm(n)]
    return None


def main():
    ap = argparse.ArgumentParser(description="Split cleaned+lapped CSV per lap")
    ap.add_argument("csv", nargs="?", default=INPUT_CSV)
    ap.add_argument("--out", default=OUTPUT_DIR)
    args = ap.parse_args()

    if not os.path.isfile(args.csv):
        sys.exit(f"file tidak ditemukan: {args.csv}")
    df = pd.read_csv(args.csv)

    def usable(c):
        """Kolom dianggap terekam hanya jika punya sinyal sungguhan.
        MCU asli mengirim PowerW/EnergiWh/kmPerkWh = 0 semua saat kalkulasi
        onboard belum jalan — kolom seperti itu diperlakukan tidak ada supaya
        cascade jatuh ke sumber yang benar (mis. V x I)."""
        if c is None:
            return None
        s = pd.to_numeric(df[c], errors="coerce")
        if s.notna().any() and s.nunique(dropna=True) > 1:
            return c
        print(f"catatan: kolom '{c}' ada tapi konstan/nol semua — "
              f"dianggap tidak direkam")
        return None

    LAP  = find_col(df, "lap_number", "lap")
    VEL  = usable(find_col(df, "velocity", "speed", "kecepatan"))
    MODE = find_col(df, "mode")
    VIN  = usable(find_col(df, "vinBattery", "vinFC", "voltage",
                           "battVoltage", "batteryVoltage"))
    CUR  = usable(find_col(df, "currentBattery", "currentM", "arusM",
                           "current", "motorCurrent"))
    PWR  = usable(find_col(df, "powerW", "power", "daya"))
    EN   = usable(find_col(df, "energyWh", "energiWh", "energy"))
    DIST = usable(find_col(df, "distance", "cumdistkm", "odometer"))
    EFF  = usable(find_col(df, "kmPerkWh", "efficiency"))
    ELAP = find_col(df, "elapsed_s", "timeS", "elapsed")

    if LAP is None:
        sys.exit("tidak ada kolom lap_number — jalankan assign_laps.py dulu")
    if ELAP is None:
        sys.exit("tidak ada kolom waktu (elapsed_s/timeS) — perlu untuk "
                 "waktu_lap_s dan integral jarak")

    laps = df.dropna(subset=[LAP]).copy()
    laps[LAP] = laps[LAP].astype(int)
    sumber = {}   # catatan: kolom wajib -> terukur / estimasi

    # ---- 2. kecepatan -------------------------------------------------------
    if VEL:
        laps["kecepatan_kmh"] = pd.to_numeric(laps[VEL], errors="coerce")
        sumber["kecepatan_kmh"] = f"terukur ({VEL})"
    else:
        laps["kecepatan_kmh"] = np.nan
        sumber["kecepatan_kmh"] = "TIDAK ADA — logger tidak merekam kecepatan"

    # ---- 4. konsumsi real-time (cascade prioritas, satuan Watt) -------------
    if PWR:
        laps["konsumsi_realtime_W"] = pd.to_numeric(laps[PWR], errors="coerce")
        sumber["konsumsi_realtime_W"] = f"terukur ({PWR}, Watt langsung dari logger)"
    elif VIN and CUR:
        laps["konsumsi_realtime_W"] = (pd.to_numeric(laps[VIN], errors="coerce")
                                       * pd.to_numeric(laps[CUR], errors="coerce"))
        sumber["konsumsi_realtime_W"] = f"dihitung ({VIN} x {CUR}, P = V x I)"
    elif EN:
        tmp = laps.sort_values([LAP, ELAP])
        dE = tmp.groupby(LAP)[EN].diff()
        dt_h = tmp.groupby(LAP)[ELAP].diff().clip(lower=1e-6) / 3600.0
        p = (dE / dt_h).rolling(5, min_periods=1).mean()
        laps.loc[tmp.index, "konsumsi_realtime_W"] = p
        sumber["konsumsi_realtime_W"] = (f"estimasi (d{EN}/dt dihaluskan rolling 5 — "
                                         "PROKSI, bukan pengukuran langsung)")
    elif EFF and VEL:
        eff = pd.to_numeric(laps[EFF], errors="coerce")
        laps["konsumsi_realtime_W"] = laps["kecepatan_kmh"] / eff * 1000.0
        sumber["konsumsi_realtime_W"] = (f"estimasi ({VEL} / {EFF} x 1000, "
                                         "P = v/efisiensi — PROKSI dari efisiensi "
                                         "instan, bukan pengukuran arus/tegangan)")
    else:
        laps["konsumsi_realtime_W"] = np.nan
        sumber["konsumsi_realtime_W"] = ("TIDAK ADA — tidak ada powerW, V+I, "
                                         "energyWh, maupun kmPerkWh untuk dihitung")

    # ---- 1. arus ------------------------------------------------------------
    if CUR:
        laps["arus_A"] = pd.to_numeric(laps[CUR], errors="coerce")
        sumber["arus_A"] = f"terukur ({CUR})"
    elif VIN and laps["konsumsi_realtime_W"].notna().any():
        laps["arus_A"] = (laps["konsumsi_realtime_W"]
                          / pd.to_numeric(laps[VIN], errors="coerce"))
        sumber["arus_A"] = (f"estimasi (konsumsi_realtime_W / {VIN}, I = P/V — "
                            "ikut sifat estimasi kolom konsumsinya)")
    else:
        laps["arus_A"] = np.nan
        sumber["arus_A"] = "TIDAK ADA — tidak ada kolom arus maupun tegangan+daya"

    # ---- 3. gas/glide -------------------------------------------------------
    if MODE:
        m = laps[MODE].astype(str).str.lower()
        burn = m.eq("gas")
        laps["mode_gas_glide"] = np.where(burn, "gas", "glide")
        sumber["mode_gas_glide"] = f"terukur ({MODE})"
    elif CUR:
        cur = pd.to_numeric(laps[CUR], errors="coerce")
        burn = cur > max(1.0, float(cur.median()))
        laps["mode_gas_glide"] = np.where(burn, "gas", "glide")
        sumber["mode_gas_glide"] = (f"estimasi (ambang arus: {CUR} > "
                                    f"max(1.0, median))")
    else:
        burn = None
        laps["mode_gas_glide"] = np.nan
        sumber["mode_gas_glide"] = "TIDAK ADA — tidak ada mode maupun arus"

    # ---- per-lap konstanta: waktu, gas%, efisiensi --------------------------
    t = pd.to_numeric(laps[ELAP], errors="coerce")
    laps["waktu_lap_s"] = (t - t.groupby(laps[LAP]).transform("min")).round(2)
    laps["durasi_lap_s"] = t.groupby(laps[LAP]).transform(
        lambda s: round(float(s.max() - s.min()), 1))
    sumber["waktu_lap_s"] = f"dihitung ({ELAP} di-nol-kan ke awal lap)"

    if burn is not None:
        gas_pct = burn.groupby(laps[LAP]).transform("mean") * 100
        laps["gas_pct"] = gas_pct.round(1)
        laps["glide_pct"] = (100 - gas_pct).round(1)

    # jarak per lap (untuk efisiensi): kolom jarak kumulatif atau integral v dt
    dist_integral = None
    if VEL:
        dt = t.groupby(laps[LAP]).diff().clip(lower=0, upper=2).fillna(0)
        seg = laps["kecepatan_kmh"] / 3.6 * dt / 1000.0
        dist_integral = seg.groupby(laps[LAP]).transform("sum")

    if DIST:
        d = pd.to_numeric(laps[DIST], errors="coerce")
        dist_km = d.groupby(laps[LAP]).transform(lambda s: s.max() - s.min())
        unit = "km"
        # deteksi satuan: kalau integral kecepatan tersedia, pilih km vs meter
        # berdasarkan mana yang cocok dengan jarak hasil integral
        if dist_integral is not None and dist_integral.iloc[0] > 0:
            ratio = float((dist_km / dist_integral).median())
            if ratio > 100:            # nilainya ~1000x integral -> pasti meter
                dist_km = dist_km / 1000.0
                unit = "meter (dikonversi ke km)"
        dist_note = f"terukur ({DIST}, satuan terdeteksi: {unit})"
    elif dist_integral is not None:
        dist_km = dist_integral
        dist_note = "estimasi (integral kecepatan terhadap waktu)"
    else:
        dist_km = None
        dist_note = "TIDAK ADA"

    # energi per lap dari integral daya (Wh = sum P dt / 3600) — hanya sah
    # kalau konsumsinya kelas Watt terukur (powerW asli atau V x I), bukan
    # proksi dari kmPerkWh (itu sirkular)
    konsumsi_watt_terukur = (PWR is not None) or (VIN is not None and CUR is not None)

    if EN and dist_km is not None:
        e = pd.to_numeric(laps[EN], errors="coerce")
        en_lap = e.groupby(laps[LAP]).transform(lambda s: s.max() - s.min())
        laps["efisiensi_km_per_kWh"] = (dist_km / (en_lap / 1000.0)).round(1)
        sumber["efisiensi_km_per_kWh"] = (f"terukur (jarak {dist_note} / "
                                          f"energi {EN} lap itu)")
    elif konsumsi_watt_terukur and dist_km is not None:
        dt = t.groupby(laps[LAP]).diff().clip(lower=0, upper=2).fillna(0)
        wh = (laps["konsumsi_realtime_W"] * dt / 3600.0)
        en_lap = wh.groupby(laps[LAP]).transform("sum")
        laps["efisiensi_km_per_kWh"] = (dist_km / (en_lap / 1000.0)).round(1)
        sumber["efisiensi_km_per_kWh"] = ("dihitung (jarak / integral "
                                          "konsumsi_realtime_W terhadap waktu — "
                                          "dari daya terukur, bukan kolom energi "
                                          "langsung)")
    elif EFF:
        eff = pd.to_numeric(laps[EFF], errors="coerce")
        laps["efisiensi_km_per_kWh"] = eff.groupby(laps[LAP]).transform("mean").round(1)
        sumber["efisiensi_km_per_kWh"] = (f"estimasi (rata-rata {EFF} tercatat "
                                          "di lap itu, bukan dari energi terukur)")
    else:
        laps["efisiensi_km_per_kWh"] = np.nan
        sumber["efisiensi_km_per_kWh"] = "TIDAK ADA — tidak ada energyWh maupun kmPerkWh"

    # ---- tulis satu CSV per lap ---------------------------------------------
    os.makedirs(args.out, exist_ok=True)
    print(f"input : {args.csv} ({len(laps)} baris dalam race)")
    print(f"output: {args.out}/")
    print("\nsumber kolom wajib:")
    for k, v in sumber.items():
        print(f"  - {k}: {v}")
    print()

    for lp in sorted(laps[LAP].unique()):
        g = laps[laps[LAP] == lp]
        path = os.path.join(args.out, f"lap_{lp:02d}.csv")
        g.to_csv(path, index=False)
        print(f"  lap {lp}: {len(g)} baris, {g['durasi_lap_s'].iloc[0]:.0f} s, "
              f"efisiensi {g['efisiensi_km_per_kWh'].iloc[0]:.1f} km/kWh "
              f"-> {path}")

    # catatan sumber ikut disimpan supaya CSV bisa dibaca tanpa lihat konsol
    notes = pd.Series(sumber, name="sumber").rename_axis("kolom_wajib")
    notes.to_csv(os.path.join(args.out, "kolom_wajib_sumber.csv"))
    print(f"\ncatatan sumber kolom: {os.path.join(args.out, 'kolom_wajib_sumber.csv')}")


if __name__ == "__main__":
    main()
