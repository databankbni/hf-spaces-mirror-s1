// Central API/WS config + type defs + small fetch helpers shared by every tab.

export const API_BASE = ''
export const WS_BASE = (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host

export async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`)
  return res.json()
}

export async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`)
  return res.json()
}

export async function putJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`)
  return res.json()
}

export async function deleteJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`)
  return res.json()
}

// --- Live Telemetry (MQTT bridge) -----------------------------------------

export interface DriverAdvisoryAction { action: 'ok' | 'glide' | 'brake'; distance_m: number | null; target_speed_kmh: number | null; s_m: number | null; latitude?: number | null; longitude?: number | null }
export interface DriverAdvisoryTurn { turn_no: number | null; distance_m: number | null; glide_in_m?: number | null; target_speed_kmh: number | null; v_safe_kmh?: number | null; s_m: number | null; latitude?: number | null; longitude?: number | null }
export interface DriverAdvisoryStop { stop_no: number | null; distance_m: number | null; stop_line_distance_m: number | null; target_speed_kmh: number | null; s_m: number | null; latitude?: number | null; longitude?: number | null }
export interface DriverAdvisoryCurrentStrategy { action: 'gas' | 'glide' | 'brake'; target_speed_kmh: number; s_m: number; latitude?: number | null; longitude?: number | null; live?: boolean }
export interface DriverAdvisoryDpSegment { v_target_kmh: number; v_coast_kmh: number; s_start_m: number; s_end_m: number }
// Steering advisory: signed lateral offset from the racing line, evaluated
// lookahead_m ahead of the car's own position. 0 = on the line; positive =
// steer left; negative = steer right. Only available with a live GPS fix
// (see racing_line.lateral_deviation_m).
export interface DriverAdvisoryLineDeviation { available: boolean; deviation_m?: number; lookahead_m?: number }
export interface DriverAdvisory {
  available: boolean
  // "dynamic" = current_strategy prefers a live MPC re-solve every call (adaptive,
  // but inherits MPC's own stop-blindspot). "ga_strict" = current_strategy is a pure
  // static lookup against GA's recorded plan, MPC never consulted. next_turn/next_stop
  // are GA-sourced and identical in both modes -- this only affects current_strategy.
  advisory_mode?: 'dynamic' | 'ga_strict'
  s_now_m?: number
  v_now_kmh?: number
  next_action?: DriverAdvisoryAction
  next_turn?: DriverAdvisoryTurn
  next_stop?: DriverAdvisoryStop
  current_strategy?: DriverAdvisoryCurrentStrategy
  dp_segment?: DriverAdvisoryDpSegment
  line_deviation?: DriverAdvisoryLineDeviation
}

export interface TelemetrySnapshot {
  broker_host: string
  broker_port: number
  car_topic: string
  gps_topic: string
  qos: number
  broker: string
  topics: string[]
  broker_connected: boolean
  connect_error: string | null
  live: boolean
  message_counts: Record<string, number>
  last_message_age_s: Record<string, number | null>
  latest: Record<string, unknown>
  recording: boolean
  recording_seconds: number
  recorded_row_count: number
  advisory: DriverAdvisory
}

export const configureTelemetry = (cfg: Partial<{ broker_host: string; broker_port: number; car_topic: string; gps_topic: string; qos: number }>) =>
  postJSON<TelemetrySnapshot>('/api/telemetry/configure', cfg)
export const connectTelemetry = () => postJSON<TelemetrySnapshot>('/api/telemetry/connect', {})
export const disconnectTelemetry = () => postJSON<TelemetrySnapshot>('/api/telemetry/disconnect', {})
export const startRecording = () => postJSON<TelemetrySnapshot>('/api/telemetry/record/start', {})
export const discardRecording = () => postJSON<TelemetrySnapshot>('/api/telemetry/record/discard', {})
export const stopRecordingAndSave = (body: { name: string; vehicle_id?: string; track_id?: string; notes?: string }) =>
  postJSON<{ success: boolean; error?: string; attempt?: Attempt }>('/api/telemetry/record/stop', body)

export const getAdvisoryMode = () => getJSON<{ mode: 'dynamic' | 'ga_strict' | null; available: boolean }>('/api/telemetry/advisory-mode')
export const setAdvisoryMode = (mode: 'dynamic' | 'ga_strict') =>
  postJSON<{ success: boolean; error?: string; mode?: string }>('/api/telemetry/advisory-mode', { mode })

export interface SimulatorStatus { running: boolean; gps: boolean | null; track_id: string | null; pid: number | null; running_seconds: number }
export const startSimulator = (gps = true, trackId?: string) =>
  postJSON<{ success: boolean; error?: string } & SimulatorStatus>('/api/telemetry/simulator/start', { gps, track_id: trackId })
export const stopSimulator = () => postJSON<{ success: boolean; error?: string } & SimulatorStatus>('/api/telemetry/simulator/stop', {})
export const getSimulatorStatus = () => getJSON<SimulatorStatus>('/api/telemetry/simulator/status')

// Mirrors clean_telemetry.py's ALIAS_GROUPS (normalised, lowercase-alnum-only
// matching) so the dashboard reads a raw field no matter what the publisher
// called it -- same "catch everything" contract as the download/MQTT logger.
export const FIELD_ALIASES: Record<string, string[]> = {
  vinBattery: ['vinbattery', 'vinfc', 'vinm', 'vin', 'voltage', 'volt', 'vbat',
    'batteryvoltage', 'battvoltage', 'battvolt', 'tegangan', 'teganganbaterai'],
  currentBattery: ['currentbattery', 'batterycurrent', 'battcurrent', 'currentm',
    'arusm', 'current', 'arus', 'ampere', 'amp', 'motorcurrent'],
  velocity: ['velocity', 'speed', 'vel', 'kecepatan', 'speedkmh', 'velocitykmh', 'speedms'],
  distance: ['distance', 'jarak', 'odometer', 'odo', 'distancekm', 'distancem', 'cumdistkm', 'cumdist', 'totaldistance'],
  powerW: ['powerw', 'power', 'daya', 'watt', 'powerwatt'],
  energyWh: ['energywh', 'energiwh', 'energy', 'energi', 'energywatthour', 'totalenergy', 'energykwh'],
  kmPerkWh: ['kmperkwh', 'efficiency', 'efisiensi', 'kmkwh', 'kmperkwhr'],
  mslAltitude: ['mslaltitude', 'altitude', 'alt', 'elevation', 'altitudem', 'ketinggian'],
  wgsAltitude: ['wgsaltitude', 'gpsaltitude'],
  gForceX: ['gforcex', 'accelx', 'ax', 'gx', 'accx'],
  gForceY: ['gforcey', 'accely', 'ay', 'gy', 'accy'],
  gForceZ: ['gforcez', 'accelz', 'az', 'gz', 'accz'],
  latitude: ['latitude', 'lat', 'gpslat'],
  longitude: ['longitude', 'lon', 'lng', 'long', 'gpslon', 'gpslng'],
  timeS: ['times', 'elapsed', 'elapseds', 'elapsedtime', 'timesec', 'waktus', 'runtime'],
  countdown: ['countdown'],
  h2leak: ['h2leak'],
  lap: ['lap', 'laps', 'lapnumber', 'lapno'],
  mode: ['mode', 'status', 'state'],
}

function normalizeKey(k: string): string {
  return k.toLowerCase().replace(/[^a-z0-9]/g, '')
}

export function pickField(latest: Record<string, unknown>, canonical: string): number | string | null {
  const aliases = FIELD_ALIASES[canonical] ?? [canonical]
  const normMap: Record<string, unknown> = {}
  for (const k of Object.keys(latest)) normMap[normalizeKey(k)] = latest[k]
  for (const alias of aliases) {
    if (alias in normMap) {
      const v = normMap[alias]
      return typeof v === 'number' || typeof v === 'string' ? v : null
    }
  }
  return null
}

// --- Garage: vehicles & tracks ----------------------------------------------
// The Sandbox no longer edits raw physics constants inline -- every vehicle's
// full spec (mass/aero/limits/powertrain) and every track's spec (GPS source
// files + attempt rules) lives here, persisted server-side, so a team running
// more than one car at more than one venue has one durable source of truth
// per vehicle/track instead of a single hardcoded config.

export const VALID_TAGS = ["MEASURED", "MEASURED-CFD", "RULE-DERIVED", "PLACEHOLDER", "PLACEHOLDER-CHOICE", "ASSUMPTION", "DERIVED"]

export interface VehicleField { value: number | string; unit?: string; tag: string; note?: string }
export type VehicleFields = Record<string, VehicleField>

export interface DerivedPowertrainEfficiency {
  speed_kmh: number
  p_wheel_w: number
  p_motor_mech_w: number
  p_motor_elec_w: number
  p_bus_elec_w: number
  p_fc_elec_w: number
  chemical_power_w: number
  drivetrain_eff_pct: number
  motor_eff_pct: number
  converter_eff_pct: number | null
  buffer_eff_pct: number
  fc_eff_pct: number
  overall_eff_pct: number
  motor_name: string
  fc_name: string
  converter_name: string | null
}

export interface VehicleDoc {
  id: string
  name: string
  energy_class: string
  notes: string
  default_motor?: string | null
  default_motor_accel?: string | null
  default_motor_cruise?: string | null
  default_cruise_converter?: string | null
  default_fc?: string | null
  motor_catalog_csv?: string | null
  fc_catalog_csv?: string | null
  aero_cda_by_geometry?: Record<string, [number, number][]> | null
  fields: VehicleFields
  derived_powertrain_efficiency?: DerivedPowertrainEfficiency | null
}

export interface VehicleSummary {
  id: string; name: string; energy_class: string; notes: string
  vehicle_mass_kg: number; driver_mass_kg: number
  default_motor?: string; default_motor_accel?: string; default_motor_cruise?: string
  default_cruise_converter?: string; default_fc?: string
}

export interface TrackDoc {
  id: string
  name: string
  location: string
  notes: string
  coordinates_csv: string
  turns_csv: string
  edges_csv: string
  racing_line_csv?: string | null
  lap_distance_km: number
  total_laps: number
  total_distance_km: number
  max_attempt_time_min: number
  stops_per_lap: number
  stop_locations_km: number[]
}

export const listVehicles = () => getJSON<{ vehicles: VehicleSummary[]; valid_tags: string[] }>('/api/vehicles')
export const getVehicle = (id: string) => getJSON<VehicleDoc>(`/api/vehicles/${id}`)
export const createVehicle = (body: Omit<VehicleDoc, 'id'>) => postJSON<VehicleDoc>('/api/vehicles', body)
export const updateVehicle = (id: string, body: Omit<VehicleDoc, 'id'>) => putJSON<VehicleDoc>(`/api/vehicles/${id}`, body)
export const deleteVehicle = (id: string) => deleteJSON<{ success: boolean; error?: string }>(`/api/vehicles/${id}`)
export const setVehicleFieldTag = (id: string, field: string, tag: string) =>
  postJSON<{ success: boolean; error?: string }>(`/api/vehicles/${id}/fields/${field}/tag`, { tag })
export const calcPowertrainEfficiency = (body: Partial<VehicleDoc>) =>
  postJSON<{ efficiency: DerivedPowertrainEfficiency | null }>('/api/vehicles/powertrain-efficiency', body)

export const listTracks = () => getJSON<{ tracks: TrackDoc[] }>('/api/tracks')
export const getTrack = (id: string) => getJSON<TrackDoc>(`/api/tracks/${id}`)
export const createTrack = (body: Omit<TrackDoc, 'id'>) => postJSON<TrackDoc>('/api/tracks', body)
export const updateTrack = (id: string, body: Omit<TrackDoc, 'id'>) => putJSON<TrackDoc>(`/api/tracks/${id}`, body)
export const deleteTrack = (id: string) => deleteJSON<{ success: boolean; error?: string }>(`/api/tracks/${id}`)

export const listDataFiles = () => getJSON<{ files: string[] }>('/api/data-files')

export interface MotorInfo { name: string; voltage_v: number; max_mech_power_w: number; rpm_range: [number, number] }
export interface FuelCellInfo { name: string; rated_power_w: number; has_efficiency_curve: boolean }
export interface ConverterInfo { name: string; output_v: number; rated_power_w: number; efficiency_pct: number }

export interface WeatherScenarioInfo {
  name: string
  temperature_c: number
  relative_humidity: number
  pressure_hpa: number
  wind_speed_kmh: number
  wind_from_bearing_deg: number
  air_density_kg_m3: number
  confidence: string
  source: string
}

export interface SimulateParams {
  vehicle_id?: string
  track_id?: string
  motor_mode?: 'single' | 'dual'
  motor_name?: string | null
  accel_motor_name?: string | null
  cruise_motor_name?: string | null
  fc_name?: string | null
  cruise_cap_enabled: boolean
  cruise_kmh?: number | null
  weather_scenario: string
  temperature_c?: number | null
  relative_humidity?: number | null
  pressure_hpa?: number | null
  wind_speed_kmh?: number | null
  wind_from_bearing_deg?: number | null
}

export interface SandboxChartPoint {
  distance_km: number
  speed_kmh: number
  altitude_m: number
  grade_pct: number
  a_ms2: number
  h2_flow_lpm: number
  p_motor_elec_w: number
  p_fc_elec_w: number
  f_drag_n: number
  f_roll_n: number
  f_grade_n: number
  f_cornering_n: number
}

export interface SimulateResult {
  success: boolean
  error?: string
  vehicle_id?: string
  vehicle_name?: string
  track_id?: string
  track_name?: string
  motor_mode?: 'single' | 'dual'
  motor_name?: string
  fc_name?: string
  cruise_kmh_used?: number
  score_km_per_m3: number
  h2_total_l: number
  accessory_h2_equiv_l: number
  total_time_min: number
  avg_speed_kmh: number
  max_speed_kmh: number
  air_density_kg_m3: number
  rule_violations: number
  stop_events: number
  motor_power_clipped_points: number
  chart_data: SandboxChartPoint[]
}

// --- Strategy (GA / PSO / CMA-ES) ------------------------------------------

export interface SegmentTarget {
  segment: number
  dist_start_km: number
  dist_end_km: number
  v_target_kmh: number
  v_coast_kmh: number
}

export interface StrategyChartPoint { distance_km: number; speed_kmh: number; h2_flow_lpm: number }

export interface StrategyResult {
  algo: string
  label: string
  available: boolean
  score_km_per_m3?: number
  h2_total_l?: number
  accessory_h2_equiv_l?: number
  total_time_min?: number
  avg_speed_kmh?: number
  max_speed_kmh?: number
  weather_scenario?: string
  motor_name?: string
  fc_name?: string
  segment_targets?: SegmentTarget[]
  chart_data?: StrategyChartPoint[]
}

export interface StrategyCompareResponse {
  results: Record<string, StrategyResult>
  vehicle: { id: string; name: string } | null
  track: { id: string; name: string; lap_distance_km: number; total_laps: number; total_distance_km: number; max_attempt_time_min: number } | null
}

// --- Attempts: saved runs (simulated: cruise/ga/pso/cma, or real: captured
// off the MQTT bridge and cleaned). This is what the Strategy tab lists. ---

export type SourceType = 'real' | 'simulated'
export type AttemptAlgorithm = 'cruise' | 'ga' | 'pso' | 'cma' | 'dp' | null

export interface AttemptSummary {
  score_km_per_m3?: number
  h2_total_l?: number
  accessory_h2_equiv_l?: number
  total_time_min?: number
  avg_speed_kmh?: number
  max_speed_kmh?: number
  row_count?: number
  duration_s?: number | null
}

export interface Attempt {
  id: string
  name: string
  created_at: string
  source_type: SourceType
  algorithm: AttemptAlgorithm
  vehicle_id: string | null
  track_id: string | null
  has_gps: boolean
  telemetry_csv: string | null
  segment_targets_csv: string | null
  qc_report_json: string | null
  summary: AttemptSummary | null
  notes: string
}

export type GasGlideState = 'gas' | 'glide' | 'brake' | null

export interface AttemptChartPoint {
  index: number
  distance_km: number | null
  speed_kmh: number | null
  latitude: number | null
  longitude: number | null
  h2_flow_lpm: number | null
  power_w: number | null
  state: GasGlideState
}

export interface AttemptChartResponse {
  points: AttemptChartPoint[]
  has_gps: boolean
  has_raw?: boolean
  state_available: boolean
  state_is_derived: boolean
  available_laps: number[]
  error?: string
}

export interface ReferenceLine { available: boolean; points: { latitude: number; longitude: number }[] }
export interface StopPoint { latitude: number; longitude: number; distance_km: number }
export interface ReferenceLinesResponse { centerline: ReferenceLine; racing_line: ReferenceLine; stops: StopPoint[] }

export const listAttempts = () => getJSON<{ attempts: Attempt[] }>('/api/attempts')
export const getAttempt = (id: string) => getJSON<Attempt>(`/api/attempts/${id}`)
export const getAttemptChart = (id: string, lap?: number | null, useRaw?: boolean) => {
  const params = new URLSearchParams()
  if (lap !== undefined && lap !== null) params.append('lap', String(lap))
  if (useRaw) params.append('use_raw', 'true')
  const qs = params.toString()
  return getJSON<AttemptChartResponse>(`/api/attempts/${id}/chart${qs ? `?${qs}` : ''}`)
}
export const getAttemptQCReport = (id: string) =>
  getJSON<{ available: boolean; report?: Record<string, unknown>; error?: string; message?: string }>(`/api/attempts/${id}/qc-report`)
export const getAttemptSegments = (id: string) => getJSON<{ available: boolean; segments?: SegmentTarget[] }>(`/api/attempts/${id}/segments`)
export const deleteAttempt = (id: string) => deleteJSON<{ success: boolean; error?: string }>(`/api/attempts/${id}`)
export const getReferenceLines = (trackId: string) => getJSON<ReferenceLinesResponse>(`/api/tracks/${trackId}/reference-lines`)

// --- Track analysis: the same per-point profile notebooks/Track_Analysis.ipynb
// explores by hand (turns, elevation, width, stops), computed live off
// whichever track is registered instead of frozen to one notebook run. ---
export interface TrackTurn { zone_id: number; start_km: number; end_km: number; r_min_m: number | null; v_safe_kmh_min: number | null }
export interface TrackElevationPoint { distance_km: number; altitude_m: number; grade_pct: number | null }
export interface TrackAnalysisResponse {
  available: boolean
  error?: string
  track_id?: string
  n_points?: number
  lap_distance_km?: number
  elevation?: {
    min_altitude_m: number; max_altitude_m: number
    max_uphill_grade_pct: number | null; max_uphill_km: number | null
    max_downhill_grade_pct: number | null; max_downhill_km: number | null
    profile: TrackElevationPoint[]
  }
  turns?: { count: number; tightest_r_min_m: number | null; list: TrackTurn[] }
  width?: { min_m: number | null; median_m: number | null; max_m: number | null }
  stops?: { distance_km: number; latitude: number; longitude: number }[]
}
export const getTrackAnalysis = (trackId: string) => getJSON<TrackAnalysisResponse>(`/api/tracks/${trackId}/analysis`)

export const saveSimulationAsAttempt = (body: SimulateParams & { name: string; notes?: string }) =>
  postJSON<{ success: boolean; error?: string; attempt?: Attempt }>('/api/attempts/from-simulation', body)

// --- Optimizer jobs: real GA/PSO/CMA-ES runs (not just the flat cruise
// physics), queued and run one after another (see optimizer_jobs.py for why
// true concurrency isn't safe with process-global config.*). ---

export type OptimizeAlgo = 'ga' | 'pso' | 'cma' | 'dp' | 'mpc' | 'fuzzy'

export interface OptimizeJob {
  id: string
  group_id: string
  algo: OptimizeAlgo
  label: string
  status: 'queued' | 'running' | 'done' | 'error'
  progress: number
  eta_s: number
  vehicle_id: string
  vehicle_name: string
  track_id: string
  track_name: string
  scenario_name: string
  motor_name: string
  fc_name: string
  pop_size: number | null
  n_gen: number | null
  result: { summary: AttemptSummary; telemetry_csv: string; segment_targets_csv: string; has_gps: boolean } | null
  error: string | null
  saved_attempt_id: string | null
}

export interface OptimizeRunRequest {
  algorithms: OptimizeAlgo[]
  vehicle_id?: string
  track_id?: string
  motor_name?: string | null
  fc_name?: string | null
  weather_scenario: string
  pop_size?: number  // omit -> Final_Project's own tuned/best config per algorithm
  n_gen?: number
}

export const runOptimizer = (body: OptimizeRunRequest) =>
  postJSON<{ success: boolean; error?: string; group_id: string; job_ids: string[]; eta_seconds_total: number }>('/api/optimize/run', body)
export const getOptimizeJob = (id: string) => getJSON<OptimizeJob>(`/api/optimize/jobs/${id}`)
export const getOptimizeGroup = (groupId: string) => getJSON<{ jobs: OptimizeJob[] }>(`/api/optimize/groups/${groupId}`)
export const saveOptimizeJob = (id: string, name: string, notes = '') =>
  postJSON<{ success: boolean; error?: string; attempt?: Attempt }>(`/api/optimize/jobs/${id}/save`, { name, notes })
export const discardOptimizeJob = (id: string) => deleteJSON<{ success: boolean }>(`/api/optimize/jobs/${id}`)

export interface CleanAndAssignParams {
  durations?: string
  lap_dist?: number
  use_gps?: boolean
  start_lat?: number
  start_lon?: number
  start_time?: string
}

export const cleanAndAssignLaps = (attemptId: string, params: CleanAndAssignParams) =>
  postJSON<{ success: boolean; error?: string; laps_assigned?: number[]; total_rows?: number; qc_report?: unknown }>(
    `/api/attempts/${attemptId}/clean-and-assign-laps`,
    params
  )

export const updateTrackStartLine = (trackId: string, start_lat: number, start_lon: number) =>
  postJSON<{ success: boolean; error?: string; start_lat?: number; start_lon?: number }>(
    `/api/tracks/${trackId}/start-line`,
    { start_lat, start_lon }
  )
