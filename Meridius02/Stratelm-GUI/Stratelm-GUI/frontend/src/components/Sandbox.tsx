import { useEffect, useRef, useState } from 'react'
import { Car, MapPin, Cpu, CloudSun, Gauge, Save, Trophy, Flame, Dna, Waves, Sigma, Play, Check } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import {
  getJSON, postJSON,
  listVehicles, listTracks, saveSimulationAsAttempt,
  runOptimizer, getOptimizeGroup, saveOptimizeJob,
  type VehicleSummary, type TrackDoc, type WeatherScenarioInfo, type MotorInfo, type FuelCellInfo,
  listAttempts,
  type SimulateParams, type SimulateResult, type Attempt,
  type OptimizeAlgo, type OptimizeJob,
} from '../api'
import { inputCls, inputClsDisabled } from './ParamUI'

const ALGO_META: Record<OptimizeAlgo, { label: string; icon: React.ReactNode; color: string }> = {
  ga: { label: 'Genetic Algorithm', icon: <Dna size={16} />, color: '#631acb' },
  pso: { label: 'Particle Swarm Optimization', icon: <Waves size={16} />, color: '#3b82f6' },
  cma: { label: 'CMA-ES', icon: <Sigma size={16} />, color: '#f59e0b' },
  dp: { label: 'DP (Physics-Optimal)', icon: <Sigma size={16} />, color: '#10b981' },
  mpc: { label: 'Model Predictive Control (MPC)', icon: <Gauge size={16} />, color: '#ec4899' },
  fuzzy: { label: 'Fuzzy Logic (TSK)', icon: <Waves size={16} />, color: '#06b6d4' },
}

// Final_Project's own validated best-known settings (digital_twin/optimize_{ga,pso,cma}.py's
// function defaults, confirmed by the team's Racing_Line_Strategy_Comparison.ipynb) --
// mirrors Stratelm-GUI/backend/optimizer_jobs.py's BEST_DEFAULTS, used here only to
// show an accurate per-algorithm ETA before the run actually resolves them server-side.
const BEST_CONFIG: Partial<Record<OptimizeAlgo, [number, number]>> = { ga: [50, 40], pso: [20, 30], cma: [20, 30], mpc: [20, 30], fuzzy: [20, 30] }

export default function Sandbox() {
  const [vehicles, setVehicles] = useState<VehicleSummary[]>([])
  const [tracks, setTracks] = useState<TrackDoc[]>([])
  const [motors, setMotors] = useState<MotorInfo[]>([])
  const [fuelCells, setFuelCells] = useState<FuelCellInfo[]>([])
  const [scenarios, setScenarios] = useState<WeatherScenarioInfo[]>([])

  const [vehicleId, setVehicleId] = useState('')
  const [trackId, setTrackId] = useState('')
  const [motorMode, setMotorMode] = useState<'single' | 'dual'>('single')
  const [motorName, setMotorName] = useState('')
  const [accelMotorName, setAccelMotorName] = useState('')
  const [cruiseMotorName, setCruiseMotorName] = useState('')
  const [fcName, setFcName] = useState('')
  const [cruiseCapEnabled, setCruiseCapEnabled] = useState(true)
  const [cruiseKmh, setCruiseKmh] = useState<number | null>(null)
  const [weatherScenario, setWeatherScenario] = useState('typical_january')
  const [customEnv, setCustomEnv] = useState(false)
  const [envOverride, setEnvOverride] = useState<{ temperature_c?: number; relative_humidity?: number; pressure_hpa?: number; wind_speed_kmh?: number; wind_from_bearing_deg?: number }>({})

  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<SimulateResult | null>(null)
  const [benchmarkAttempts, setBenchmarkAttempts] = useState<Attempt[]>([])
  const [error, setError] = useState<string | null>(null)

  const [cruiseSaveOpen, setCruiseSaveOpen] = useState(false)
  const [cruiseSaveName, setCruiseSaveName] = useState('')
  const [cruiseSaving, setCruiseSaving] = useState(false)
  const [cruiseSaved, setCruiseSaved] = useState(false)

  const [selectedAlgos, setSelectedAlgos] = useState<Record<OptimizeAlgo, boolean>>({ ga: true, pso: false, cma: false, dp: false, mpc: false, fuzzy: false })
  const [useBestConfig, setUseBestConfig] = useState(true)
  const [popSize, setPopSize] = useState(10)
  const [nGen, setNGen] = useState(8)
  const [optJobs, setOptJobs] = useState<OptimizeJob[]>([])
  const [optSubmitting, setOptSubmitting] = useState(false)
  const [optError, setOptError] = useState<string | null>(null)
  const [jobSaveNames, setJobSaveNames] = useState<Record<string, string>>({})
  const [jobSaving, setJobSaving] = useState<Record<string, boolean>>({})
  const pollRef = useRef<number | null>(null)

  useEffect(() => {
    listVehicles().then(r => {
      setVehicles(r.vehicles)
      if (r.vehicles.length && !vehicleId) setVehicleId(r.vehicles[0].id)
    }).catch(e => setError(String(e)))
    listTracks().then(r => {
      setTracks(r.tracks)
      if (r.tracks.length && !trackId) setTrackId(r.tracks[0].id)
    }).catch(e => setError(String(e)))
    getJSON<{ scenarios: WeatherScenarioInfo[]; default: string }>('/api/weather-scenarios').then(r => setScenarios(r.scenarios)).catch(() => {})
    listAttempts().then(r => setBenchmarkAttempts(
      r.attempts.filter(a => a.source_type === 'simulated' && a.algorithm && a.algorithm !== 'cruise' && a.summary)
    )).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!vehicleId) return
    getJSON<{ motors: MotorInfo[]; default: string }>(`/api/motors?vehicle_id=${vehicleId}`).then(r => {
      setMotors(r.motors)
      setMotorName(r.default)
    }).catch(() => {})
    getJSON<{ fuel_cells: FuelCellInfo[]; default: string }>(`/api/fuel-cells?vehicle_id=${vehicleId}`).then(r => {
      setFuelCells(r.fuel_cells)
      setFcName(r.default)
    }).catch(() => {})
    setCruiseKmh(null) // fall back to the newly-selected vehicle's own cruise_target_kmh
    const v = vehicles.find(v => v.id === vehicleId)
    setAccelMotorName(v?.default_motor_accel ?? '')
    setCruiseMotorName(v?.default_motor_cruise ?? '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vehicleId])

  const selectedVehicle = vehicles.find(v => v.id === vehicleId)
  const vehicleHasDualMotor = !!(selectedVehicle?.default_motor_accel && selectedVehicle?.default_motor_cruise)
  const selectedTrack = tracks.find(t => t.id === trackId)
  const activeScenario = scenarios.find(s => s.name === weatherScenario)

  const handleSimulate = async () => {
    setLoading(true)
    setError(null)
    try {
      const payload: SimulateParams = {
        vehicle_id: vehicleId || undefined,
        track_id: trackId || undefined,
        motor_mode: motorMode,
        ...(motorMode === 'dual'
          ? { accel_motor_name: accelMotorName || undefined, cruise_motor_name: cruiseMotorName || undefined }
          : { motor_name: motorName || undefined }),
        fc_name: fcName || undefined,
        cruise_cap_enabled: cruiseCapEnabled,
        cruise_kmh: cruiseKmh ?? undefined,
        weather_scenario: weatherScenario,
        ...(customEnv ? envOverride : {}),
      }
      const data = await postJSON<SimulateResult>('/api/simulate', payload)
      if (data.success) { setResult(data); setCruiseSaved(false) }
      else setError(data.error ?? 'Simulation failed')
    } catch (e) {
      setError(String(e))
    }
    setLoading(false)
  }

  const handleSaveCruise = async () => {
    setCruiseSaving(true)
    try {
      const res = await saveSimulationAsAttempt({
        vehicle_id: vehicleId || undefined,
        track_id: trackId || undefined,
        motor_mode: motorMode,
        ...(motorMode === 'dual'
          ? { accel_motor_name: accelMotorName || undefined, cruise_motor_name: cruiseMotorName || undefined }
          : { motor_name: motorName || undefined }),
        fc_name: fcName || undefined,
        cruise_cap_enabled: cruiseCapEnabled,
        cruise_kmh: cruiseKmh ?? undefined,
        weather_scenario: weatherScenario,
        ...(customEnv ? envOverride : {}),
        name: cruiseSaveName,
      })
      if (res.success) { setCruiseSaveOpen(false); setCruiseSaved(true) }
      else setError(res.error ?? 'save failed')
    } catch (e) {
      setError(String(e))
    }
    setCruiseSaving(false)
  }

  const stopPolling = () => {
    if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null }
  }

  const handleRunOptimizer = async () => {
    const algorithms = (Object.keys(selectedAlgos) as OptimizeAlgo[]).filter(a => selectedAlgos[a])
    if (!algorithms.length) { setOptError('Pick at least one algorithm.'); return }
    setOptSubmitting(true)
    setOptError(null)
    setOptJobs([])
    stopPolling()
    try {
      const res = await runOptimizer({
        algorithms, vehicle_id: vehicleId || undefined, track_id: trackId || undefined,
        motor_name: motorName || undefined, fc_name: fcName || undefined,
        weather_scenario: weatherScenario,
        ...(useBestConfig ? {} : { pop_size: popSize, n_gen: nGen }),
      })
      if (!res.success) { setOptError(res.error ?? 'failed to start'); setOptSubmitting(false); return }
      const groupId = res.group_id
      const poll = async () => {
        const { jobs } = await getOptimizeGroup(groupId)
        setOptJobs(jobs)
        if (jobs.length && jobs.every(j => j.status === 'done' || j.status === 'error')) stopPolling()
      }
      await poll()
      pollRef.current = window.setInterval(poll, 3000)
    } catch (e) {
      setOptError(String(e))
    }
    setOptSubmitting(false)
  }

  useEffect(() => stopPolling, [])

  const handleSaveJob = async (jobId: string) => {
    const name = jobSaveNames[jobId] || `Job ${jobId}`
    setJobSaving(prev => ({ ...prev, [jobId]: true }))
    try {
      const res = await saveOptimizeJob(jobId, name)
      if (res.success) {
        setOptJobs(prev => prev.map(j => j.id === jobId ? { ...j, saved_attempt_id: jobId } : j))
      } else {
        setOptError(res.error ?? 'save failed')
      }
    } catch (e) {
      setOptError(String(e))
    }
    setJobSaving(prev => ({ ...prev, [jobId]: false }))
  }

  const num = (v: string) => parseFloat(v)

  const selectedAlgoList = (Object.keys(selectedAlgos) as OptimizeAlgo[]).filter(a => selectedAlgos[a])
  const etaSecondsFor = (a: OptimizeAlgo) => {
    if (a === 'dp') return 15
    const [p, g] = useBestConfig ? (BEST_CONFIG[a] ?? [popSize, nGen]) : [popSize, nGen]
    return p * g * 7.5
  }
  const totalEtaS = selectedAlgoList.reduce((sum, a) => sum + etaSecondsFor(a), 0)

  return (
    <div className="p-8 overflow-y-auto h-full">
      <div className="mb-8">
        <h2 className="text-3xl font-bold flex items-center gap-3"><Cpu className="text-brand-purple" />Digital Twin Sandbox</h2>
        <p className="text-gray-400">Pick a vehicle & track from the Garage, set the environment, then run the physics twin</p>
      </div>

      {error && <div className="mb-6 bg-red-500/10 border border-red-500/30 text-red-400 rounded-lg px-4 py-3 text-sm">{error}</div>}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-8">
        {/* Pickers */}
        <div className="xl:col-span-1 flex flex-col gap-6">
          <div className="bg-dark-card border border-dark-border rounded-xl p-6">
            <h3 className="text-lg font-bold mb-5 flex items-center gap-2"><Car className="text-brand-purple" size={18} />Vehicle</h3>
            <select className={inputCls} value={vehicleId} onChange={e => setVehicleId(e.target.value)}>
              {vehicles.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
            {selectedVehicle && (
              <div className="grid grid-cols-2 gap-2 text-xs text-gray-400 bg-[#0d1117] rounded-lg p-3 border border-dark-border mt-3">
                <span>Class: {selectedVehicle.energy_class?.replace(/_/g, ' ')}</span>
                <span>Mass: {selectedVehicle.vehicle_mass_kg} kg</span>
                <span className="col-span-2 truncate">Motors: Accel: {selectedVehicle.default_motor_accel ?? selectedVehicle.default_motor ?? 'None'} · Cruise: {selectedVehicle.default_motor_cruise ?? selectedVehicle.default_motor ?? 'None'}</span>
              </div>
            )}
            <p className="text-[11px] text-gray-600 mt-2">Edit this vehicle's full spec in the Garage tab.</p>

            <div className="mt-5 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1">Motor Setup (this run)</label>
                <div className="grid grid-cols-2 gap-2">
                  <button type="button" onClick={() => setMotorMode('single')}
                    className={`text-sm py-2 rounded-lg border transition-colors ${motorMode === 'single' ? 'bg-brand-purple border-brand-purple text-white' : 'bg-[#0d1117] border-dark-border text-gray-400 hover:border-brand-purple/50'}`}>
                    Single Motor
                  </button>
                  <button type="button" onClick={() => setMotorMode('dual')}
                    className={`text-sm py-2 rounded-lg border transition-colors ${motorMode === 'dual' ? 'bg-brand-purple border-brand-purple text-white' : 'bg-[#0d1117] border-dark-border text-gray-400 hover:border-brand-purple/50'}`}>
                    Dual Motor
                  </button>
                </div>
                {motorMode === 'dual' && !vehicleHasDualMotor && (
                  <p className="text-[11px] text-amber-400 mt-1">This vehicle has no accel/cruise motor pair set as default — pick both below, or set them in the Garage.</p>
                )}
              </div>

              {motorMode === 'single' ? (
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">Motor (this run)</label>
                  <select className={inputCls} value={motorName} onChange={e => setMotorName(e.target.value)}>
                    {motors.map(m => <option key={m.name} value={m.name}>{m.name} ({m.voltage_v}V, {m.max_mech_power_w}W)</option>)}
                  </select>
                </div>
              ) : (
                <div className="space-y-3">
                  <div>
                    <label className="block text-sm font-medium text-gray-400 mb-1">Accel Motor (this run)</label>
                    <select className={inputCls} value={accelMotorName} onChange={e => setAccelMotorName(e.target.value)}>
                      <option value="">-- select --</option>
                      {motors.map(m => <option key={m.name} value={m.name}>{m.name} ({m.voltage_v}V, {m.max_mech_power_w}W)</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-400 mb-1">Cruise Motor (this run)</label>
                    <select className={inputCls} value={cruiseMotorName} onChange={e => setCruiseMotorName(e.target.value)}>
                      <option value="">-- select --</option>
                      {motors.map(m => <option key={m.name} value={m.name}>{m.name} ({m.voltage_v}V, {m.max_mech_power_w}W)</option>)}
                    </select>
                  </div>
                  <p className="text-[11px] text-gray-600">
                    Accel motor sits directly on the 48V bus; cruise motor draws through the vehicle's DC/DC converter (Garage tab).
                  </p>
                </div>
              )}
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1">Fuel Cell (this run)</label>
                <select className={inputCls} value={fcName} onChange={e => setFcName(e.target.value)}>
                  {fuelCells.map(f => <option key={f.name} value={f.name}>{f.name} ({f.rated_power_w}W)</option>)}
                </select>
              </div>
              <div>
                <div className="flex justify-between items-center mb-1">
                  <label className="flex items-center gap-2 text-sm font-medium text-gray-400 cursor-pointer">
                    <input type="checkbox" checked={cruiseCapEnabled} onChange={e => setCruiseCapEnabled(e.target.checked)} />
                    Cruise Target (km/h)
                  </label>
                </div>
                <input type="number" className={cruiseCapEnabled ? inputCls : inputClsDisabled}
                  disabled={!cruiseCapEnabled}
                  placeholder="vehicle default"
                  value={cruiseKmh ?? ''}
                  onChange={e => setCruiseKmh(e.target.value === '' ? null : num(e.target.value))} />
                <p className="text-[11px] text-gray-600 mt-1">
                  {cruiseCapEnabled
                    ? "Leave blank to use this vehicle's own cruise target (set in the Garage)."
                    : 'Disabled — the car accelerates as hard as the motor/track allow, capped only by track-safety speed limits.'}
                </p>
              </div>
            </div>
          </div>

          <div className="bg-dark-card border border-dark-border rounded-xl p-6">
            <h3 className="text-lg font-bold mb-5 flex items-center gap-2"><MapPin className="text-brand-purple" size={18} />Track</h3>
            <select className={inputCls} value={trackId} onChange={e => setTrackId(e.target.value)}>
              {tracks.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            {selectedTrack && (
              <div className="grid grid-cols-2 gap-2 text-xs text-gray-400 bg-[#0d1117] rounded-lg p-3 border border-dark-border mt-3">
                <span>{selectedTrack.location}</span>
                <span>{selectedTrack.lap_distance_km} km/lap</span>
                <span>{selectedTrack.total_laps} laps</span>
                <span>{selectedTrack.max_attempt_time_min} min limit</span>
              </div>
            )}
            <p className="text-[11px] text-gray-600 mt-2">Register more tracks in the Garage tab.</p>
          </div>

          <div className="bg-dark-card border border-dark-border rounded-xl p-6">
            <h3 className="text-lg font-bold mb-5 flex items-center gap-2"><CloudSun className="text-brand-purple" size={18} />Environment / Location</h3>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1">Weather Scenario</label>
                <select className={inputCls} value={weatherScenario} disabled={customEnv} onChange={e => setWeatherScenario(e.target.value)}>
                  {scenarios.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
                </select>
              </div>
              {activeScenario && !customEnv && (
                <div className="grid grid-cols-2 gap-2 text-xs text-gray-400 bg-[#0d1117] rounded-lg p-3 border border-dark-border">
                  <span>Temp: {activeScenario.temperature_c}°C</span>
                  <span>Humidity: {(activeScenario.relative_humidity * 100).toFixed(0)}%</span>
                  <span>Pressure: {activeScenario.pressure_hpa} hPa</span>
                  <span>Wind: {activeScenario.wind_speed_kmh} km/h @ {activeScenario.wind_from_bearing_deg}°</span>
                  <span className="col-span-2">Air density: {activeScenario.air_density_kg_m3} kg/m³</span>
                </div>
              )}
              <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
                <input type="checkbox" checked={customEnv} onChange={e => setCustomEnv(e.target.checked)} />
                Override location manually
              </label>
              {customEnv && (
                <div className="grid grid-cols-2 gap-3">
                  <div><label className="block text-sm font-medium text-gray-400 mb-1">Temp (°C)</label>
                    <input type="number" className={inputCls} value={envOverride.temperature_c ?? activeScenario?.temperature_c ?? 17.7}
                      onChange={e => setEnvOverride({ ...envOverride, temperature_c: num(e.target.value) })} /></div>
                  <div><label className="block text-sm font-medium text-gray-400 mb-1">Humidity (0-1)</label>
                    <input type="number" step="0.01" className={inputCls} value={envOverride.relative_humidity ?? activeScenario?.relative_humidity ?? 0.65}
                      onChange={e => setEnvOverride({ ...envOverride, relative_humidity: num(e.target.value) })} /></div>
                  <div><label className="block text-sm font-medium text-gray-400 mb-1">Pressure (hPa)</label>
                    <input type="number" className={inputCls} value={envOverride.pressure_hpa ?? activeScenario?.pressure_hpa ?? 1015}
                      onChange={e => setEnvOverride({ ...envOverride, pressure_hpa: num(e.target.value) })} /></div>
                  <div><label className="block text-sm font-medium text-gray-400 mb-1">Wind (km/h)</label>
                    <input type="number" className={inputCls} value={envOverride.wind_speed_kmh ?? activeScenario?.wind_speed_kmh ?? 17}
                      onChange={e => setEnvOverride({ ...envOverride, wind_speed_kmh: num(e.target.value) })} /></div>
                  <div><label className="block text-sm font-medium text-gray-400 mb-1">Wind From (deg)</label>
                    <input type="number" className={inputCls} value={envOverride.wind_from_bearing_deg ?? activeScenario?.wind_from_bearing_deg ?? 351}
                      onChange={e => setEnvOverride({ ...envOverride, wind_from_bearing_deg: num(e.target.value) })} /></div>
                </div>
              )}
            </div>
          </div>

          <button onClick={handleSimulate}
            disabled={loading || !vehicleId || !trackId || (motorMode === 'dual' && (!accelMotorName || !cruiseMotorName))}
            className="w-full bg-brand-purple hover:bg-brand-purple/80 text-white font-bold py-3 rounded-lg transition-colors flex justify-center items-center gap-2">
            {loading ? <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div> : <Save size={18} />}
            {loading ? 'Simulating (full attempt)...' : 'Run Simulation (flat cruise)'}
          </button>

          <div className="bg-dark-card border border-dark-border rounded-xl p-6">
            <h3 className="text-lg font-bold mb-2 flex items-center gap-2"><Trophy className="text-brand-purple" size={18} />Strategy Optimizer</h3>
            <p className="text-[11px] text-gray-600 mb-4">
              A flat cruise target is a naive baseline — run the real GA/PSO/CMA-ES gas/glide search over the QP optimum racing line instead (or several at once to compare).
              {selectedAlgoList.length > 0 && <> Each takes minutes, not seconds: ~{Math.round(totalEtaS)}s total for the selected algorithm(s) at these settings.</>}
            </p>
            <div className="space-y-2 mb-4">
              {(Object.keys(ALGO_META) as OptimizeAlgo[]).map(a => (
                <label key={a} className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                  <input type="checkbox" checked={selectedAlgos[a]} onChange={e => setSelectedAlgos({ ...selectedAlgos, [a]: e.target.checked })} />
                  <span style={{ color: ALGO_META[a].color }}>{ALGO_META[a].icon}</span>
                  {ALGO_META[a].label}
                </label>
              ))}
            </div>
            <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer mb-2">
              <input type="checkbox" checked={useBestConfig} onChange={e => setUseBestConfig(e.target.checked)} />
              Use tuned best configuration <span className="text-gray-600">(recommended)</span>
            </label>
            <p className="text-[11px] text-gray-600 mb-3">
              {useBestConfig
                ? "Each algorithm runs Final_Project's own validated settings — GA 50×40, PSO 20×30, CMA-ES 20×30 gen (DP has no population/generations concept)."
                : 'Custom settings below apply to every selected algorithm.'}
            </p>
            <div className="grid grid-cols-2 gap-3 mb-4">
              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1">Population</label>
                <input type="number" min={4} disabled={useBestConfig} className={useBestConfig ? inputClsDisabled : inputCls}
                  value={popSize} onChange={e => setPopSize(parseInt(e.target.value, 10) || 4)} />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1">Generations</label>
                <input type="number" min={1} disabled={useBestConfig} className={useBestConfig ? inputClsDisabled : inputCls}
                  value={nGen} onChange={e => setNGen(parseInt(e.target.value, 10) || 1)} />
              </div>
            </div>
            {optError && <div className="mb-3 text-sm text-red-400">{optError}</div>}
            <button onClick={handleRunOptimizer} disabled={optSubmitting || !vehicleId || !trackId}
              className="w-full bg-dark-border hover:bg-brand-purple/30 border border-dark-border hover:border-brand-purple/50 text-white font-bold py-2.5 rounded-lg transition-colors flex justify-center items-center gap-2">
              <Play size={16} /> {optSubmitting ? 'Starting...' : 'Run Optimizer(s)'}
            </button>
          </div>
        </div>

        {/* Results */}
        <div className="xl:col-span-2 flex flex-col gap-6">
          {result && (
            <div className="text-xs text-gray-500">
              Ran <span className="text-gray-300">{result.vehicle_name}</span> on <span className="text-gray-300">{result.track_name}</span> — {result.motor_name} / {result.fc_name}, cruise {result.cruise_kmh_used?.toFixed(1)} km/h
            </div>
          )}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <ResultCard label="Art 54e Score" value={result?.score_km_per_m3} unit="km/m³" highlight />
            <ResultCard label="Total H2" value={result?.h2_total_l} unit="L" />
            <ResultCard label="Avg Speed" value={result?.avg_speed_kmh} unit="km/h" />
            <ResultCard label="Attempt Time" value={result?.total_time_min} unit="min" />
          </div>

          {result && (
            <div className="flex items-center gap-3">
              {!cruiseSaveOpen && !cruiseSaved && (
                <button onClick={() => { setCruiseSaveOpen(true); setCruiseSaveName(`Cruise run ${new Date().toLocaleString()}`) }}
                  className="text-sm bg-dark-card border border-dark-border hover:border-brand-purple/50 text-gray-300 px-4 py-2 rounded-lg flex items-center gap-2">
                  <Save size={14} /> Save this run
                </button>
              )}
              {cruiseSaved && <span className="text-sm text-green-400 flex items-center gap-2"><Check size={14} /> Saved — view it in the Strategy tab</span>}
              {cruiseSaveOpen && (
                <div className="flex items-center gap-2 flex-1">
                  <input className={inputCls} value={cruiseSaveName} onChange={e => setCruiseSaveName(e.target.value)} />
                  <button onClick={handleSaveCruise} disabled={cruiseSaving}
                    className="bg-brand-purple hover:bg-brand-purple/80 text-white text-sm font-bold px-4 py-2 rounded-lg whitespace-nowrap">
                    {cruiseSaving ? 'Saving...' : 'Confirm'}
                  </button>
                  <button onClick={() => setCruiseSaveOpen(false)} className="text-gray-400 hover:text-white text-sm px-2">Cancel</button>
                </div>
              )}
            </div>
          )}

          {optJobs.length > 0 && (
            <div className="bg-dark-card border border-dark-border rounded-xl p-5">
              <h3 className="text-sm font-semibold mb-4 flex items-center gap-2 text-gray-300 uppercase tracking-wider">
                <Trophy size={14} className="text-yellow-500" /> Optimizer Runs
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {optJobs.map(job => (
                  <div key={job.id} className="bg-[#0d1117] border border-dark-border rounded-lg p-4">
                    <div className="flex items-center gap-2 mb-2 text-xs font-semibold uppercase tracking-wider" style={{ color: ALGO_META[job.algo].color }}>
                      {ALGO_META[job.algo].icon} {job.label}
                    </div>
                    {job.status !== 'done' && job.status !== 'error' && (
                      <>
                        <div className="w-full bg-dark-border rounded-full h-1.5 mb-2">
                          <div className="h-1.5 rounded-full bg-brand-purple transition-all" style={{ width: `${job.progress}%` }} />
                        </div>
                        <div className="text-xs text-gray-500">{job.status} — {job.progress.toFixed(0)}%</div>
                      </>
                    )}
                    {job.status === 'error' && <div className="text-xs text-red-400">{job.error}</div>}
                    {job.status === 'done' && job.result && (
                      <>
                        <div className="text-2xl font-bold text-white mb-1">
                          {job.result.summary.score_km_per_m3?.toFixed(1)} <span className="text-xs text-gray-500">km/m³</span>
                        </div>
                        <div className="text-xs text-gray-400 grid grid-cols-2 gap-x-2 mb-3">
                          <span>H2: {job.result.summary.h2_total_l?.toFixed(1)} L</span>
                          <span>Time: {job.result.summary.total_time_min?.toFixed(1)} min</span>
                        </div>
                        {job.saved_attempt_id ? (
                          <span className="text-xs text-green-400 flex items-center gap-1"><Check size={12} /> Saved</span>
                        ) : (
                          <div className="flex gap-2">
                            <input className={`${inputCls} text-xs py-1`} placeholder="name..."
                              value={jobSaveNames[job.id] ?? `${job.label} run`}
                              onChange={e => setJobSaveNames({ ...jobSaveNames, [job.id]: e.target.value })} />
                            <button onClick={() => handleSaveJob(job.id)} disabled={jobSaving[job.id]}
                              className="text-xs bg-brand-purple hover:bg-brand-purple/80 text-white px-3 py-1 rounded whitespace-nowrap">
                              {jobSaving[job.id] ? '...' : 'Save'}
                            </button>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {benchmarkAttempts.length > 0 && (
            <div className="bg-dark-card border border-dark-border rounded-xl p-5">
              <h3 className="text-sm font-semibold mb-3 flex items-center gap-2 text-gray-300 uppercase tracking-wider">
                <Trophy size={14} className="text-yellow-500" /> Reference: Optimizer Benchmarks (Strategy tab)
              </h3>
              <p className="text-[11px] text-gray-600 mb-3">
                Saved simulated runs — only a fair comparison if the vehicle/track match what you're running above.
              </p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                {benchmarkAttempts.map(a => (
                  <div key={a.id} className="bg-[#0d1117] border border-dark-border rounded-lg px-3 py-2">
                    <div className="text-xs text-gray-500">{a.algorithm ? ALGO_META[a.algorithm as OptimizeAlgo]?.label ?? a.algorithm : a.name}</div>
                    <div className="text-lg font-bold text-white">{a.summary?.score_km_per_m3?.toFixed(1) ?? '--'} <span className="text-xs text-gray-500">km/m³</span></div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {result && result.chart_data.length > 0 && (
            <>
              <ChartCard title="Velocity vs Distance" icon={<Gauge size={16} className="text-brand-purple" />}>
                <LineChart data={result.chart_data} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                  <XAxis dataKey="distance_km" stroke="#8b949e" tickFormatter={v => v.toFixed(1)} />
                  <YAxis stroke="#8b949e" />
                  <Tooltip contentStyle={{ backgroundColor: '#161b22', borderColor: '#30363d', color: '#fff' }} labelFormatter={l => `Dist: ${Number(l).toFixed(2)} km`} />
                  <Line type="monotone" dataKey="speed_kmh" name="Speed (km/h)" stroke="#631acb" strokeWidth={2} dot={false} />
                </LineChart>
              </ChartCard>

              <ChartCard title="Resistance Forces vs Distance" icon={<Cpu size={16} className="text-blue-400" />}>
                <LineChart data={result.chart_data} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                  <XAxis dataKey="distance_km" stroke="#8b949e" tickFormatter={v => v.toFixed(1)} />
                  <YAxis stroke="#8b949e" />
                  <Tooltip contentStyle={{ backgroundColor: '#161b22', borderColor: '#30363d', color: '#fff' }} labelFormatter={l => `Dist: ${Number(l).toFixed(2)} km`} />
                  <Legend />
                  <Line type="monotone" dataKey="f_drag_n" name="Drag (N)" stroke="#3b82f6" strokeWidth={1.5} dot={false} />
                  <Line type="monotone" dataKey="f_roll_n" name="Rolling (N)" stroke="#f59e0b" strokeWidth={1.5} dot={false} />
                  <Line type="monotone" dataKey="f_grade_n" name="Grade (N)" stroke="#10b981" strokeWidth={1.5} dot={false} />
                  <Line type="monotone" dataKey="f_cornering_n" name="Cornering (N)" stroke="#ec4899" strokeWidth={1.5} dot={false} />
                </LineChart>
              </ChartCard>

              <ChartCard title="Electrical Power vs Distance" icon={<Flame size={16} className="text-yellow-500" />}>
                <LineChart data={result.chart_data} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                  <XAxis dataKey="distance_km" stroke="#8b949e" tickFormatter={v => v.toFixed(1)} />
                  <YAxis stroke="#8b949e" />
                  <Tooltip contentStyle={{ backgroundColor: '#161b22', borderColor: '#30363d', color: '#fff' }} labelFormatter={l => `Dist: ${Number(l).toFixed(2)} km`} />
                  <Legend />
                  <Line type="monotone" dataKey="p_motor_elec_w" name="Motor Electrical (W)" stroke="#631acb" strokeWidth={1.5} dot={false} />
                  <Line type="monotone" dataKey="p_fc_elec_w" name="FC Electrical (W)" stroke="#22d3ee" strokeWidth={1.5} dot={false} />
                </LineChart>
              </ChartCard>

              <ChartCard title="H2 Flow vs Distance" icon={<Flame size={16} className="text-orange-400" />}>
                <LineChart data={result.chart_data} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                  <XAxis dataKey="distance_km" stroke="#8b949e" tickFormatter={v => v.toFixed(1)} />
                  <YAxis stroke="#8b949e" />
                  <Tooltip contentStyle={{ backgroundColor: '#161b22', borderColor: '#30363d', color: '#fff' }} labelFormatter={l => `Dist: ${Number(l).toFixed(2)} km`} />
                  <Line type="monotone" dataKey="h2_flow_lpm" name="H2 Flow (L/min)" stroke="#f97316" strokeWidth={2} dot={false} />
                </LineChart>
              </ChartCard>
            </>
          )}

          {!result && (
            <div className="bg-dark-card border border-dark-border rounded-xl p-12 text-center text-gray-500">
              Pick a vehicle & track and click "Run Simulation" to see the physics impact.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ResultCard({ label, value, unit, highlight }: { label: string; value?: number; unit: string; highlight?: boolean }) {
  return (
    <div className="bg-dark-card border border-dark-border rounded-xl p-5">
      <div className="text-xs text-gray-400 uppercase tracking-wider mb-2">{label}</div>
      <div className={`text-2xl font-bold ${highlight ? 'text-white' : 'text-gray-200'}`}>
        {value !== undefined ? value.toFixed(1) : '--'} <span className="text-sm text-gray-500">{unit}</span>
      </div>
    </div>
  )
}

function ChartCard({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactElement }) {
  return (
    <div className="bg-dark-card border border-dark-border rounded-xl p-6 min-h-[320px] flex flex-col">
      <h3 className="text-lg font-medium mb-4 flex items-center gap-2">{icon}{title}</h3>
      <div className="flex-1 w-full">
        <ResponsiveContainer width="100%" height="100%" minHeight={260}>
          {children}
        </ResponsiveContainer>
      </div>
    </div>
  )
}
