# MPC Strategy Controller

**Status:** DESIGN / TODO — Ini adalah source-of-truth brief untuk implementasi
**Model Predictive Control (MPC) yang bersifat Predictive + Adaptive + Driver-Aware**
untuk SEM Hydrogen digital twin. Dokumen ini adalah **petunjuk untuk agent/developer**,
bukan hasil simulasi. Agent wajib membaca ini sebelum menyentuh kode.

**Dibuat:** 2026-07-20 (Rev 1 → Rev 2 dengan data EP, driver-awareness, dan GA tuning)

---

## 0. Jawaban Pertanyaan Utama: Apakah GA Diperlukan?

**YA — GA tetap diperlukan, tapi perannya berubah.** Arsitektur yang benar adalah:

```
┌─────────────────────────────────────────────────────────────────┐
│  OUTER LOOP — GA (offline, optimize_ga.py)                      │
│  Mencari hyperparameter MPC terbaik (bobot Q/R, horizon N)      │
│  Fitness = hasil run_closed_loop() lengkap (Art. 54e score)     │
└──────────────────────────┬──────────────────────────────────────┘
                           │ theta (hyperparams)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  INNER LOOP — MPC (online, mpc.py)                              │
│  Di setiap step track, melihat horizon N ke depan               │
│  + membaca driver-movement state + parameter EP                 │
│  → menghasilkan v_cmd optimal step demi step                    │
└─────────────────────────────────────────────────────────────────┘
```

**Kenapa GA masih perlu:**
GA tidak lagi mencari `v_target/v_coast` langsung per segmen (open-loop).
GA sekarang men-tune **bobot MPC** (Q_time, Q_h2, R_du) dan **panjang horizon N**
sehingga MPC yang greedy-lokal menghasilkan perilaku global yang mendekati optimal.
Tanpa GA, bobot MPC harus di-set manual (sulit). Dengan GA, bobot otomatis ditemukan.

---

## 1. Tujuan Sistem

Membangun controller MPC yang **menggantikan logika gas/glide fixed-per-segment**
(di `simulate.py` baris ~119-135) dengan **receding-horizon optimal control** yang:

1. **Predictive** — melihat N langkah ke depan (elevasi, tikungan, stop-event,
   hambatan aerodinamik dan rolling) sebelum memutuskan kecepatan target.
2. **Adaptive** — parameter model prediksi diperbarui dari:
   - Estimasi komponen divisi Electrical & Powertrain (EP) — tabel parameter di §2
   - Data lingkungan aktual (cuaca, angin, suhu) via `weather.py`
   - Deviasi state aktual vs prediksi (online estimation opsional — §5)
3. **Driver-Aware** — MPC membaca sinyal movement driver (akselerasi aktual,
   pola gas/rem, deviasi dari profil nominal) dan menyesuaikan setpoint secara
   real-time tanpa ubah kode controller (§6).

---

## 2. Parameter Komponen dari Divisi Electrical & Powertrain (EP)

Semua nilai ini sudah tersimpan di `config.py` dan `data/`. **Agent WAJIB
membaca dari sana — JANGAN hardcode ulang di `mpc.py`.**

### 2.1 Parameter Massa & Geometri

| Parameter          | Simbol      | Nilai EP         | Unit  | Sumber di Repo                   | Catatan                                             |
| ------------------ | ----------- | ---------------- | ----- | -------------------------------- | --------------------------------------------------- |
| Vehicle Mass       | `m_vehicle` | 85               | kg    | `config.MASS_VEHICLE_KG` (= 88)  | EP: 85, repo: 88 — JANGAN ubah tanpa konfirmasi tim |
| Driver Mass        | `m_driver`  | 70               | kg    | `config.MASS_DRIVER_KG`          | SEM Regulation floor                                |
| Total Mass         | `m`         | 155→158          | kg    | `config.MASS_TOTAL_KG`           | EP: 155, repo: 158 (88+70)                          |
| Air Density        | `rho`       | 1.225            | kg/m3 | `config.AIR_DENSITY_STD_KG_M3`   | Pakai `weather.air_density()` di runtime            |
| Drag Coefficient   | `Cd`        | 0.1 (legacy)     | —     | `config.AERO_CD_LEGACY_ESTIMATE` | SUPERSEDED oleh CFD — pakai `AERO_CDA_CFD`          |
| Vehicle Width      | `W`         | 1.22             | m     | `config.VEHICLE_WIDTH_M`         |                                                     |
| Vehicle Height     | `H`         | 1.05             | m     | `config.VEHICLE_HEIGHT_M`        |                                                     |
| Shape Factor       | `k`         | 0.6 (legacy)     | —     | Superseded, real k=0.40 dari CFD |                                                     |
| Frontal Area       | `A`         | 0.77 m2 (legacy) | m2    | `config.FRONTAL_AREA_LEGACY_M2`  | Pakai CFD: `AERO_FRONTAL_AREA_CFD_M2 = 0.509`       |
| Rolling Resistance | `Crr`       | 0.004            | —     | `config.CRR`                     | PLACEHOLDER — update bila ada coast-down test       |
| Wheel Diameter     | `D`         | 16               | inch  | `config.WHEEL_DIAMETER_IN`       |                                                     |
| Wheel Radius       | `r`         | 0.203            | m     | `config.WHEEL_RADIUS_M`          |                                                     |

### 2.2 Parameter Kinematik & Gaya (Dipakai di Prediction Model)

| Parameter                | Simbol   | Formula         | Nilai EP                           | Sumber di Repo                            | Fungsi yang Memakainya        |
| ------------------------ | -------- | --------------- | ---------------------------------- | ----------------------------------------- | ----------------------------- |
| Cruise Speed             | `v`      | —               | 30 km/h = 8.33 m/s                 | `config.V_TARGET_AVG_KMH_CRUISE`          | MPC horizon rollout           |
| Aero Drag Force          | `Fd`     | 0.5·rho·Cd·A·v2 | 3.27 N                             | `vehicle.drag_force_n()`                  | Cost function tiap step       |
| Rolling Resistance Force | `Fr`     | Crr·m·g         | 6.08 N                             | `vehicle.rolling_resistance_n()`          | Cost function tiap step       |
| Total Resistance         | `Fres`   | Fd + Fr         | 9.35 N                             | `vehicle.resistance_force_n()`            | MPC rollout                   |
| Cruise Mechanical Power  | `Pmech`  | F·v             | 77.9 W                             | Dihitung di `simulate.py`                 | Validasi prediction model     |
| Drivetrain Efficiency    | `eta`    | —               | 92% (EP), 80% (repo, CONSERVATIVE) | `config.DRIVETRAIN_EFFICIENCY_ASSUMED`    | GUNAKAN 80% sampai ukur ulang |
| Cruise Electrical Power  | `Pelec`  | Pmech/eta       | 84.7 W (EP) / 97.4 W (repo)        | Dihitung via `motor.electrical_power_w()` |                               |
| Target Acceleration      | `a`      | Delta_v/t       | 0.833 m/s2                         | `config.ACCEL_MAX_MS2`                    | Hard constraint MPC           |
| Acceleration Force       | `Facc`   | m·a             | 129.1 N                            | Dihitung di tiap step                     | MPC cost + constraint         |
| Total Force (accel)      | `Ftotal` | Facc+Fd+Fr      | 138.45 N                           | Dihitung di tiap step                     | Torque prediction             |
| Required Wheel Torque    | `T`      | F·r             | 28.1 Nm                            | `config.WHEEL_RADIUS_M`                   | Peak power validation         |
| Peak Mechanical Power    | `Ppeak`  | F·v             | 1.15 kW                            | Dipakai sbg batas clip motor              | `motor.electrical_power_w()`  |

> **Catatan Agent:** Nilai EP adalah estimasi awal dari divisi Electrical & Powertrain.
> Nilai di `config.py` adalah yang sudah divalidasi/dikoreksi tim.
> SELALU gunakan `config.py` sebagai ground truth, bukan tabel di atas langsung.

---

## 3. Formulasi MPC Lengkap

### 3.1 State & Control

**State** `x_i` di langkah track ke-`i`:

```
x_i = {
    v_ms:     kecepatan aktual (m/s)
    soc_wh:   SOC buffer (Wh) — dari BufferModel, aktifkan di MPC
    s_m:      posisi di lintasan (implicit dari index i)
    v_driver: kecepatan yang sedang dijalankan driver (m/s) — lihat §6
}
```

**Control** `u_i` — Gunakan Opsi A (rekomendasi):

```
u_i = v_cmd (m/s)
    Clip ke [V_MIN, V_MAX] dan v_ceiling_kmh[i] / 3.6
    Interpretasi: v_cmd > v_ms → gas; v_cmd < v_ms → coast/glide
```

### 3.2 Prediction Model (Horizon Rollout)

Untuk setiap kandidat `v_cmd` selama rollout horizon `[i, i+N)`:

```python
# WAJIB pakai fungsi yang sudah ada — JANGAN tulis fisika baru
f_res     = vehicle.resistance_force_n(v_kmh, grade_pct[k], scenario,
                                       heading_deg[k], r_min_m=r_min_m[k])
f_traction = MASS_TOTAL_KG * a_applied + f_res
p_wheel    = max(0.0, f_traction) * v_ms
p_motor    = p_wheel / DRIVETRAIN_EFFICIENCY_ASSUMED
p_elec, _  = motor.electrical_power_w(p_motor)
p_fc       = p_elec / POWERTRAIN_BUFFER_EFFICIENCY_ASSUMED + FC_PARASITIC_LOAD_W
dH2        = fc.h2_volume_flow_m3_s(p_fc) * dt
```

Semua fungsi ada di `vehicle.py` dan `powertrain.py`. TIDAK PERLU menulis ulang.

### 3.3 Cost Function

```
J(u_{i:i+N}) = Σ_{k=i}^{i+N-1} [
    w_h2    * dH2_k                          # minimize H2 (tujuan utama)
  + w_time  * dt_k                           # penalti waktu
  + w_track * max(0, v_k - v_ceiling_k)^2   # deviasi dari batas aman
  + w_du    * (u_k - u_{k-1})^2             # smoothness
  + w_drv   * driver_deviation_penalty_k    # deviasi dari sinyal driver (§6)
]
```

**Bobot `{w_h2, w_time, w_track, w_du, w_drv}` = `theta` yang di-tuning GA.**

### 3.4 Hard Constraints

```
v_i <= v_ceiling_kmh[i] / 3.6          # kecepatan aman
-BRAKE_MAX_MS2 <= a_i <= ACCEL_MAX_MS2 # batas akselerasi/deselerasi
SOC_MIN <= soc_wh <= SOC_MAX           # batas SOC buffer
stop_event[i] → v_cmd = 0             # hard stop pada stop_event
```

### 3.5 Solver Horizon

**Mulai dengan Grid Enumeration (rekomendasi, tanpa dependency baru):**

```python
# Kandidat v_cmd: 10-15 nilai terdistribusi
v_candidates = np.linspace(v_min_safe, v_ceiling[i], N_CANDIDATES)

best_J   = np.inf
best_cmd = v_candidates[0]
for v_cmd in v_candidates:
    J = rollout_cost(state, i, v_cmd, horizon_n, theta, full_track, ...)
    if J < best_J:
        best_J   = J
        best_cmd = v_cmd
return best_cmd
```

Jika kelak kontrol multi-dimensional, pertimbangkan `scipy.optimize.minimize`.
Jangan tambah dependency berat sekarang.

---

## 4. Adaptive Component — Koneksi ke Estimasi EP

### 4.1 Static Re-parameterization (WAJIB, Level 1)

MPC **menerima semua parameter sebagai argumen**, bukan konstanta lokal:

```python
class MPCController:
    def __init__(self, full_track, scenario, motor, fc,
                 horizon_n, weights, v_bounds,
                 crr=config.CRR,
                 drivetrain_eff=config.DRIVETRAIN_EFFICIENCY_ASSUMED,
                 buffer=None, adaptive=False):
```

Ketika EP memperbarui nilai (CRR, kurva FC baru, efisiensi drivetrain terukur),
**cukup ganti argumen** saat memanggil `MPCController(...)` — tidak perlu
sentuh logika controller.

**Sumber parameter EP yang perlu di-inject:**

- `config.CRR` → rolling resistance
- `config.DRIVETRAIN_EFFICIENCY_ASSUMED` → efisiensi drivetrain
- `config.AERO_CDA_CFD[config.AERO_BODY_GEOMETRY]` → drag area per speed
- `data/motor_candidates.csv` → kurva efisiensi motor (`MotorModel`)
- `data/fc_candidates.csv` → kurva efisiensi FC (`FuelCellModel`)
- `config.BUFFER_*` → kapasitas & efisiensi buffer

### 4.2 Online Estimation (OPSIONAL, Level 2)

Jika diaktifkan (`adaptive=True`):

```python
def update_estimates(self, actual_state: dict, i: int):
    """
    Koreksi ringan berdasarkan deviasi state aktual vs prediksi.

    Contoh koreksi:
    - CRR_eff: sesuaikan dari selisih (v_prediksi - v_aktual) / gaya prediksi
    - bias aero: koreksi dari selisih momentum di ruas datar (grade ≈ 0)
    - SOC tracking: sinkron BufferModel dari SOC sensor onboard
    """
    # PLACEHOLDER — implementasi bila sensor onboard tersedia
    pass
```

Tandai semua bagian yang belum ada data: `# PLACEHOLDER — online estimation`

---

## 5. Data Lingkungan — Integrasi dengan Weather

MPC harus menerima `scenario: WeatherScenario` dan mem-pass-nya ke semua
fungsi fisika (sudah ada di `weather.py`):

```python
# Saat rollout horizon — JANGAN hardcode rho = 1.225
f_drag = vehicle.drag_force_n(v_kmh, scenario, heading_deg[k])
rho    = weather.air_density(scenario)  # termasuk koreksi suhu & ketinggian
```

**Parameter lingkungan yang memengaruhi MPC:**

| Variabel             | Efek pada MPC                   | Cara pakai                            |
| -------------------- | ------------------------------- | ------------------------------------- |
| Suhu udara `T_air`   | Mengubah rho → Fd               | `weather.air_density(scenario)`       |
| Angin `(speed, dir)` | Mengubah relative airspeed → Fd | `weather.relative_airspeed_kmh()`     |
| Kelembapan           | Minor effect pada rho           | Sudah di `WeatherScenario`            |
| Elevasi lintasan     | Mengubah grade force            | `full_track["grade_pct"]` (sudah ada) |

**Scenario yang tersedia:** `weather.SCENARIOS` — default: `"typical_january"`.
GA outer loop bisa sweep beberapa scenario untuk robustness.

---

## 6. Driver-Awareness — Komponen Adaptif Utama (BARU di Rev 2)

### 6.1 Apa itu "Driver Movement"?

Dalam konteks SEM, "driver movement" adalah perilaku aktual driver yang
**menyimpang dari setpoint MPC ideal**, misalnya:

- Driver menginjak gas lebih dalam → akselerasi lebih besar dari `v_cmd`
- Driver rem lebih awal di tikungan → v aktual < v_cmd sebelum stop
- Driver lelah → respons lambat, velocity tracking error meningkat

MPC yang driver-aware membaca deviasi ini dan **menyesuaikan horizon
berikutnya** tanpa membiarkan error terakumulasi.

### 6.2 Driver State yang Dibutuhkan

```python
driver_state = {
    "v_actual_ms":          float,  # kecepatan aktual yang driver jalankan
    "a_actual_ms2":         float,  # akselerasi aktual (dari differensial v)
    "throttle_pct":         float,  # 0-100 (sensor, atau estimasi dari a_actual)
    "brake_pct":            float,  # 0-100 (sensor, atau estimasi dari a_actual)
    "deviation_ms":         float,  # v_actual - v_cmd (positif = driver > setpoint)
    "deviation_cumsum_ms":  float   # integral error (untuk deteksi systematic bias)
}
```

> **Catatan Agent:** Jika sensor throttle/brake tidak tersedia, estimasi dari akselerasi:
>
> - `a_actual > 0` → throttle = `a_actual / ACCEL_MAX_MS2 * 100`
> - `a_actual < 0` → brake = `abs(a_actual) / BRAKE_MAX_MS2 * 100`
>   Tandai: `# ESTIMATED FROM ACCELERATION — replace with sensor data when available`

### 6.3 Driver Adaptation Logic

```python
def solve_step(self, state, driver_state, i):
    """
    Tiga mode adaptasi berdasarkan driver movement:

    MODE 1 — TRACKING: |deviation| < THRESHOLD_MS
        MPC jalan normal, v_cmd = output optimizer horizon

    MODE 2 — CORRECTION: |deviation| >= THRESHOLD_MS (sementara)
        v_cmd_corrected = v_cmd + ALPHA_CORRECTION * deviation
        ALPHA_CORRECTION di-tune oleh GA sebagai bagian theta

    MODE 3 — BIAS DETECTION: |cumsum_deviation| > BIAS_THRESHOLD
        Driver punya systematic bias (mis. selalu lebih lambat 2 km/h)
        Update v_bounds MPC untuk horizon berikutnya
        Log warning ke telemetry untuk analisis pasca-run
    """
```

**Penalty driver deviation dalam cost function:**

```
w_drv * (v_cmd_k - v_actual_k)^2
```

`w_drv` adalah bagian dari `theta` yang di-tune GA.

### 6.4 Kolom Telemetry Tambahan

Tambahkan ke output `run_closed_loop()`:

```python
out["v_cmd_mpc"]           = ...  # setpoint MPC sebelum koreksi driver
out["v_cmd_corrected"]     = ...  # setpoint setelah koreksi driver
out["driver_deviation"]    = ...  # v_actual - v_cmd
out["mpc_mode"]            = ...  # "tracking" / "correction" / "bias_detected"
out["driver_throttle_pct"] = ...
out["driver_brake_pct"]    = ...
```

---

## 7. GA sebagai Outer Loop Tuner

### 7.1 Decision Variables GA (`theta`)

| Variabel          | Bound Bawah | Bound Atas | Unit  | Keterangan                  |
| ----------------- | ----------- | ---------- | ----- | --------------------------- |
| `horizon_n`       | 10          | 100        | steps | 1 step ≈ 1 meter track      |
| `w_h2`            | 0.1         | 10.0       | —     | Prioritas hemat H2          |
| `w_time`          | 0.0         | 5.0        | —     | Penalti makan waktu         |
| `w_track`         | 0.0         | 20.0       | —     | Penalti lewat v_ceiling     |
| `w_du`            | 0.0         | 5.0        | —     | Anti-chatter                |
| `w_drv`           | 0.0         | 5.0        | —     | Seberapa ketat ikuti driver |
| `alpha_drv`       | 0.0         | 1.0        | —     | Gain koreksi deviasi driver |
| `soc_target_frac` | `SOC_MIN`   | `SOC_MAX`  | frac  | Target SOC buffer           |
| `v_min_kmh`       | 15.0        | 25.0       | km/h  | Floor kecepatan MPC         |
| `v_max_kmh`       | 25.0        | 45.0       | km/h  | Ceiling kecepatan MPC       |

**JANGAN** menghapus `GasGlideProblem` lama. Buat class baru di `optimize_ga.py`:

```python
class MPCHyperparamProblem(ElementwiseProblem):
    def _evaluate(self, x, out, *args, **kwargs):
        theta = dict(zip(THETA_KEYS, x))
        telemetry = mpc_mod.run_closed_loop(full_track, scenario, motor, fc, theta)
        out["F"] = ...  # Art. 54e net H2
        out["G"] = ...  # time constraint violation
```

### 7.2 Entry Point Baru di `optimize_ga.py`

```python
# optimize_ga.py — tambahkan, JANGAN timpa GasGlideProblem
def optimize_mpc_hyperparams(scenario_name="typical_january",
                              motor_name=config.DEFAULT_MOTOR_NAME,
                              fc_name=config.DEFAULT_FC_NAME,
                              pop_size=30, n_gen=50):
    """Outer loop GA: cari theta MPC terbaik."""
    ...
```

---

## 8. File yang Dibuat / Diubah

| File                               | Aksi               | Yang Harus Dilakukan Agent                                                                               |
| ---------------------------------- | ------------------ | -------------------------------------------------------------------------------------------------------- |
| `digital_twin/mpc.py`              | **BUAT BARU**      | `MPCController` class + `run_closed_loop()` — inti semua logika MPC                                      |
| `digital_twin/simulate.py`         | **REFACTOR KECIL** | Ekstrak isi loop jadi `step()` pure function. Jaga `simulate()` tetap jalan.                             |
| `digital_twin/optimize_ga.py`      | **TAMBAH**         | `MPCHyperparamProblem` + `optimize_mpc_hyperparams()`. JANGAN hapus `GasGlideProblem`.                   |
| `digital_twin/optimize_pso.py`     | **TAMBAH**         | Sama seperti GA, versi PSO.                                                                              |
| `digital_twin/config.py`           | **TAMBAH**         | Blok `# --- MPC ---`: default theta, THRESHOLD_MS, BIAS_THRESHOLD, ALPHA_CORRECTION. Tandai PLACEHOLDER. |
| `data/mpc_segment_targets.csv`     | output             | Konsisten dengan `ga_segment_targets.csv`                                                                |
| `data/simulated_telemetry_mpc.csv` | output             | Konsisten dengan `simulated_telemetry_ga.csv`                                                            |

---

## 9. Refactor `simulate.py` yang Dibutuhkan

### 9.1 Signature `step()` yang Dibutuhkan

```python
# digital_twin/simulate.py — TAMBAH fungsi ini
def step(state: dict, i: int, ds: float, track_arrays: dict,
         scenario: WeatherScenario, motor: MotorModel,
         fc: FuelCellModel, a_applied: float) -> dict:
    """
    Pure function — satu langkah integrasi fisika. NO side-effects.

    Args:
        state:        {"v_ms": float, "soc_wh": float, "t_s": float, ...}
        i:            index titik lintasan saat ini
        ds:           jarak ke titik berikutnya (m)
        track_arrays: dict semua kolom track (grade_pct, heading_deg, dll)
        a_applied:    akselerasi yang diputuskan controller (m/s^2)

    Returns:
        {
            "v_next_ms":      float,
            "dt_s":           float,
            "dh2_m3":         float,
            "dsoc_wh":        float,
            "p_wheel_w":      float,
            "p_motor_elec_w": float,
            "p_fc_elec_w":    float,
            "f_traction_n":   float,
            "rule_violation": bool,
        }
    """
```

### 9.2 Cara `simulate()` Diperbaiki

```python
def simulate(...) -> pd.DataFrame:
    for i in range(n - 1):
        # Hitung a_applied (sama seperti sekarang)
        ...
        # PANGGIL step() — jangan duplikasi fisika
        result = step(state, i, ds, track_arrays, scenario, motor, fc, a_applied)
        v_ms[i+1] = result["v_next_ms"]
        ...
```

**Verifikasi wajib:** setelah refactor, output `simulate()` harus identik
dengan sebelum refactor. Bandingkan dengan `np.testing.assert_allclose`.

---

## 10. Interface yang Diharapkan — Signature Lengkap

```python
# digital_twin/mpc.py

class MPCController:
    def __init__(self,
                 full_track:      pd.DataFrame,
                 scenario:        weather_mod.WeatherScenario,
                 motor:           powertrain.MotorModel,
                 fc:              powertrain.FuelCellModel,
                 horizon_n:       int   = 30,
                 weights:         dict  = None,    # {w_h2, w_time, w_track, w_du, w_drv}
                 v_bounds:        tuple = (15.0, 45.0),
                 alpha_drv:       float = 0.3,
                 soc_target_frac: float = 0.6,
                 buffer:          powertrain.BufferModel | None = None,
                 adaptive:        bool  = False,
                 crr:             float = config.CRR,
                 drivetrain_eff:  float = config.DRIVETRAIN_EFFICIENCY_ASSUMED):
        ...

    def solve_step(self, state: dict, driver_state: dict, i: int) -> float:
        """
        Kembalikan v_cmd (m/s) — aksi optimal untuk 1 langkah.
        Gunakan grid enumeration atas v_candidates.
        Sertakan driver_deviation_penalty dalam cost.
        """
        ...

    def update_estimates(self, actual_state: dict, i: int):
        """
        OPSIONAL — online parameter estimation (hanya aktif jika adaptive=True).
        Tandai semua bagian belum ada data: # PLACEHOLDER — online estimation
        """
        ...


def run_closed_loop(full_track:   pd.DataFrame,
                    scenario:     weather_mod.WeatherScenario,
                    motor:        powertrain.MotorModel,
                    fc:           powertrain.FuelCellModel,
                    theta:        dict,
                    driver_trace: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Jalankan MPC end-to-end.

    Output DataFrame HARUS berisi SEMUA kolom yang sama seperti simulate(),
    PLUS kolom driver-awareness dari §6.4.

    driver_trace: opsional — DataFrame {"v_kmh", "a_ms2", ...} dari telemetri
                  driver nyata/sensor. Jika None, estimasi driver state dari v_ms.

    Return value HARUS bisa langsung dipakai di:
        telemetry.h2_score_km_per_m3(...)
        telemetry.accessory_h2_equivalent_m3(...)
    tanpa modifikasi apapun.
    """
    ...
```

---

## 11. Validasi / Kriteria Selesai

| #   | Kriteria                                                      | Cara Verifikasi                                              |
| --- | ------------------------------------------------------------- | ------------------------------------------------------------ |
| 1   | `step()` refactor tidak mengubah output                       | `np.testing.assert_allclose(old_csv, new_csv, rtol=1e-9)`    |
| 2   | `run_closed_loop(theta_default)` menghasilkan telemetry valid | `rule_violation.sum()==0`, jarak ≈ 14.8 km, stop count benar |
| 3   | Skor MPC (default theta) >= baseline crude                    | Bandingkan `h2_score_km_per_m3`                              |
| 4   | Skor MPC (GA-tuned theta) >= skor `optimize_ga` open-loop     | Run `optimize_mpc_hyperparams()`, bandingkan tabel           |
| 5   | Ganti motor/FC/CRR lewat argumen mengubah hasil               | Test dengan motor berbeda dari `data/motor_candidates.csv`   |
| 6   | Driver-awareness kolom ada di output CSV                      | Check header `simulated_telemetry_mpc.csv`                   |
| 7   | `GasGlideProblem` lama masih jalan                            | Panggil `optimize_strategy()` tanpa error                    |

---

## 12. Konvensi Kode yang Wajib Diikuti

1. **Satu file = satu metode.** Logika MPC di `mpc.py` SAJA. Optimizer di
   `optimize_ga.py` SAJA. Fisika di `vehicle.py` + `simulate.py` SAJA.
2. **JANGAN duplikasi persamaan fisika.** Selalu panggil `vehicle.py` dan
   `powertrain.py` dari `mpc.py`. Tidak boleh ada `0.5 * rho * Cd * A * v**2`
   di dalam `mpc.py`.
3. Tandai semua nilai belum terukur: `# PLACEHOLDER — [alasan]`
4. Tandai semua nilai terukur: `# MEASURED` / `# RULE-DERIVED`
5. `run_closed_loop()` output wajib kompatibel langsung dengan `telemetry.py`.
6. Tidak ada breaking change: `simulate()` lama tetap jalan identik setelah
   refactor `step()`.

---

## 13. Open Questions — Perlu Konfirmasi Sebelum Implementasi

- [ ] **Sensor driver tersedia?** Apakah hardware ada sensor throttle/brake posisi,
      atau hanya estimasi dari akselerasi? (Menentukan §6.2)
- [ ] **Driver trace dari mana?** Apakah `data/real_Telemetry_Example.csv` bisa
      dipakai sebagai sinyal driver referensi untuk simulasi?
- [ ] **Buffer aktifkan online estimation (§4.2)?** Static re-parameterization
      (§4.1) wajib. Online estimation butuh keputusan tim.
- [ ] **Solver horizon:** Grid enumeration (rekomendasi) atau scipy?
- [ ] **Massa kendaraan:** EP: 85 kg, repo: 88 kg — konfirmasi mana yang final
      untuk `config.MASS_VEHICLE_KG`.
- [ ] **Drivetrain efficiency:** EP: 92%, repo: 80%. Nilai mana untuk MPC
      prediction model?
