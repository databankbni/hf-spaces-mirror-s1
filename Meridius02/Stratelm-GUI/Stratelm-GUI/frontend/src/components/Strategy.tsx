import { useEffect, useState } from 'react'
import { Trophy, Dna, Waves, Sigma, Gauge, Radio, MapPin, MapPinOff, Trash2, BarChart3, Fuel, Info, Sparkles, RefreshCw, Check } from 'lucide-react'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ZAxis, ReferenceDot,
} from 'recharts'
import {
  listAttempts, getAttemptChart, getAttemptSegments, getReferenceLines, deleteAttempt, cleanAndAssignLaps, getAttemptQCReport,
  type Attempt, type AttemptChartResponse, type AttemptChartPoint, type SegmentTarget, type ReferenceLinesResponse,
} from '../api'

const ALGO_META: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  mpc: { label: 'Model Predictive Control', icon: <Gauge size={14} />, color: '#ec4899' },
  dp: { label: 'DP (Physics-Optimal)', icon: <Sigma size={14} />, color: '#10b981' },
  ga: { label: 'Genetic Algorithm', icon: <Dna size={14} />, color: '#631acb' },
  pso: { label: 'Particle Swarm Optimization', icon: <Waves size={14} />, color: '#3b82f6' },
  cma: { label: 'CMA-ES', icon: <Sigma size={14} />, color: '#f59e0b' },
  fuzzy: { label: 'Fuzzy Logic TSK', icon: <Waves size={14} />, color: '#06b6d4' },
  cruise: { label: 'Flat Cruise', icon: <Gauge size={14} />, color: '#9ca3af' },
}

const STATE_COLOR: Record<string, string> = { gas: '#22c55e', glide: '#4b5563', brake: '#ef4444' }

function algoMeta(algo: string | null, sourceType?: string) {
  const key = algo ? algo.toLowerCase().trim() : ''
  if (key && ALGO_META[key]) return ALGO_META[key]
  if (algo) {
    const formatted = algo.toUpperCase() === 'CMA' ? 'CMA-ES' : algo.toUpperCase() === 'MPC' ? 'Model Predictive Control' : algo.charAt(0).toUpperCase() + algo.slice(1)
    return { label: formatted, icon: <Gauge size={14} />, color: '#38bdf8' }
  }
  if (sourceType === 'real') {
    return { label: 'Real Recording', icon: <Radio size={14} />, color: '#10b981' }
  }
  return { label: 'Simulated Strategy', icon: <Gauge size={14} />, color: '#9ca3af' }
}

interface StateRun { state: string; points: { latitude: number; longitude: number }[] }

// Recharts draws one color per <Line> -- to paint gas/glide/brake spatially on
// the track map, split the path into contiguous same-state runs and render
// each as its own colored segment, carrying the previous run's last point
// forward so the segments visually connect with no gaps.
function buildStateRuns(points: AttemptChartPoint[]): StateRun[] {
  const withGps = points.filter(p => p.latitude !== null && p.longitude !== null)
  const runs: StateRun[] = []
  for (const p of withGps) {
    const st = p.state ?? 'glide'
    const last = runs[runs.length - 1]
    const pt = { latitude: p.latitude as number, longitude: p.longitude as number }
    if (last && last.state === st) {
      last.points.push(pt)
    } else {
      const seed = last ? [last.points[last.points.length - 1], pt] : [pt]
      runs.push({ state: st, points: seed })
    }
  }
  return runs
}

export default function Strategy() {
  const [attempts, setAttempts] = useState<Attempt[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [chart, setChart] = useState<AttemptChartResponse | null>(null)
  const [selectedLap, setSelectedLap] = useState<number | null>(null)
  const [useRaw, setUseRaw] = useState<boolean>(false)
  const [segments, setSegments] = useState<SegmentTarget[] | null>(null)
  const [refLines, setRefLines] = useState<ReferenceLinesResponse | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [cleanModalOpen, setCleanModalOpen] = useState(false)
  const [cleanMode, setCleanMode] = useState<'gps' | 'time' | 'dist'>('gps')
  const [cleanStartTime, setCleanStartTime] = useState('')
  const [cleanDurations, setCleanDurations] = useState('')
  const [cleanLapDist, setCleanLapDist] = useState('')
  const [cleanStartLat, setCleanStartLat] = useState('25.4883')
  const [cleanStartLon, setCleanStartLon] = useState('51.4503')
  const [cleanProcessing, setCleanProcessing] = useState(false)
  const [cleanSuccessMsg, setCleanSuccessMsg] = useState<string | null>(null)

  const [qcModalOpen, setQcModalOpen] = useState(false)
  const [qcLoading, setQcLoading] = useState(false)
  const [qcData, setQcData] = useState<{ available: boolean; report?: Record<string, unknown>; error?: string; message?: string } | null>(null)

  const refresh = () => listAttempts().then(r => {
    setAttempts(r.attempts)
    if (!selectedId && r.attempts.length) setSelectedId(r.attempts[0].id)
  }).catch(e => setError(String(e)))

  useEffect(() => { refresh() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // reset to "all laps" whenever the selected attempt changes
  useEffect(() => { setSelectedLap(null); setUseRaw(false) }, [selectedId])

  useEffect(() => {
    if (!selectedId) return
    setLoadingDetail(true)
    setSegments(null)
    setRefLines(null)
    const attempt = attempts.find(a => a.id === selectedId)
    Promise.all([
      getAttemptChart(selectedId, selectedLap, useRaw),
      getAttemptSegments(selectedId),
      attempt?.track_id ? getReferenceLines(attempt.track_id) : Promise.resolve(null),
    ]).then(([chartRes, segRes, refRes]) => {
      setChart(chartRes)
      setSegments(segRes.available ? segRes.segments ?? null : null)
      setRefLines(refRes)
    }).catch(e => setError(String(e))).finally(() => setLoadingDetail(false))
  }, [selectedId, selectedLap, useRaw]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleOpenQCReport = async () => {
    if (!selectedId) return
    setQcModalOpen(true)
    setQcLoading(true)
    try {
      const res = await getAttemptQCReport(selectedId)
      setQcData(res)
    } catch (err) {
      setQcData({ available: false, error: String(err) })
    } finally {
      setQcLoading(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (id.startsWith('seed-')) return
    if (!confirm('Delete this attempt? This cannot be undone.')) return
    const res = await deleteAttempt(id)
    if (res.success) {
      if (selectedId === id) setSelectedId(null)
      refresh()
    }
  }

  const handleCleanAndAssign = async () => {
    if (!selectedId) return
    setCleanProcessing(true)
    setCleanSuccessMsg(null)
    try {
      const res = await cleanAndAssignLaps(selectedId, {
        durations: cleanDurations.trim() || undefined,
        lap_dist: cleanMode === 'dist' && cleanLapDist ? parseFloat(cleanLapDist) : undefined,
        use_gps: cleanMode === 'gps',
        start_lat: cleanMode === 'gps' && cleanStartLat ? parseFloat(cleanStartLat) : undefined,
        start_lon: cleanMode === 'gps' && cleanStartLon ? parseFloat(cleanStartLon) : undefined,
        start_time: cleanMode === 'time' && cleanStartTime.trim() ? cleanStartTime.trim() : undefined,
      })
      if (res.success) {
        setCleanSuccessMsg(`Cleaned telemetry & assigned ${res.laps_assigned?.length ?? 0} laps! (${res.total_rows} rows processed)`)
        setTimeout(() => {
          setCleanModalOpen(false)
          setCleanSuccessMsg(null)
          if (selectedId) {
            getAttemptChart(selectedId, selectedLap).then(setChart)
          }
        }, 1500)
      } else {
        setError(res.error ?? 'Clean and assign failed')
      }
    } catch (e) {
      setError(String(e))
    }
    setCleanProcessing(false)
  }

  const selected = attempts.find(a => a.id === selectedId)
  const hasCenterline = refLines?.centerline.available && refLines.centerline.points.length > 0
  const hasOptimum = refLines?.racing_line.available && refLines.racing_line.points.length > 0
  const stateRuns = chart ? buildStateRuns(chart.points) : []

  return (
    <div className="p-8 h-full overflow-y-auto">
      <div className="mb-8">
        <h2 className="text-3xl font-bold flex items-center gap-3"><Trophy className="text-brand-purple" />Lusail Urban Hydrogen Strategy</h2>
        <p className="text-gray-400">Saved runs — GA/PSO/CMA-ES search results, plain cruise baselines, and real recordings off the car</p>
      </div>

      {error && <div className="mb-6 bg-red-500/10 border border-red-500/30 text-red-400 rounded-lg px-4 py-3 text-sm">{error}</div>}

      <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
        {/* Attempts list */}
        <div className="xl:col-span-1 flex flex-col gap-3">
          {attempts.map(a => {
            const meta = algoMeta(a.algorithm, a.source_type)
            return (
              <div key={a.id} role="button" tabIndex={0} onClick={() => setSelectedId(a.id)}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') setSelectedId(a.id) }}
                className={`text-left bg-dark-card border rounded-xl p-4 transition-colors relative group cursor-pointer ${
                  selectedId === a.id ? 'border-brand-purple' : 'border-dark-border hover:border-gray-600'}`}>
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider mb-1" style={{ color: meta.color }}>
                  {meta.icon} {meta.label}
                  {a.source_type === 'real' && <span className="ml-auto text-[9px] bg-green-500/20 text-green-400 px-1.5 py-0.5 rounded">REAL</span>}
                </div>
                <div className="font-semibold text-white text-sm truncate">{a.name}</div>
                <div className="text-xs text-gray-500 mt-1">
                  {a.summary?.score_km_per_m3 !== undefined
                    ? <>{a.summary.score_km_per_m3.toFixed(1)} km/m³</>
                    : <>{a.summary?.row_count ?? 0} rows</>}
                </div>
                <div className="flex items-center gap-1 text-[10px] text-gray-600 mt-1">
                  {a.has_gps ? <MapPin size={10} /> : <MapPinOff size={10} />}
                  {a.has_gps ? 'GPS available' : 'no GPS'}
                </div>
                {!a.id.startsWith('seed-') && (
                  <button onClick={e => { e.stopPropagation(); handleDelete(a.id) }}
                    className="absolute top-3 right-3 text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            )
          })}
          {attempts.length === 0 && (
            <div className="bg-dark-card border border-dark-border rounded-xl p-6 text-center text-gray-500 text-sm">
              No saved runs yet. Run the optimizer or a cruise sim in the Sandbox, or record a session in Live Telemetry.
            </div>
          )}
        </div>

        {/* Detail */}
        <div className="xl:col-span-3 flex flex-col gap-6">
          {!selected && (
            <div className="bg-dark-card border border-dark-border rounded-xl p-12 text-center text-gray-500">
              Select a saved run to see its gas/glide map and racing line.
            </div>
          )}

          {selected && (
            <>
              <div className="bg-dark-card border border-dark-border rounded-xl p-5">
                <div className="flex items-center justify-between flex-wrap gap-3 mb-1">
                  <h3 className="text-xl font-bold">{selected.name}</h3>
                  <div className="flex items-center gap-2">
                    <button onClick={handleOpenQCReport}
                      className="bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 border border-blue-500/40 text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5">
                      <BarChart3 size={14} /> QC Report
                    </button>
                    <button onClick={() => setCleanModalOpen(true)}
                      className="bg-brand-purple/20 hover:bg-brand-purple/30 text-brand-purple border border-brand-purple/40 text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5">
                      <Sparkles size={14} /> Clean & Assign Laps
                    </button>
                    <span className="text-xs text-gray-500">{new Date(selected.created_at).toLocaleString()}</span>
                  </div>
                </div>
                <p className="text-xs text-gray-500 mb-4">{selected.vehicle_id ?? 'unknown vehicle'} · {selected.track_id ?? 'unknown track'}{selected.notes ? ` · ${selected.notes}` : ''}</p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <Stat label="Score" value={selected.summary?.score_km_per_m3?.toFixed(1)} unit="km/m³" />
                  <Stat label="H2 Total" value={selected.summary?.h2_total_l?.toFixed(1)} unit="L" />
                  <Stat label="Avg Speed" value={selected.summary?.avg_speed_kmh?.toFixed(1)} unit="km/h" />
                  <Stat label="Time" value={selected.summary?.total_time_min?.toFixed(1) ?? (selected.summary?.duration_s ? (selected.summary.duration_s / 60).toFixed(1) : undefined)} unit="min" />
                </div>
                {chart && (
                  <div className="flex items-center justify-between flex-wrap gap-2 mt-4 pt-4 border-t border-dark-border">
                    {chart.available_laps.length > 0 ? (
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-500 uppercase tracking-wider mr-1">Lap:</span>
                        <button onClick={() => setSelectedLap(null)}
                          className={`px-3 py-1 rounded-md text-xs font-medium border transition-colors ${
                            selectedLap === null ? 'bg-brand-purple/20 text-brand-purple border-brand-purple/50' : 'border-dark-border text-gray-400 hover:text-white'}`}>
                          All laps
                        </button>
                        {chart.available_laps.map(lap => (
                          <button key={lap} onClick={() => setSelectedLap(lap)}
                            className={`px-3 py-1 rounded-md text-xs font-medium border transition-colors ${
                              selectedLap === lap ? 'bg-brand-purple/20 text-brand-purple border-brand-purple/50' : 'border-dark-border text-gray-400 hover:text-white'}`}>
                            Lap {lap}
                          </button>
                        ))}
                      </div>
                    ) : <div />}

                    {chart.has_raw && (
                      <div className="flex items-center gap-1.5 bg-[#0d1117] p-1 rounded-lg border border-dark-border">
                        <button onClick={() => setUseRaw(false)}
                          className={`px-2.5 py-1 rounded text-xs font-semibold transition-colors flex items-center gap-1 ${
                            !useRaw ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 shadow' : 'text-gray-400 hover:text-white'}`}>
                          ✨ Cleaned
                        </button>
                        <button onClick={() => setUseRaw(true)}
                          className={`px-2.5 py-1 rounded text-xs font-semibold transition-colors flex items-center gap-1 ${
                            useRaw ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40 shadow' : 'text-gray-400 hover:text-white'}`}>
                          ⚡ Raw Sensor
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {cleanModalOpen && (
                <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
                  <div className="bg-dark-card border border-dark-border rounded-xl p-6 max-w-md w-full shadow-2xl">
                    <h3 className="text-lg font-bold flex items-center gap-2 mb-2">
                      <Sparkles className="text-brand-purple" size={18} /> Clean Telemetry & Assign Laps
                    </h3>
                    <p className="text-xs text-gray-400 mb-4">
                      Runs <code>clean_telemetry.py</code> to filter outliers and <code>assign_laps.py</code> to automatically flag Lap 1, Lap 2, Lap 3... based on GPS start-line returns or lap durations.
                    </p>

                    <div className="flex border-b border-dark-border mb-4">
                      <button onClick={() => setCleanMode('gps')}
                        className={`flex-1 py-2 text-xs font-semibold text-center border-b-2 transition-colors ${cleanMode === 'gps' ? 'border-brand-purple text-brand-purple' : 'border-transparent text-gray-400 hover:text-white'}`}>
                        📍 GPS Map Point
                      </button>
                      <button onClick={() => setCleanMode('time')}
                        className={`flex-1 py-2 text-xs font-semibold text-center border-b-2 transition-colors ${cleanMode === 'time' ? 'border-brand-purple text-brand-purple' : 'border-transparent text-gray-400 hover:text-white'}`}>
                        ⏱️ Logtime / WIB Time
                      </button>
                      <button onClick={() => setCleanMode('dist')}
                        className={`flex-1 py-2 text-xs font-semibold text-center border-b-2 transition-colors ${cleanMode === 'dist' ? 'border-brand-purple text-brand-purple' : 'border-transparent text-gray-400 hover:text-white'}`}>
                        📏 Distance
                      </button>
                    </div>

                    <div className="space-y-4 mb-6">
                      {cleanMode === 'gps' && (
                        <div>
                          <label className="block text-xs font-medium text-gray-400 mb-1">Track Start/Finish Line (Lat, Lon)</label>
                          <div className="grid grid-cols-2 gap-2">
                            <input className="bg-[#0d1117] border border-dark-border rounded px-3 py-1.5 text-xs text-white"
                              placeholder="Start Lat" value={cleanStartLat} onChange={e => setCleanStartLat(e.target.value)} />
                            <input className="bg-[#0d1117] border border-dark-border rounded px-3 py-1.5 text-xs text-white"
                              placeholder="Start Lon" value={cleanStartLon} onChange={e => setCleanStartLon(e.target.value)} />
                          </div>
                          <p className="text-[11px] text-gray-500 mt-1">Detects lap completions whenever the car passes near these coordinates.</p>
                        </div>
                      )}

                      {cleanMode === 'time' && (
                        <>
                          <div>
                            <label className="block text-xs font-medium text-gray-400 mb-1">Race Start Time (WIB / Local Timestamp)</label>
                            <input className="bg-[#0d1117] border border-dark-border rounded px-3 py-1.5 text-xs text-white w-full"
                              placeholder="e.g. 2026-07-13 08:05:00" value={cleanStartTime} onChange={e => setCleanStartTime(e.target.value)} />
                          </div>
                          <div>
                            <label className="block text-xs font-medium text-gray-400 mb-1">Lap Durations in Seconds</label>
                            <input className="bg-[#0d1117] border border-dark-border rounded px-3 py-1.5 text-xs text-white w-full"
                              placeholder="e.g. 512, 498, 505, 510" value={cleanDurations} onChange={e => setCleanDurations(e.target.value)} />
                          </div>
                        </>
                      )}

                      {cleanMode === 'dist' && (
                        <div>
                          <label className="block text-xs font-medium text-gray-400 mb-1">Track Lap Length / Distance (Meters)</label>
                          <input className="bg-[#0d1117] border border-dark-border rounded px-3 py-1.5 text-xs text-white w-full"
                            placeholder="e.g. 3700.0" value={cleanLapDist} onChange={e => setCleanLapDist(e.target.value)} />
                          <p className="text-[11px] text-gray-500 mt-1">Assigns +1 lap every time cumulative distance advances by this length.</p>
                        </div>
                      )}
                    </div>

                    {cleanSuccessMsg && (
                      <div className="mb-4 bg-green-500/10 border border-green-500/30 text-green-400 rounded-lg p-3 text-xs flex items-center gap-2">
                        <Check size={16} /> {cleanSuccessMsg}
                      </div>
                    )}

                    <div className="flex justify-end gap-3">
                      <button onClick={() => setCleanModalOpen(false)}
                        className="px-4 py-2 border border-dark-border text-gray-400 hover:text-white rounded-lg text-xs font-medium">
                        Cancel
                      </button>
                      <button onClick={handleCleanAndAssign} disabled={cleanProcessing}
                        className="px-4 py-2 bg-brand-purple hover:bg-brand-purple/80 text-white rounded-lg text-xs font-bold transition-colors flex items-center gap-1.5">
                        <RefreshCw size={14} className={cleanProcessing ? 'animate-spin' : ''} />
                        {cleanProcessing ? 'Processing...' : 'Run Clean & Assign'}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {qcModalOpen && (
                <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
                  <div className="bg-dark-card border border-dark-border rounded-xl p-6 max-w-xl w-full shadow-2xl">
                    <h3 className="text-lg font-bold flex items-center gap-2 mb-2">
                      <BarChart3 className="text-blue-400" size={18} /> Telemetry Quality Control (QC) Report
                    </h3>
                    <p className="text-xs text-gray-400 mb-4">
                      Outlier filtering & data cleaning statistics generated by <code>clean_telemetry.py</code>.
                    </p>

                    {qcLoading ? (
                      <div className="py-8 text-center text-xs text-gray-400 animate-pulse">Loading QC report metrics...</div>
                    ) : qcData && qcData.available && qcData.report ? (
                      <div className="space-y-4 mb-6">
                        <div className="bg-[#0d1117] border border-dark-border rounded-lg p-4 font-mono text-xs max-h-80 overflow-y-auto">
                          <pre className="text-gray-300 whitespace-pre-wrap">{JSON.stringify(qcData.report, null, 2)}</pre>
                        </div>
                      </div>
                    ) : (
                      <div className="bg-amber-500/10 border border-amber-500/30 text-amber-300 rounded-lg p-4 text-xs mb-6">
                        {qcData?.message || qcData?.error || 'No QC report found. Click "Clean & Assign Laps" to run quality control analysis.'}
                      </div>
                    )}

                    <div className="flex justify-end">
                      <button onClick={() => setQcModalOpen(false)}
                        className="px-4 py-2 bg-dark-border hover:bg-gray-700 text-white rounded-lg text-xs font-semibold">
                        Close
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {loadingDetail && <div className="text-gray-500 text-sm">Loading...</div>}

              {chart && chart.error && (
                <div className="bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 rounded-xl px-4 py-3 text-sm">{chart.error}</div>
              )}

              {chart && chart.points.length > 0 && (
                <div className="bg-dark-card border border-dark-border rounded-xl p-6">
                  <h3 className="text-lg font-medium mb-4 flex items-center gap-2"><Gauge size={16} className="text-brand-purple" />Speed Trace</h3>
                  <div className="h-[260px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={chart.points} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                        <XAxis dataKey={chart.points.some(p => p.distance_km !== null) ? 'distance_km' : 'index'}
                          stroke="#8b949e" tickFormatter={v => Number(v).toFixed(1)} />
                        <YAxis stroke="#8b949e" />
                        <Tooltip contentStyle={{ backgroundColor: '#161b22', borderColor: '#30363d', color: '#fff' }} />
                        <Line type="monotone" dataKey="speed_kmh" name="Speed (km/h)" stroke="#631acb" strokeWidth={1.5} dot={false} connectNulls isAnimationActive={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>

                </div>
              )}

              {chart && chart.points.length > 0 && (
                <div className="bg-dark-card border border-dark-border rounded-xl p-6">
                  <h3 className="text-lg font-medium mb-1 flex items-center gap-2">
                    <Fuel size={16} className="text-green-500" /> Gas/Glide Map
                  </h3>
                  <p className="text-[11px] text-gray-600 mb-4">
                    Where along the track this run burns (gas) vs coasts (glide) vs brakes{chart.state_is_derived ? ' — derived from power > 15 W, no direct sensor label in real telemetry' : ''}.
                    {chart.available_laps.length > 0 && selectedLap === null && ' Showing all 4 laps overlaid on one loop — pick a single lap above to see it cleanly.'}
                  </p>
                  {chart.state_available && chart.has_gps ? (
                    <>
                      <div className="h-[360px]">
                        <ResponsiveContainer width="100%" height="100%">
                          <LineChart margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
                            <XAxis type="number" dataKey="longitude" domain={['auto', 'auto']} stroke="#8b949e" tickFormatter={v => v.toFixed(3)} name="Longitude" />
                            <YAxis type="number" dataKey="latitude" domain={['auto', 'auto']} stroke="#8b949e" tickFormatter={v => v.toFixed(3)} name="Latitude" />
                            <ZAxis range={[1, 1]} />
                            {stateRuns.map((run, i) => (
                              <Line key={i} data={run.points} type="monotone" dataKey="latitude"
                                stroke={STATE_COLOR[run.state]} strokeWidth={3} dot={false} isAnimationActive={false} />
                            ))}
                            {refLines?.stops.map((s, i) => (
                              <ReferenceDot key={i} x={s.longitude} y={s.latitude} r={7}
                                fill="#facc15" stroke="#78350f" strokeWidth={1.5}
                                label={{ value: `Stop ${i + 1}`, position: 'top', fill: '#facc15', fontSize: 11 }}
                                ifOverflow="extendDomain" />
                            ))}
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                      <div className="flex gap-4 mt-3 text-[11px] text-gray-500">
                        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm inline-block" style={{ background: STATE_COLOR.gas }} />Gas (burning)</span>
                        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm inline-block" style={{ background: STATE_COLOR.glide }} />Glide (coasting)</span>
                        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm inline-block" style={{ background: STATE_COLOR.brake }} />Brake</span>
                        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full inline-block" style={{ background: '#facc15' }} />Mandatory stop</span>
                      </div>
                    </>
                  ) : !chart.has_gps ? (
                    <div className="bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 rounded-lg px-4 py-3 text-sm flex items-center gap-2">
                      <MapPinOff size={16} />
                      No GPS data available for this attempt — can't place gas/glide state on the map.
                    </div>
                  ) : (
                    <p className="text-xs text-gray-600">Gas/glide state not available for this run.</p>
                  )}
                </div>
              )}

              {segments && segments.length > 0 && (
                <div className="bg-dark-card border border-dark-border rounded-xl p-6">
                  <h3 className="text-lg font-medium mb-4 flex items-center gap-2"><BarChart3 size={16} className="text-brand-purple" />Per-Segment Gas/Glide Targets</h3>
                  <div className="h-[280px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={segments} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                        <XAxis dataKey="segment" stroke="#8b949e" />
                        <YAxis stroke="#8b949e" />
                        <Tooltip contentStyle={{ backgroundColor: '#161b22', borderColor: '#30363d', color: '#fff' }} />
                        <Legend />
                        <Bar dataKey="v_target_kmh" name="v_target (km/h, gas)" fill="#631acb" />
                        <Bar dataKey="v_coast_kmh" name="v_coast (km/h, glide)" fill="#30363d" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              <div className="bg-dark-card border border-dark-border rounded-xl p-6">
                <h3 className="text-lg font-medium mb-2 flex items-center gap-2"><MapPin size={16} className="text-brand-purple" />Racing Line</h3>

                {selected.source_type === 'simulated' && (
                  <div className="bg-blue-500/10 border border-blue-500/30 text-blue-300 rounded-lg px-4 py-2.5 text-xs flex items-start gap-2 mb-4">
                    <Info size={14} className="mt-0.5 flex-shrink-0" />
                    <span>
                      {selected.algorithm === 'ga' || selected.algorithm === 'pso' || selected.algorithm === 'cma'
                        ? <>{ALGO_META[selected.algorithm].label} only searches over per-segment <em>speed</em> (v_target/v_coast) — it does not choose a lateral path. This run's "path" below follows the fixed Shell GPS track backbone, same as every other simulated run; it will look identical regardless of which algorithm was used. Only a real GPS recording shows an actually-driven line.</>
                        : <>A flat cruise run follows the fixed Shell GPS track backbone, same as every simulated run — the path itself carries no strategy information here, only the speed profile does.</>}
                    </span>
                  </div>
                )}

                {!hasCenterline && !hasOptimum && !chart?.has_gps ? (
                  <div className="bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 rounded-lg px-4 py-3 text-sm flex items-center gap-2">
                    <MapPinOff size={16} />
                    No GPS data available for this attempt, and no reference lines computed for this track yet.
                  </div>
                ) : (
                  <>
                    {!chart?.has_gps && (
                      <div className="bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 rounded-lg px-4 py-2.5 text-xs flex items-center gap-2 mb-3">
                        <MapPinOff size={14} />
                        This attempt itself has no GPS fix — showing the track's reference lines only, no driven path.
                      </div>
                    )}
                    <div className="h-[380px]">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
                          <XAxis type="number" dataKey="longitude" domain={['auto', 'auto']} stroke="#8b949e" tickFormatter={v => v.toFixed(3)} name="Longitude" />
                          <YAxis type="number" dataKey="latitude" domain={['auto', 'auto']} stroke="#8b949e" tickFormatter={v => v.toFixed(3)} name="Latitude" />
                          <ZAxis range={[1, 1]} />
                          <Tooltip contentStyle={{ backgroundColor: '#161b22', borderColor: '#30363d', color: '#fff' }} />
                          <Legend />
                          {hasCenterline && (
                            <Line data={refLines!.centerline.points} type="monotone" dataKey="latitude" name="Track centerline"
                              stroke="#8b949e" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                          )}
                          {hasOptimum && (
                            <Line data={refLines!.racing_line.points} type="monotone" dataKey="latitude" name="Optimum racing line (QP)"
                              stroke="#10b981" strokeDasharray="4 3" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                          )}
                          {chart?.has_gps && (
                            <Line data={chart.points.filter(p => p.latitude !== null)} type="monotone" dataKey="latitude" name="This run's path"
                              stroke="#631acb" strokeWidth={2} dot={false} isAnimationActive={false} />
                          )}
                          {refLines?.stops.map((s, i) => (
                            <ReferenceDot key={i} x={s.longitude} y={s.latitude} r={7}
                              fill="#facc15" stroke="#78350f" strokeWidth={1.5}
                              label={{ value: `Stop ${i + 1}`, position: 'top', fill: '#facc15', fontSize: 11 }}
                              ifOverflow="extendDomain" />
                          ))}
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                    <p className="text-[11px] text-gray-600 mt-2">
                      Centerline = rebuilt corridor midline from the width digitization (<code>data/track_edges_imagery.csv</code>); optimum = shortest-path QP solve over that corridor (<code>data/racing_line.csv</code>) — both precomputed, not recalculated here. Yellow dots mark the 2 mandatory full-stop locations (Art. 226/227).
                    </p>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function Stat({ label, value, unit }: { label: string; value?: string; unit: string }) {
  return (
    <div className="bg-[#0d1117] border border-dark-border rounded-lg px-3 py-2">
      <div className="text-[10px] text-gray-500 uppercase tracking-wider">{label}</div>
      <div className="text-lg font-bold text-white">{value ?? '--'} <span className="text-xs text-gray-500">{unit}</span></div>
    </div>
  )
}
