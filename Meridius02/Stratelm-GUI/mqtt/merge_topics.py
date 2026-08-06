"""
merge_topics.py — gabungkan CSV dari dua topic MQTT (data mobil + data GPS)
menjadi satu CSV siap masuk clean_telemetry.py.

Logger (log.py / logQos0.py) menulis satu CSV per topic:
    falcon_current.csv  — data mobil: arus, tegangan, daya, velocity, ...
    falcon_track.csv    — data GPS: latitude, longitude, altitude, ...

Kedua stream tidak pernah sampel di milidetik yang persis sama, jadi
penggabungan dilakukan dengan pencocokan timestamp TERDEKAT (merge_asof):
setiap baris data mobil (stream utama) diberi baris GPS terdekat, selama
selisihnya <= TOLERANCE_MS. Baris GPS yang lebih jauh dari itu dibiarkan
kosong (NaN) — lebih jujur daripada memaksakan posisi yang salah.

Pakai:  python merge_topics.py          (path diatur di bawah)
        python merge_topics.py car.csv gps.csv -o merged.csv --tolerance-ms 500
"""

# ==== KONFIGURASI: atur path di sini ========================================
CAR_CSV      = r"data\race_day\attempt_01\falcon_current.csv"
GPS_CSV      = r"data\race_day\attempt_01\falcon_track.csv"
OUTPUT_CSV   = r"data\race_day\attempt_01\attempt_01_merged.csv"
TOLERANCE_MS = 1000   # pasangan GPS dianggap valid jika selisih <= 1 detik
# ============================================================================

import argparse
import os
import sys

import pandas as pd

from clean_telemetry import _find_ts_column


def load_with_ts(path, label):
    if not os.path.isfile(path):
        sys.exit(f"file tidak ditemukan ({label}): {path}")
    df = pd.read_csv(path)
    ts_name, ts_ms = _find_ts_column(df, "ts")
    if ts_name is None:
        sys.exit(f"tidak ada kolom timestamp di {label} ({path}) — "
                 "dicari ts/timestamp/recorded_at/datetime/...")
    df = df.assign(_ts_ms=pd.to_numeric(ts_ms, errors="coerce"))
    df = df.dropna(subset=["_ts_ms"]).sort_values("_ts_ms")
    print(f"{label}: {path} — {len(df)} baris, timestamp '{ts_name}'")
    return df, ts_name


def main():
    ap = argparse.ArgumentParser(description="Gabungkan CSV topic mobil + GPS")
    ap.add_argument("car", nargs="?", default=CAR_CSV, help="CSV data mobil")
    ap.add_argument("gps", nargs="?", default=GPS_CSV, help="CSV data GPS")
    ap.add_argument("-o", "--out", default=OUTPUT_CSV)
    ap.add_argument("--tolerance-ms", type=float, default=TOLERANCE_MS)
    args = ap.parse_args()

    car_ada = os.path.isfile(args.car)
    gps_ada = os.path.isfile(args.gps)
    if not car_ada and not gps_ada:
        sys.exit(f"kedua file tidak ada:\n  mobil: {args.car}\n  GPS  : {args.gps}")

    # salah satu topic offline selama sesi -> file-nya tidak pernah terbentuk.
    # Jangan gagal: teruskan stream yang ada apa adanya supaya pipeline
    # (clean_telemetry -> assign_laps -> split_laps) tetap bisa jalan.
    if not gps_ada or not car_ada:
        ada_path, label = (args.car, "mobil") if car_ada else (args.gps, "GPS")
        hilang = "GPS" if car_ada else "mobil"
        print(f"PERINGATAN: file {hilang} tidak ada — hanya data {label} yang "
              f"diteruskan tanpa penggabungan.")
        df = pd.read_csv(ada_path)
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        df.to_csv(args.out, index=False)
        print(f"ditulis: {args.out} ({len(df)} baris, hanya stream {label})")
        print("langkah berikutnya: python clean_telemetry.py " + args.out)
        return

    car, car_ts = load_with_ts(args.car, "mobil")
    gps, gps_ts = load_with_ts(args.gps, "GPS")

    # kolom yang namanya sama di kedua file: pakai versi mobil, buang punya GPS
    # (kecuali kolom timestampnya sendiri, yang memang tidak dibawa)
    dup = [c for c in gps.columns
           if c in car.columns and c not in ("_ts_ms",)]
    if dup:
        print(f"kolom duplikat di kedua file (dipakai versi mobil): {dup}")
    gps_take = gps.drop(columns=dup)

    merged = pd.merge_asof(car, gps_take, on="_ts_ms",
                           direction="nearest",
                           tolerance=args.tolerance_ms)

    gps_cols = [c for c in gps_take.columns if c != "_ts_ms"]
    matched = merged[gps_cols].notna().any(axis=1).sum() if gps_cols else 0
    print(f"\nhasil: {len(merged)} baris (basis stream mobil)")
    print(f"baris dengan pasangan GPS <= {args.tolerance_ms:.0f} ms: "
          f"{matched} ({matched / max(len(merged), 1):.0%})")
    if gps_cols and matched < len(merged) * 0.5:
        print("PERINGATAN: kurang dari separuh baris dapat pasangan GPS — "
              "cek apakah kedua logger jalan bersamaan / toleransi terlalu ketat")

    merged = merged.drop(columns=["_ts_ms"])
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    merged.to_csv(args.out, index=False)
    print(f"\nditulis: {args.out}")
    print("langkah berikutnya: python clean_telemetry.py " + args.out)


if __name__ == "__main__":
    main()
