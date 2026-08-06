import { useEffect, useState } from 'react'
import { Mountain, RotateCw, Ruler, MapPinOff, TriangleAlert } from 'lucide-react'
import {
  AreaChart, Area, BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer,
} from 'recharts'
import { listTracks, getTrackAnalysis, type TrackDoc, type TrackAnalysisResponse } from '../api'
import { inputCls } from './ParamUI'

function StatCard({ label, value, unit, sub }: { label: string; value: string | number; unit?: string; sub?: string }) {
  return (
    <div className="bg-[#0d1117] border border-dark-border rounded-lg px-4 py-3">
      <div className="text-[11px] text-gray-500 uppercase tracking-wider mb-1">{label}</div>
      <div className="text-xl font-bold text-white">{value} {unit && <span className="text-xs text-gray-500">{unit}</span>}</div>
      {sub && <div className="text-[11px] text-gray-600 mt-0.5">{sub}</div>}
    </div>
  )
}

export default function TrackAnalysis() {
  const [tracks, setTracks] = useState<TrackDoc[]>([])
  const [trackId, setTrackId] = useState('')
  const [analysis, setAnalysis] = useState<TrackAnalysisResponse | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    listTracks().then(r => { setTracks(r.tracks); if (r.tracks.length) setTrackId(r.tracks[0].id) }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!trackId) return
    setLoading(true)
    getTrackAnalysis(trackId).then(setAnalysis).catch(() => setAnalysis(null)).finally(() => setLoading(false))
  }, [trackId])

  const el = analysis?.elevation
  const turns = analysis?.turns
  const width = analysis?.width

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <label className="text-sm font-medium text-gray-400">Track</label>
        <select className={`${inputCls} max-w-xs`} value={trackId} onChange={e => setTrackId(e.target.value)}>
          {tracks.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>

      <p className="text-[11px] text-gray-600 -mt-2">
        Sourced from the same per-point profile as <code>notebooks/Track_Analysis.ipynb</code> (turns via Kasa circle fitting, grade via spline over real GPS fixes, width via satellite corridor digitization) -- computed live off this track's own registered CSVs, not a frozen notebook snapshot.
      </p>

      {loading && <p className="text-sm text-gray-500">Loading analysis...</p>}

      {!loading && analysis && !analysis.available && (
        <div className="bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 rounded-lg px-4 py-3 text-sm flex items-center gap-2">
          <MapPinOff size={16} />
          No analysis available for this track{analysis.error ? `: ${analysis.error}` : ' -- check its coordinates/turns/edges CSVs are set in the Registry tab.'}
        </div>
      )}

      {!loading && analysis?.available && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard label="Lap Distance" value={analysis.lap_distance_km?.toFixed(3) ?? '--'} unit="km" />
            <StatCard label="Turns" value={turns?.count ?? '--'} sub={turns?.tightest_r_min_m != null ? `tightest R_min ${turns.tightest_r_min_m.toFixed(0)} m` : undefined} />
            <StatCard label="Max Uphill" value={el?.max_uphill_grade_pct != null ? `+${el.max_uphill_grade_pct.toFixed(2)}` : '--'} unit="%"
              sub={el?.max_uphill_km != null ? `@ ${el.max_uphill_km.toFixed(2)} km` : undefined} />
            <StatCard label="Max Downhill" value={el?.max_downhill_grade_pct != null ? el.max_downhill_grade_pct.toFixed(2) : '--'} unit="%"
              sub={el?.max_downhill_km != null ? `@ ${el.max_downhill_km.toFixed(2)} km` : undefined} />
          </div>

          {width && (width.min_m != null) && (
            <div className="grid grid-cols-3 gap-3">
              <StatCard label="Narrowest" value={width.min_m!.toFixed(1)} unit="m" />
              <StatCard label="Median Width" value={width.median_m!.toFixed(1)} unit="m" />
              <StatCard label="Widest" value={width.max_m!.toFixed(1)} unit="m" />
            </div>
          )}

          {el && el.profile.length > 0 && (
            <div className="bg-dark-card border border-dark-border rounded-xl p-6">
              <h3 className="text-lg font-medium mb-4 flex items-center gap-2"><Mountain size={16} className="text-brand-purple" />Elevation Profile</h3>
              <div className="h-[220px]">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={el.profile} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                    <XAxis dataKey="distance_km" stroke="#8b949e" tickFormatter={v => Number(v).toFixed(1)} />
                    <YAxis stroke="#8b949e" />
                    <Tooltip contentStyle={{ backgroundColor: '#161b22', borderColor: '#30363d', color: '#fff' }} labelFormatter={l => `Dist: ${Number(l).toFixed(2)} km`} />
                    <Area type="monotone" dataKey="altitude_m" name="Altitude (m)" stroke="#58a6ff" fill="#58a6ff" fillOpacity={0.2} isAnimationActive={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              <div className="h-[180px] mt-2">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={el.profile} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                    <XAxis dataKey="distance_km" stroke="#8b949e" tickFormatter={v => Number(v).toFixed(1)} />
                    <YAxis stroke="#8b949e" />
                    <Tooltip contentStyle={{ backgroundColor: '#161b22', borderColor: '#30363d', color: '#fff' }} labelFormatter={l => `Dist: ${Number(l).toFixed(2)} km`} />
                    <ReferenceLine y={0} stroke="#8b949e" />
                    <Bar dataKey="grade_pct" name="Grade (%)">
                      {el.profile.map((p, i) => (
                        <Cell key={i} fill={(p.grade_pct ?? 0) >= 0 ? '#3fb950' : '#f85149'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {turns && turns.list.length > 0 && (
            <div className="bg-dark-card border border-dark-border rounded-xl p-6">
              <h3 className="text-lg font-medium mb-4 flex items-center gap-2"><RotateCw size={16} className="text-blue-400" />Turns (Kasa circle fit)</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-gray-500 text-xs uppercase tracking-wider border-b border-dark-border">
                      <th className="py-2 pr-4">#</th>
                      <th className="py-2 pr-4">Start (km)</th>
                      <th className="py-2 pr-4">End (km)</th>
                      <th className="py-2 pr-4">R_min (m)</th>
                      <th className="py-2 pr-4">Safe Speed (km/h)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {turns.list.map((t, i) => (
                      <tr key={t.zone_id} className="border-b border-dark-border/50">
                        <td className="py-2 pr-4 text-gray-400">T{i + 1}</td>
                        <td className="py-2 pr-4">{t.start_km.toFixed(3)}</td>
                        <td className="py-2 pr-4">{t.end_km.toFixed(3)}</td>
                        <td className="py-2 pr-4">
                          {t.r_min_m != null ? (
                            <span className={t.r_min_m < 6 ? 'text-red-400 flex items-center gap-1' : ''}>
                              {t.r_min_m < 6 && <TriangleAlert size={12} />}{t.r_min_m.toFixed(1)}
                            </span>
                          ) : '--'}
                        </td>
                        <td className="py-2 pr-4">{t.v_safe_kmh_min != null ? t.v_safe_kmh_min.toFixed(1) : '--'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-[11px] text-gray-600 mt-3 flex items-center gap-1"><Ruler size={11} /> R_min below the Article 47 vehicle turning radius limit (6 m) is flagged -- the vehicle physically cannot hold the corridor centerline through that turn at any speed.</p>
            </div>
          )}

          {analysis.stops && analysis.stops.length > 0 && (
            <div className="bg-dark-card border border-dark-border rounded-xl p-6">
              <h3 className="text-lg font-medium mb-4">Mandatory Stops (Art. 227)</h3>
              <div className="flex gap-4 flex-wrap">
                {analysis.stops.map((s, i) => (
                  <div key={i} className="bg-[#0d1117] border border-dark-border rounded-lg px-4 py-2 text-sm">
                    <span className="text-yellow-400 font-semibold">Stop {i + 1}</span>
                    <span className="text-gray-500 ml-2">@ {s.distance_km.toFixed(2)} km</span>
                    <span className="text-gray-600 ml-2 font-mono text-xs">{s.latitude.toFixed(5)}, {s.longitude.toFixed(5)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
