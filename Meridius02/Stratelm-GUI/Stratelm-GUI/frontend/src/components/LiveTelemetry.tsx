import { useEffect, useRef, useState } from 'react'
import {
  Radio, Zap, Compass, Activity, ShieldAlert, Wind, Settings, Circle, Square, Save, Trash2,
  Plug, PlugZap, Play, Cpu, MapPin, MapPinOff, Eye, EyeOff, ListTree, Terminal, Navigation,
} from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import {
  WS_BASE, pickField, FIELD_ALIASES, type TelemetrySnapshot,
  configureTelemetry, connectTelemetry, disconnectTelemetry,
  startRecording, discardRecording, stopRecordingAndSave,
  listVehicles, listTracks, type VehicleSummary, type TrackDoc,
  startSimulator, stopSimulator, getSimulatorStatus, type SimulatorStatus,
  getReferenceLines, type ReferenceLinesResponse,
  setAdvisoryMode,
} from '../api'
import { inputCls } from './ParamUI'

const HISTORY_LIMIT = 120
const GPS_TRAIL_LIMIT = 12
const LOOKAHEAD_S_LABEL = '0.5' // mirrors backend's driver_advisory_bridge.LOOKAHEAD_S, for display only

interface HistoryPoint { t: number; velocity: number | null; powerW: number | null }
interface GpsPoint { latitude: number; longitude: number }

function StatusPill({ snapshot, wsOpen }: { snapshot: TelemetrySnapshot | null; wsOpen: boolean }) {
  let label = 'OFFLINE'
  let color = 'bg-gray-500'
  let dotColor = 'bg-gray-500'
  if (!wsOpen) {
    label = 'DASHBOARD DISCONNECTED'
    color = 'text-gray-400'
    dotColor = 'bg-gray-500'
  } else if (snapshot?.live) {
    label = 'LIVE'
    color = 'text-green-400'
    dotColor = 'bg-green-500 animate-pulse'
  } else if (snapshot?.broker_connected) {
    label = 'OFFLINE — LISTENING, NO CAR DATA'
    color = 'text-yellow-400'
    dotColor = 'bg-yellow-500'
  } else {
    label = 'OFFLINE — BROKER UNREACHABLE'
    color = 'text-red-400'
    dotColor = 'bg-red-500'
  }
  return (
    <div className="flex items-center gap-2">
      <div className={`w-2.5 h-2.5 rounded-full ${dotColor}`}></div>
      <span className={`text-sm font-bold tracking-wide ${color}`}>{label}</span>
    </div>
  )
}

function Metric({ label, value, unit }: { label: string; value: number | string | null; unit?: string }) {
  const display = value === null || value === undefined || value === ''
    ? '--'
    : typeof value === 'number' ? value.toFixed(value < 10 && value !== 0 ? 3 : 1) : String(value)
  return (
    <div className="bg-[#0d1117] border border-dark-border rounded-lg px-4 py-3">
      <div className="text-[11px] text-gray-500 uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-xl font-bold ${value === null ? 'text-gray-600' : 'text-white'}`}>
        {display} {unit && value !== null && <span className="text-xs text-gray-500">{unit}</span>}
      </div>
    </div>
  )
}

function Group({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="bg-dark-card border border-dark-border rounded-xl p-5">
      <h3 className="text-sm font-semibold mb-4 flex items-center gap-2 text-gray-300 uppercase tracking-wider">
        {icon}
        {title}
      </h3>
      <div className="grid grid-cols-2 xl:grid-cols-3 gap-3">{children}</div>
    </div>
  )
}

interface SvgTrackMapProps {
  centerline: { latitude: number; longitude: number }[]
  racingLine?: { latitude: number; longitude: number }[]
  stops?: { latitude: number; longitude: number; distance_km: number }[]
  gpsTrail: { latitude: number; longitude: number }[]
  carPosition: { latitude: number; longitude: number } | null
  carSpeed: number | null
  advisory: any | null
}

const TURN_COLOR = '#38bdf8'

function SvgTrackMap({ centerline, racingLine, stops, gpsTrail, carPosition, carSpeed, advisory }: SvgTrackMapProps) {
  const [showRacingLine, setShowRacingLine] = useState(true)

  if (!centerline || centerline.length === 0) {
    return (
      <div className="h-[360px] bg-[#0d1117] border border-dark-border rounded-xl flex items-center justify-center text-gray-500 text-sm">
        No track geometry available
      </div>
    )
  }

  let minLat = Infinity, maxLat = -Infinity, minLon = Infinity, maxLon = -Infinity
  for (const p of centerline) {
    if (p.latitude < minLat) minLat = p.latitude
    if (p.latitude > maxLat) maxLat = p.latitude
    if (p.longitude < minLon) minLon = p.longitude
    if (p.longitude > maxLon) maxLon = p.longitude
  }

  const midLat = (minLat + maxLat) / 2
  const cosLat = Math.cos((midLat * Math.PI) / 180)

  const lonSpan = (maxLon - minLon) * cosLat || 0.001
  const latSpan = (maxLat - minLat) || 0.001

  const padFrac = 0.08
  const paddedMinLon = minLon - (lonSpan / cosLat) * padFrac
  const paddedMaxLon = maxLon + (lonSpan / cosLat) * padFrac
  const paddedMinLat = minLat - latSpan * padFrac
  const paddedMaxLat = maxLat + latSpan * padFrac

  const totalWidth = 900
  const totalHeight = 400

  const mapX = (lon: number) => {
    const norm = (lon - paddedMinLon) / (paddedMaxLon - paddedMinLon)
    return norm * totalWidth
  }

  const mapY = (lat: number) => {
    const norm = (lat - paddedMinLat) / (paddedMaxLat - paddedMinLat)
    return totalHeight - (norm * totalHeight)
  }

  const centerlineD = centerline.length > 0
    ? 'M ' + centerline.map(p => `${mapX(p.longitude).toFixed(1)},${mapY(p.latitude).toFixed(1)}`).join(' L ')
    : ''

  const racingLineD = (racingLine && racingLine.length > 0)
    ? 'M ' + racingLine.map(p => `${mapX(p.longitude).toFixed(1)},${mapY(p.latitude).toFixed(1)}`).join(' L ')
    : ''

  const trailPointsString = gpsTrail.map(p => `${mapX(p.longitude).toFixed(1)},${mapY(p.latitude).toFixed(1)}`).join(' ')

  const na = advisory?.next_action
  let advisoryPoint: { latitude: number; longitude: number } | null = null

  if (na?.latitude && na?.longitude) {
    advisoryPoint = { latitude: na.latitude, longitude: na.longitude }
  } else if (na?.s_m != null && centerline.length > 0) {
    // Fallback only: the backend now reports real latitude/longitude for
    // next_action, so this coarse index-proportion guess is just a safety
    // net for an older/incompatible advisory table.
    const totalDistM = 3630
    const sMod = ((na.s_m % totalDistM) + totalDistM) % totalDistM
    const idx = Math.min(centerline.length - 1, Math.floor((sMod / totalDistM) * centerline.length))
    advisoryPoint = centerline[idx]
  }

  const nt = advisory?.next_turn
  const turnPoint: { latitude: number; longitude: number } | null =
    (nt?.turn_no != null && nt?.latitude && nt?.longitude) ? { latitude: nt.latitude, longitude: nt.longitude } : null

  const carX = carPosition ? mapX(carPosition.longitude) : null
  const carY = carPosition ? mapY(carPosition.latitude) : null

  const advX = advisoryPoint ? mapX(advisoryPoint.longitude) : null
  const advY = advisoryPoint ? mapY(advisoryPoint.latitude) : null

  const turnX = turnPoint ? mapX(turnPoint.longitude) : null
  const turnY = turnPoint ? mapY(turnPoint.latitude) : null

  const actionColor = na?.action === 'brake' ? '#ef4444' : na?.action === 'glide' ? '#f59e0b' : '#3b82f6'

  let advisorySegmentPath = ''
  if (carPosition && advisoryPoint && centerline.length > 0 && na?.action && na.action !== 'ok') {
    let carIdx = 0, minCarDist = Infinity
    let advIdx = 0, minAdvDist = Infinity
    centerline.forEach((p, idx) => {
      const dCar = Math.hypot(p.latitude - carPosition.latitude, p.longitude - carPosition.longitude)
      const dAdv = Math.hypot(p.latitude - advisoryPoint.latitude, p.longitude - advisoryPoint.longitude)
      if (dCar < minCarDist) { minCarDist = dCar; carIdx = idx }
      if (dAdv < minAdvDist) { minAdvDist = dAdv; advIdx = idx }
    })

    let segmentPts: { latitude: number; longitude: number }[] = []
    if (carIdx <= advIdx) {
      segmentPts = centerline.slice(carIdx, advIdx + 1)
    } else {
      segmentPts = [...centerline.slice(carIdx), ...centerline.slice(0, advIdx + 1)]
    }

    if (segmentPts.length > 1) {
      advisorySegmentPath = 'M ' + segmentPts.map(p => `${mapX(p.longitude).toFixed(1)},${mapY(p.latitude).toFixed(1)}`).join(' L ')
    }
  }

  return (
    <div className="relative bg-[#0d1117] border border-dark-border rounded-xl p-4 overflow-hidden">
      <div className="absolute top-4 right-4 z-10 flex items-center gap-2 bg-dark-card/90 backdrop-blur border border-dark-border px-3 py-1.5 rounded-lg text-xs">
        {racingLine && racingLine.length > 0 && (
          <label className="flex items-center gap-1.5 text-gray-300 cursor-pointer">
            <input type="checkbox" checked={showRacingLine} onChange={e => setShowRacingLine(e.target.checked)} className="rounded" />
            <span className="text-[11px]">Racing Line</span>
          </label>
        )}
      </div>

      <svg viewBox={`0 0 ${totalWidth} ${totalHeight}`} className="w-full h-[360px] select-none">
        <defs>
          <filter id="glow-purple" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        <path d={centerlineD} fill="none" stroke="#1f2937" strokeWidth="16" strokeLinecap="round" strokeLinejoin="round" />
        <path d={centerlineD} fill="none" stroke="#475569" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />

        {showRacingLine && racingLineD && (
          <path d={racingLineD} fill="none" stroke="#3b82f6" strokeWidth="2" strokeDasharray="6 3" strokeLinecap="round" strokeLinejoin="round" opacity="0.6" />
        )}

        {stops?.map((stop, idx) => {
          const sx = mapX(stop.longitude)
          const sy = mapY(stop.latitude)
          return (
            <g key={idx} transform={`translate(${sx}, ${sy})`}>
              <circle r="9" fill="#eab308" opacity="0.2" className="animate-ping" />
              <circle r="6" fill="#eab308" stroke="#000000" strokeWidth="1.5" />
              <text y="-10" textAnchor="middle" fill="#eab308" fontSize="10" fontWeight="bold">
                STOP #{idx + 1}
              </text>
            </g>
          )
        })}

        {/* GPS Recent Trail — short, sleek path immediately behind car */}
        {gpsTrail.length > 1 && (
          <>
            <polyline points={trailPointsString} fill="none" stroke="#a855f7" strokeWidth="8" opacity="0.25" filter="url(#glow-purple)" strokeLinecap="round" strokeLinejoin="round" />
            <polyline points={trailPointsString} fill="none" stroke="#c084fc" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" />
          </>
        )}

        {/* Glowing connector path following the track corridor from Car to Advisory Target Point */}
        {advisorySegmentPath ? (
          <>
            <path d={advisorySegmentPath} fill="none" stroke={actionColor} strokeWidth="8" opacity="0.3" strokeLinecap="round" strokeLinejoin="round" />
            <path d={advisorySegmentPath} fill="none" stroke={actionColor} strokeWidth="3.5" strokeDasharray="6 3" strokeLinecap="round" strokeLinejoin="round" />
          </>
        ) : carX !== null && carY !== null && advX !== null && advY !== null && na?.action && na.action !== 'ok' ? (
          <line x1={carX} y1={carY} x2={advX} y2={advY} stroke={actionColor} strokeWidth="2" strokeDasharray="4 4" opacity="0.8" />
        ) : null}

        {/* Advisory Target Point Marker on the Track Map */}
        {advX !== null && advY !== null && na?.action && na.action !== 'ok' && (
          <g transform={`translate(${advX}, ${advY})`}>
            <circle r="14" fill={actionColor} opacity="0.3" className="animate-ping" />
            <circle r="8" fill={actionColor} stroke="#ffffff" strokeWidth="2" />
            <g transform="translate(0, -22)">
              <rect x="-70" y="-12" width="140" height="24" rx="6" fill="#161b22" stroke={actionColor} strokeWidth="1.5" />
              <text textAnchor="middle" y="4" fill="#ffffff" fontSize="11" fontWeight="bold">
                🎯 {na.action.toUpperCase()} @ {na.target_speed_kmh?.toFixed(0)} km/h ({na.distance_m?.toFixed(0)}m)
              </text>
            </g>
          </g>
        )}

        {/* Next Turn Marker -- independent of next_action/glide-ceiling, always
            shows the nearest upcoming corner regardless of whether current
            speed already satisfies it (real corner v_safe values are far above
            any speed this car reaches, so the ceiling above rarely fires on a
            turn -- this marker is what actually answers "where's the next turn") */}
        {turnX !== null && turnY !== null && nt?.turn_no != null && (
          <g transform={`translate(${turnX}, ${turnY})`}>
            <circle r="12" fill={TURN_COLOR} opacity="0.25" className="animate-ping" />
            <circle r="7" fill={TURN_COLOR} stroke="#ffffff" strokeWidth="2" />
            <g transform="translate(0, -22)">
              <rect x="-62" y="-12" width="124" height="24" rx="6" fill="#161b22" stroke={TURN_COLOR} strokeWidth="1.5" />
              <text textAnchor="middle" y="4" fill="#ffffff" fontSize="11" fontWeight="bold">
                ↷ Turn {nt.turn_no} @ {nt.target_speed_kmh?.toFixed(0)} km/h ({nt.distance_m?.toFixed(0)}m)
              </text>
            </g>
          </g>
        )}

        {/* Car Position Marker */}
        {carX !== null && carY !== null && (
          <g transform={`translate(${carX}, ${carY})`}>
            <circle r="12" fill="#22c55e" opacity="0.3" className="animate-ping" />
            <circle r="6.5" fill="#22c55e" stroke="#ffffff" strokeWidth="2" />
            <g transform="translate(0, 22)">
              <rect x="-45" y="-10" width="90" height="20" rx="4" fill="#0d1117" stroke="#22c55e" strokeWidth="1" />
              <text textAnchor="middle" y="3" fill="#22c55e" fontSize="11" fontWeight="bold">
                CAR {carSpeed !== null ? `(${carSpeed.toFixed(0)} km/h)` : ''}
              </text>
            </g>
          </g>
        )}
      </svg>

      <div className="flex items-center justify-between text-[11px] text-gray-400 mt-2 px-1 border-t border-dark-border/50 pt-2 flex-wrap gap-2">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-green-500"></span> Car Position</span>
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-purple-400"></span> Recent GPS Path</span>
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-amber-500"></span> Advisory Target Point</span>
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-sky-400"></span> Next Turn</span>
        </div>
        <div>
          {na?.action && na.action !== 'ok' && (
            <span className="text-amber-400 font-mono">
              Target Point: {na.distance_m?.toFixed(0)}m ahead (Station s = {na.s_m?.toFixed(0)}m)
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

export default function LiveTelemetry() {
  const [snapshot, setSnapshot] = useState<TelemetrySnapshot | null>(null)
  const [wsOpen, setWsOpen] = useState(false)
  const [history, setHistory] = useState<HistoryPoint[]>([])
  const startRef = useRef<number>(Date.now())

  const [configOpen, setConfigOpen] = useState(false)
  const [cfgBrokerHost, setCfgBrokerHost] = useState('')
  const [cfgBrokerPort, setCfgBrokerPort] = useState(1883)
  const [cfgCarTopic, setCfgCarTopic] = useState('')
  const [cfgGpsTopic, setCfgGpsTopic] = useState('')
  const [cfgQos, setCfgQos] = useState(1)
  const [applying, setApplying] = useState(false)

  const [vehicles, setVehicles] = useState<VehicleSummary[]>([])
  const [tracks, setTracks] = useState<TrackDoc[]>([])
  const [saveOpen, setSaveOpen] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [saveVehicleId, setSaveVehicleId] = useState('')
  const [saveTrackId, setSaveTrackId] = useState('')
  const [saveNotes, setSaveNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedMsg, setSavedMsg] = useState<string | null>(null)

  const [simStatus, setSimStatus] = useState<SimulatorStatus | null>(null)
  const [simGps, setSimGps] = useState(true)
  const [simTrackId, setSimTrackId] = useState('')
  const [simBusy, setSimBusy] = useState(false)
  const [simError, setSimError] = useState<string | null>(null)

  const [refLines, setRefLines] = useState<ReferenceLinesResponse | null>(null)
  const [gpsTrail, setGpsTrail] = useState<GpsPoint[]>([])

  const [paramsOpen, setParamsOpen] = useState(false)
  const [hiddenParams, setHiddenParams] = useState<Set<string>>(new Set())
  const [showRaw, setShowRaw] = useState(false)

  const [advisoryModeBusy, setAdvisoryModeBusy] = useState(false)
  const advisoryMode = snapshot?.advisory?.advisory_mode ?? null

  useEffect(() => {
    let ws: WebSocket
    let cancelled = false
    const connect = () => {
      if (cancelled) return
      ws = new WebSocket(`${WS_BASE}/ws/telemetry`)
      ws.onopen = () => setWsOpen(true)
      ws.onclose = () => {
        setWsOpen(false)
        if (!cancelled) setTimeout(connect, 2000)
      }
      ws.onerror = () => ws.close()
      ws.onmessage = (event) => {
        const data: TelemetrySnapshot = JSON.parse(event.data)
        setSnapshot(data)
        const v = pickField(data.latest, 'velocity')
        const p = pickField(data.latest, 'powerW')
        setHistory(prev => {
          const next = [...prev, {
            t: Math.round((Date.now() - startRef.current) / 1000),
            velocity: typeof v === 'number' ? v : null,
            powerW: typeof p === 'number' ? p : null,
          }]
          return next.length > HISTORY_LIMIT ? next.slice(next.length - HISTORY_LIMIT) : next
        })
        const lat = pickField(data.latest, 'latitude')
        const lon = pickField(data.latest, 'longitude')
        if (typeof lat === 'number' && typeof lon === 'number') {
          setGpsTrail(prev => {
            const next = [...prev, { latitude: lat, longitude: lon }]
            return next.length > GPS_TRAIL_LIMIT ? next.slice(next.length - GPS_TRAIL_LIMIT) : next
          })
        }
      }
    }
    connect()
    return () => { cancelled = true; ws?.close() }
  }, [])

  useEffect(() => {
    listVehicles().then(r => { setVehicles(r.vehicles); if (r.vehicles.length) setSaveVehicleId(r.vehicles[0].id) }).catch(() => {})
    listTracks().then(r => {
      setTracks(r.tracks)
      if (r.tracks.length) { setSaveTrackId(r.tracks[0].id); setSimTrackId(r.tracks[0].id) }
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!simTrackId) { setRefLines(null); return }
    let cancelled = false
    getReferenceLines(simTrackId).then(r => { if (!cancelled) setRefLines(r) }).catch(() => { if (!cancelled) setRefLines(null) })
    setGpsTrail([])
    return () => { cancelled = true }
  }, [simTrackId])

  useEffect(() => {
    let cancelled = false
    const poll = () => getSimulatorStatus().then(s => { if (!cancelled) setSimStatus(s) }).catch(() => {})
    poll()
    const id = setInterval(poll, 3000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  const lastSimPid = useRef<number | null>(null)
  useEffect(() => {
    const pid = simStatus?.running ? simStatus.pid : null
    if (pid !== null && pid !== lastSimPid.current) {
      setGpsTrail([])
      setHistory([])
      startRef.current = Date.now()
    }
    lastSimPid.current = pid
  }, [simStatus])

  const handleStartSimulator = async () => {
    setSimBusy(true)
    setSimError(null)
    try {
      const res = await startSimulator(simGps, simGps ? simTrackId : undefined)
      if (!res.success) setSimError(res.error ?? 'failed to start simulator')
      setSimStatus(res)
    } catch (e) {
      setSimError(String(e))
    }
    setSimBusy(false)
  }

  const handleStopSimulator = async () => {
    setSimBusy(true)
    setSimError(null)
    try {
      const res = await stopSimulator()
      if (!res.success) setSimError(res.error ?? 'failed to stop simulator')
      setSimStatus(res)
    } catch (e) {
      setSimError(String(e))
    }
    setSimBusy(false)
  }

  useEffect(() => {
    if (snapshot && !configOpen && cfgBrokerHost === '') {
      setCfgBrokerHost(snapshot.broker_host)
      setCfgBrokerPort(snapshot.broker_port)
      setCfgCarTopic(snapshot.car_topic)
      setCfgGpsTopic(snapshot.gps_topic)
      setCfgQos(snapshot.qos)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshot])

  const latest = snapshot?.latest ?? {}
  const g = (key: string) => pickField(latest, key)
  const numOrNull = (v: number | string | null) => typeof v === 'number' ? v : null
  const hasCenterline = !!refLines?.centerline.available && refLines.centerline.points.length > 0
  const normalizeKey = (k: string) => k.toLowerCase().replace(/[^a-z0-9]/g, '')
  const knownAliasSet = new Set(Object.values(FIELD_ALIASES).flat().map(normalizeKey))
  const rawExtraKeys = Object.keys(latest).filter(k => !knownAliasSet.has(normalizeKey(k)))

  const handleApplyReconnect = async () => {
    setApplying(true)
    try {
      await configureTelemetry({
        broker_host: cfgBrokerHost, broker_port: cfgBrokerPort,
        car_topic: cfgCarTopic, gps_topic: cfgGpsTopic, qos: cfgQos,
      })
      await connectTelemetry()
    } catch { /* status will show via ws */ }
    setApplying(false)
  }

  const handleSetAdvisoryMode = async (mode: 'dynamic' | 'ga_strict') => {
    if (advisoryModeBusy || advisoryMode === mode) return
    setAdvisoryModeBusy(true)
    try {
      await setAdvisoryMode(mode)
      // next websocket tick's snapshot.advisory.advisory_mode reflects the change --
      // no local state to update here, it's derived straight from the snapshot.
    } catch {
      // leave mode as-is; the button simply won't visually flip if this failed
    } finally {
      setAdvisoryModeBusy(false)
    }
  }

  const handleDisconnect = () => { disconnectTelemetry().catch(() => {}) }
  const handleStartRecording = () => { setSavedMsg(null); startRecording().catch(() => {}) }
  const handleDiscard = () => { discardRecording().catch(() => {}); setSaveOpen(false) }

  const handleStopClick = () => {
    setSaveName(`Attempt ${new Date().toLocaleString()}`)
    setSaveError(null)
    setSaveOpen(true)
  }

  const handleConfirmSave = async () => {
    setSaving(true)
    setSaveError(null)
    try {
      const res = await stopRecordingAndSave({
        name: saveName, vehicle_id: saveVehicleId || undefined, track_id: saveTrackId || undefined, notes: saveNotes,
      })
      if (res.success) {
        setSaveOpen(false)
        setSavedMsg(`Saved "${res.attempt?.name}" — view it in the Strategy tab.`)
      } else {
        setSaveError(res.error ?? 'save failed')
      }
    } catch (e) {
      setSaveError(String(e))
    }
    setSaving(false)
  }

  const currentLat = numOrNull(g('latitude'))
  const currentLon = numOrNull(g('longitude'))
  const currentCarPos = (currentLat !== null && currentLon !== null) ? { latitude: currentLat, longitude: currentLon } : (gpsTrail.length > 0 ? gpsTrail[gpsTrail.length - 1] : null)
  const currentVelocity = numOrNull(g('velocity'))

  return (
    <div className="p-8 h-full flex flex-col overflow-y-auto">
      <div className="flex flex-wrap justify-between items-end gap-4 mb-6">
        <div>
          <h2 className="text-3xl font-bold flex items-center gap-3">
            <Radio className="text-brand-purple" />
            Live Telemetry
          </h2>
          <p className="text-gray-400">Real-time driver data & MQTT feed — currently offline, waiting for the car</p>
        </div>
        <div className="bg-dark-card border border-dark-border px-5 py-3 rounded-xl">
          <StatusPill snapshot={snapshot} wsOpen={wsOpen} />
          <div className="text-xs text-gray-500 mt-1 font-mono">
            {snapshot?.broker ?? '--'} · qos {snapshot?.qos ?? '--'} · car: {snapshot?.car_topic ?? '--'} · gps: {snapshot?.gps_topic ?? '--'}
          </div>
        </div>
      </div>

      {/* MQTT config panel */}
      <div className="bg-dark-card border border-dark-border rounded-xl mb-6">
        <button onClick={() => setConfigOpen(o => !o)} className="w-full flex items-center justify-between px-5 py-3">
          <span className="text-sm font-semibold flex items-center gap-2 text-gray-300 uppercase tracking-wider">
            <Settings size={14} /> MQTT Configuration
          </span>
          <span className="text-xs text-gray-500">{configOpen ? 'hide' : 'show'}</span>
        </button>
        {configOpen && (
          <div className="px-5 pb-5">
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-4 mb-4">
              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1">Broker Host</label>
                <input className={inputCls} value={cfgBrokerHost} onChange={e => setCfgBrokerHost(e.target.value)} />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1">Broker Port</label>
                <input type="number" className={inputCls} value={cfgBrokerPort} onChange={e => setCfgBrokerPort(parseInt(e.target.value, 10))} />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1">Car Topic</label>
                <input className={inputCls} value={cfgCarTopic} onChange={e => setCfgCarTopic(e.target.value)} />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1">GPS Topic</label>
                <input className={inputCls} value={cfgGpsTopic} onChange={e => setCfgGpsTopic(e.target.value)} />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1">QoS</label>
                <select className={inputCls} value={cfgQos} onChange={e => setCfgQos(parseInt(e.target.value, 10))}>
                  <option value={1}>1 — reliable (at-least-once)</option>
                  <option value={0}>0 — fast (fire-and-forget)</option>
                </select>
              </div>
            </div>
            <div className="flex gap-3">
              <button onClick={handleApplyReconnect} disabled={applying}
                className="bg-brand-purple hover:bg-brand-purple/80 text-white text-sm font-bold px-5 py-2 rounded-lg transition-colors flex items-center gap-2">
                <PlugZap size={16} /> {applying ? 'Applying...' : 'Apply & Reconnect'}
              </button>
              <button onClick={handleDisconnect}
                className="bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 text-red-400 text-sm font-bold px-5 py-2 rounded-lg transition-colors flex items-center gap-2">
                <Plug size={16} /> Disconnect
              </button>
            </div>
            <p className="text-[11px] text-gray-600 mt-2">Car and GPS are separate MQTT publishers/topics on the real rig — configure them independently. QoS applies to both subscriptions (matches the logger's own qos1/qos0 script variants).</p>
          </div>
        )}
      </div>

      {/* Field simulator control */}
      <div className="bg-dark-card border border-dark-border rounded-xl p-5 mb-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="text-sm font-semibold flex items-center gap-2 text-gray-300 uppercase tracking-wider">
              <Cpu size={14} /> Field Simulator
            </span>
            {simStatus?.running ? (
              <>
                <div className="flex items-center gap-2 text-green-400 text-sm font-bold">
                  <Circle size={10} fill="currentColor" className="animate-pulse" />
                  RUNNING {simStatus.running_seconds.toFixed(0)}s · pid {simStatus.pid} · {simStatus.gps ? `GPS: ${tracks.find(t => t.id === simStatus.track_id)?.name ?? simStatus.track_id ?? 'default track'}` : 'no GPS'}
                </div>
                <button onClick={handleStopSimulator} disabled={simBusy}
                  className="bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 text-red-400 text-sm font-bold px-4 py-2 rounded-lg transition-colors flex items-center gap-2">
                  <Square size={14} /> {simBusy ? 'Stopping...' : 'Stop Simulator'}
                </button>
              </>
            ) : (
              <>
                <label className="flex items-center gap-2 text-xs text-gray-400">
                  <input type="checkbox" checked={simGps} onChange={e => setSimGps(e.target.checked)} /> include GPS
                </label>
                {simGps && (
                  <select className={`${inputCls} !w-auto text-xs py-1.5`} value={simTrackId} onChange={e => setSimTrackId(e.target.value)}>
                    {tracks.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                  </select>
                )}
                <button onClick={handleStartSimulator} disabled={simBusy}
                  className="bg-brand-purple hover:bg-brand-purple/80 text-white text-sm font-bold px-4 py-2 rounded-lg transition-colors flex items-center gap-2">
                  <Play size={14} /> {simBusy ? 'Starting...' : 'Start Simulator'}
                </button>
              </>
            )}
          </div>
          <p className="text-[11px] text-gray-600 max-w-md">Launches/kills mqtt/simulate_field.py as a managed subprocess publishing synthetic car (and optionally GPS) data to this broker — off by default, so nothing runs unless you press Start.</p>
        </div>
        {simError && <p className="mt-2 text-sm text-red-400">{simError}</p>}
      </div>

      {/* Recording controls */}
      <div className="bg-dark-card border border-dark-border rounded-xl p-5 mb-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            {!snapshot?.recording ? (
              <button onClick={handleStartRecording}
                className="bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 text-red-400 text-sm font-bold px-5 py-2.5 rounded-lg transition-colors flex items-center gap-2">
                <Circle size={14} fill="currentColor" /> Start Recording
              </button>
            ) : (
              <>
                <div className="flex items-center gap-2 text-red-400 text-sm font-bold">
                  <Circle size={10} fill="currentColor" className="animate-pulse" />
                  REC {snapshot.recording_seconds.toFixed(0)}s · {snapshot.recorded_row_count} rows
                </div>
                <button onClick={handleStopClick}
                  className="bg-brand-purple hover:bg-brand-purple/80 text-white text-sm font-bold px-4 py-2 rounded-lg transition-colors flex items-center gap-2">
                  <Square size={14} /> Stop & Save
                </button>
                <button onClick={handleDiscard}
                  className="border border-dark-border text-gray-400 hover:text-white text-sm px-4 py-2 rounded-lg transition-colors flex items-center gap-2">
                  <Trash2 size={14} /> Discard
                </button>
              </>
            )}
          </div>
          <p className="text-[11px] text-gray-600 max-w-md">Recording buffers every message from both topics; on Stop & Save, mqtt/clean_telemetry.py's cleaner runs immediately over the captured session before it's registered as an Attempt.</p>
        </div>

        {saveOpen && (
          <div className="mt-4 pt-4 border-t border-dark-border grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            <div className="xl:col-span-2">
              <label className="block text-xs font-medium text-gray-400 mb-1">Attempt Name</label>
              <input className={inputCls} value={saveName} onChange={e => setSaveName(e.target.value)} />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1">Vehicle</label>
              <select className={inputCls} value={saveVehicleId} onChange={e => setSaveVehicleId(e.target.value)}>
                {vehicles.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1">Track</label>
              <select className={inputCls} value={saveTrackId} onChange={e => setSaveTrackId(e.target.value)}>
                {tracks.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </div>
            <div className="xl:col-span-4">
              <label className="block text-xs font-medium text-gray-400 mb-1">Notes</label>
              <input className={inputCls} value={saveNotes} onChange={e => setSaveNotes(e.target.value)} />
            </div>
            {saveError && <div className="xl:col-span-4 text-sm text-red-400">{saveError}</div>}
            <div className="xl:col-span-4 flex gap-3">
              <button onClick={handleConfirmSave} disabled={saving}
                className="bg-brand-purple hover:bg-brand-purple/80 text-white text-sm font-bold px-5 py-2 rounded-lg transition-colors flex items-center gap-2">
                <Save size={16} /> {saving ? 'Cleaning & Saving...' : 'Confirm Save'}
              </button>
              <button onClick={() => setSaveOpen(false)} className="text-gray-400 hover:text-white text-sm px-4 py-2">Cancel</button>
            </div>
          </div>
        )}
        {savedMsg && <p className="mt-3 text-sm text-green-400">{savedMsg}</p>}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6 text-xs">
        {snapshot?.topics.map(t => (
          <div key={t} className="bg-dark-card border border-dark-border rounded-lg px-4 py-2 flex justify-between items-center">
            <span className="font-mono text-gray-400">{t}</span>
            <span className="text-gray-300">
              {snapshot.message_counts[t] ?? 0} msgs
              {snapshot.last_message_age_s[t] != null && ` · ${snapshot.last_message_age_s[t]}s ago`}
            </span>
          </div>
        ))}
      </div>

      {/* 2D Track Map Component */}
      <div className="bg-dark-card border border-dark-border rounded-xl p-6 mb-6">
        <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
          <MapPin className="text-brand-purple" size={18} />
          Track Map
        </h3>
        {!simTrackId ? (
          <div className="bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 rounded-lg px-4 py-3 text-sm flex items-center gap-2">
            <MapPinOff size={16} /> No track selected — pick one in the Field Simulator panel above (or wire a real GPS feed via MQTT Configuration).
          </div>
        ) : !hasCenterline ? (
          <div className="bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 rounded-lg px-4 py-3 text-sm flex items-center gap-2">
            <MapPinOff size={16} /> No reference centerline computed yet for this track.
          </div>
        ) : (
          <SvgTrackMap
            centerline={refLines!.centerline.points}
            racingLine={refLines!.racing_line.points}
            stops={refLines!.stops}
            gpsTrail={gpsTrail}
            carPosition={currentCarPos}
            carSpeed={currentVelocity}
            advisory={snapshot?.advisory ?? null}
          />
        )}
      </div>

      {/* Driver Advisory Panel */}
      <div className="bg-dark-card border border-dark-border rounded-xl p-6 mb-6">
        <h3 className="text-lg font-medium mb-4 flex items-center justify-between flex-wrap gap-2">
          <span className="flex items-center gap-2">
            <Navigation className="text-brand-purple" size={18} />
            Driver Advisory
          </span>
          <div className="flex items-center gap-2">
            <div className="flex items-center rounded-md border border-dark-border bg-[#0d1117] p-0.5 text-xs font-mono">
              <button
                type="button"
                disabled={advisoryModeBusy}
                onClick={() => handleSetAdvisoryMode('dynamic')}
                title="Current-strategy prefers a live MPC re-solve every call -- adaptive, but inherits MPC's short-horizon stop blind spot"
                className={`px-2.5 py-1 rounded transition-colors ${advisoryMode === 'dynamic' ? 'bg-brand-purple text-white' : 'text-gray-400 hover:text-gray-200'}`}
              >
                Dynamic (MPC)
              </button>
              <button
                type="button"
                disabled={advisoryModeBusy}
                onClick={() => handleSetAdvisoryMode('ga_strict')}
                title="Current-strategy is a pure static lookup against GA's recorded plan -- MPC is never consulted"
                className={`px-2.5 py-1 rounded transition-colors ${advisoryMode === 'ga_strict' ? 'bg-brand-purple text-white' : 'text-gray-400 hover:text-gray-200'}`}
              >
                GA Strict
              </button>
            </div>
            {snapshot?.advisory?.available && snapshot.advisory.next_action?.s_m != null && (
              <span className="text-xs font-mono text-gray-400 bg-dark-border/50 px-2.5 py-1 rounded-md">
                Target Location: Station s = {snapshot.advisory.next_action.s_m.toFixed(0)} m
              </span>
            )}
          </div>
        </h3>
        {!snapshot?.advisory?.available ? (
          <p className="text-center text-sm text-gray-600 py-6">Waiting for distance &amp; speed telemetry to compute a recommendation…</p>
        ) : (() => {
          const nt = snapshot.advisory.next_turn
          const nstop = snapshot.advisory.next_stop
          const cs = snapshot.advisory.current_strategy
          const seg = snapshot.advisory.dp_segment!
          const csStyle = cs ? {
            gas: { bg: 'bg-green-500/10 border-green-500/30', text: 'text-green-400', label: 'GAS — Accelerate' },
            glide: { bg: 'bg-amber-500/10 border-amber-500/30', text: 'text-amber-400', label: 'GLIDE — Lift off & coast' },
            brake: { bg: 'bg-red-500/10 border-red-500/30', text: 'text-red-400', label: 'BRAKE' },
          }[cs.action] : null
          return (
            <>
              {cs && csStyle && (
                <div className={`rounded-lg border px-5 py-4 mb-3 flex items-center justify-between ${csStyle.bg}`}>
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1">
                      Current Strategy <span className="text-gray-600 normal-case">(right now, ~{LOOKAHEAD_S_LABEL}s ahead)</span>
                    </div>
                    <div className={`text-2xl font-bold ${csStyle.text}`}>
                      {csStyle.label} <span className="text-base font-semibold text-gray-400">@ {cs.target_speed_kmh.toFixed(0)} km/h</span>
                    </div>
                  </div>
                  <div className={`text-right text-xs font-mono px-3 py-1.5 rounded border hidden sm:block ${cs.live ? 'text-emerald-400/80 bg-emerald-500/5 border-emerald-500/20' : 'text-gray-500 bg-gray-500/5 border-gray-500/20'}`}>
                    {cs.live ? '⚡ Live MPC re-solve' : '📋 Precomputed plan'}
                  </div>
                </div>
              )}

              {nstop && nstop.stop_no != null && (
                <div className="rounded-lg border px-5 py-4 mb-3 flex items-center justify-between bg-red-500/10 border-red-500/30">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1 flex items-center gap-2">
                      <span>Next Stop</span>
                      <span className="text-[10px] text-red-300 bg-red-500/20 px-2 py-0.5 rounded font-normal">
                        Glide-Start &amp; Target Entry Speed
                      </span>
                    </div>
                    <div className="text-2xl font-bold text-red-400">
                      {nstop.distance_m != null && nstop.distance_m > 0 ? (
                        <>
                          GLIDE START in {nstop.distance_m.toFixed(0)} m → Bring {nstop.target_speed_kmh?.toFixed(0)} km/h{' '}
                          <span className="text-sm font-normal text-gray-400">
                            (Stop Line: {nstop.stop_line_distance_m?.toFixed(0)}m ahead)
                          </span>
                        </>
                      ) : (
                        <>
                          GLIDE NOW! → Coast to Stop{' '}
                          <span className="text-sm font-normal text-gray-400">
                            (Stop Line: {nstop.stop_line_distance_m?.toFixed(0)}m ahead)
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="text-right text-xs text-red-400/80 font-mono bg-red-500/5 px-3 py-1.5 rounded border border-red-500/20 hidden sm:block">
                    🛑 Mandatory Stop #{nstop.stop_no}
                  </div>
                </div>
              )}

              {nt && nt.turn_no != null && (
                <div className="rounded-lg border px-5 py-4 mb-3 flex items-center justify-between bg-sky-500/10 border-sky-500/30">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1 flex items-center gap-2">
                      <span>Next Turn</span>
                    </div>
                    <div className="text-2xl font-bold text-sky-400">
                      Turn {nt.turn_no} in {nt.distance_m?.toFixed(0)} m → Bring {nt.target_speed_kmh?.toFixed(0)} km/h
                    </div>
                  </div>
                  <div className="text-right text-xs text-sky-400/80 font-mono bg-sky-500/5 px-3 py-1.5 rounded border border-sky-500/20 hidden sm:block">
                    ↷ Turn #{nt.turn_no}
                  </div>
                </div>
              )}
              <div className="bg-[#0d1117] border border-dark-border rounded-lg p-3 text-xs text-gray-400 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span className="font-semibold text-gray-300">DP Segment Strategy:</span> Accelerate to <span className="text-brand-purple font-semibold">{seg.v_target_kmh.toFixed(0)} km/h</span>, then coast to <span className="text-amber-400 font-semibold">{seg.v_coast_kmh.toFixed(0)} km/h</span> over segment {seg.s_start_m.toFixed(0)} m → {seg.s_end_m.toFixed(0)} m (~{(seg.s_end_m - seg.s_start_m).toFixed(0)} m)
                </div>
                <div className="text-gray-500 text-[11px]">
                  Current: s = {snapshot.advisory.s_now_m?.toFixed(0)} m @ {snapshot.advisory.v_now_kmh?.toFixed(1)} km/h
                </div>
              </div>
            </>
          )
        })()}
      </div>

      {/* Driving Line Advisory -- steering (lateral offset), separate from the
          speed/gas-glide advisory above. Needs a real GPS fix: the flat
          constant-cruise sim has no lateral freedom of its own (it drives the
          fixed Shell GPS backbone exactly), so this only lights up once a
          GPS topic (live or --gps simulator) is actually publishing. */}
      <div className="bg-dark-card border border-dark-border rounded-xl p-6 mb-6">
        <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
          <Compass className="text-brand-purple" size={18} />
          Driving Line
          <span className="text-xs font-normal text-gray-500">
            lateral offset from racing line, {snapshot?.advisory?.line_deviation?.lookahead_m?.toFixed(0) ?? '10'} m ahead
          </span>
        </h3>
        {!snapshot?.advisory?.line_deviation?.available ? (
          <p className="text-center text-sm text-gray-600 py-6">Waiting for a live GPS fix to compute lateral position…</p>
        ) : (() => {
          const dev = snapshot.advisory.line_deviation.deviation_m as number
          const absDev = Math.abs(dev)
          const onLine = absDev < 0.15
          const style = onLine
            ? { text: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30' }
            : absDev < 0.75
            ? { text: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/30' }
            : { text: 'text-red-400', bg: 'bg-red-500/10 border-red-500/30' }
          const direction = onLine ? 'ON LINE' : dev > 0 ? '← STEER LEFT' : 'STEER RIGHT →'
          return (
            <div className={`rounded-lg border px-5 py-4 flex items-center justify-between ${style.bg}`}>
              <div>
                <div className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1">Lateral Deviation</div>
                <div className={`text-4xl font-bold font-mono ${style.text}`}>
                  {dev > 0 ? '+' : ''}{dev.toFixed(2)} m
                </div>
              </div>
              <div className={`text-right text-sm font-semibold ${style.text}`}>{direction}</div>
            </div>
          )
        })()}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-6">
        <Group icon={<Zap size={16} className="text-yellow-500" />} title="Electrical">
          <Metric label="Battery / FC Voltage" value={numOrNull(g('vinBattery'))} unit="V" />
          <Metric label="Current" value={numOrNull(g('currentBattery'))} unit="A" />
          <Metric label="Power" value={numOrNull(g('powerW'))} unit="W" />
          <Metric label="Energy" value={numOrNull(g('energyWh'))} unit="Wh" />
          <Metric label="Efficiency" value={numOrNull(g('kmPerkWh'))} unit="km/kWh" />
        </Group>

        <Group icon={<Compass size={16} className="text-blue-400" />} title="Motion & GPS">
          <Metric label="Velocity" value={numOrNull(g('velocity'))} unit="km/h" />
          <Metric label="Distance" value={numOrNull(g('distance'))} />
          <Metric label="Elapsed Time" value={numOrNull(g('timeS'))} unit="s" />
          <Metric label="Latitude" value={numOrNull(g('latitude'))} />
          <Metric label="Longitude" value={numOrNull(g('longitude'))} />
          <Metric label="MSL Altitude" value={numOrNull(g('mslAltitude'))} unit="m" />
        </Group>

        <Group icon={<Activity size={16} className="text-brand-purple" />} title="Dynamics (IMU)">
          <Metric label="G-Force X" value={numOrNull(g('gForceX'))} unit="g" />
          <Metric label="G-Force Y" value={numOrNull(g('gForceY'))} unit="g" />
          <Metric label="G-Force Z" value={numOrNull(g('gForceZ'))} unit="g" />
          <Metric label="WGS Altitude" value={numOrNull(g('wgsAltitude'))} unit="m" />
        </Group>

        <Group icon={<ShieldAlert size={16} className="text-red-400" />} title="Safety & Status">
          <Metric label="H2 Leak" value={g('h2leak') as number | string | null} />
          <Metric label="Countdown" value={numOrNull(g('countdown'))} unit="s" />
          <Metric label="Lap" value={numOrNull(g('lap'))} />
          <Metric label="Mode" value={g('mode') as number | string | null} />
        </Group>
      </div>

      {/* Full parameter data-flow panel -- every canonical field side by side,
          plus any raw key the feed sends that isn't in the recognized alias
          list, with per-row hide/show and a literal raw-JSON view -- the
          "see everything, like a terminal" view. */}
      <div className="bg-dark-card border border-dark-border rounded-xl mb-6">
        <button onClick={() => setParamsOpen(o => !o)} className="w-full flex items-center justify-between px-5 py-3">
          <span className="text-sm font-semibold flex items-center gap-2 text-gray-300 uppercase tracking-wider">
            <ListTree size={14} /> All Parameters ({Object.keys(latest).length} live keys)
          </span>
          <span className="text-xs text-gray-500">{paramsOpen ? 'hide' : 'show'}</span>
        </button>
        {paramsOpen && (
          <div className="px-5 pb-5">
            <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
              <p className="text-[11px] text-gray-600 max-w-lg">Every recognized field, plus (highlighted) any raw key the feed sends that isn't in the alias list. Click the eye to hide a row.</p>
              <div className="flex gap-3">
                {hiddenParams.size > 0 && (
                  <button onClick={() => setHiddenParams(new Set())} className="text-xs text-gray-400 hover:text-white flex items-center gap-1">
                    <Eye size={12} /> Show all ({hiddenParams.size} hidden)
                  </button>
                )}
                <button onClick={() => setShowRaw(s => !s)} className="text-xs text-gray-400 hover:text-white flex items-center gap-1">
                  <Terminal size={12} /> {showRaw ? 'Hide raw JSON' : 'Show raw JSON'}
                </button>
              </div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 font-mono text-xs">
              {Object.keys(FIELD_ALIASES).filter(name => !hiddenParams.has(name)).map(name => {
                const v = g(name)
                return (
                  <div key={name} className="flex items-center justify-between bg-[#0d1117] border border-dark-border rounded-lg px-3 py-2">
                    <button onClick={() => setHiddenParams(prev => new Set(prev).add(name))} className="text-gray-600 hover:text-red-400 mr-2 flex-shrink-0">
                      <EyeOff size={12} />
                    </button>
                    <span className="text-gray-400 flex-1 truncate mr-2">{name}</span>
                    <span className={v === null || v === undefined ? 'text-gray-600' : 'text-white'}>{v === null || v === undefined ? '--' : String(v)}</span>
                  </div>
                )
              })}
              {rawExtraKeys.filter(name => !hiddenParams.has(name)).map(name => (
                <div key={name} className="flex items-center justify-between bg-yellow-500/5 border border-yellow-500/20 rounded-lg px-3 py-2">
                  <button onClick={() => setHiddenParams(prev => new Set(prev).add(name))} className="text-gray-600 hover:text-red-400 mr-2 flex-shrink-0">
                    <EyeOff size={12} />
                  </button>
                  <span className="text-yellow-500 flex-1 truncate mr-2" title="Not in the recognized alias list -- shown raw">{name}</span>
                  <span className="text-white">{String(latest[name])}</span>
                </div>
              ))}
            </div>
            {showRaw && (
              <pre className="mt-4 bg-[#0d1117] border border-dark-border rounded-lg p-3 text-[11px] text-gray-400 overflow-x-auto max-h-64 overflow-y-auto">
{JSON.stringify(latest, null, 2)}
              </pre>
            )}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 flex-1 min-h-[280px]">
        <div className="bg-dark-card border border-dark-border rounded-xl p-6 flex flex-col">
          <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
            <Wind className="text-blue-400" size={18} />
            Speed vs Time
          </h3>
          <div className="flex-1 w-full h-full min-h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={history} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                <XAxis dataKey="t" stroke="#8b949e" tick={{ fill: '#8b949e' }} />
                <YAxis stroke="#8b949e" tick={{ fill: '#8b949e' }} domain={[0, 'auto']} />
                <Tooltip contentStyle={{ backgroundColor: '#161b22', borderColor: '#30363d', color: '#fff' }} />
                <Line type="monotone" dataKey="velocity" stroke="#631acb" strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          {history.every(h => h.velocity === null) && (
            <p className="text-center text-xs text-gray-600 mt-2">No data yet — chart will populate once the car publishes on {snapshot?.car_topic ?? 'the car topic'}</p>
          )}
        </div>

        <div className="bg-dark-card border border-dark-border rounded-xl p-6 flex flex-col">
          <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
            <Zap className="text-yellow-500" size={18} />
            Power vs Time
          </h3>
          <div className="flex-1 w-full h-full min-h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={history} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#30363d" vertical={false} />
                <XAxis dataKey="t" stroke="#8b949e" tick={{ fill: '#8b949e' }} />
                <YAxis stroke="#8b949e" tick={{ fill: '#8b949e' }} domain={[0, 'auto']} />
                <Tooltip contentStyle={{ backgroundColor: '#161b22', borderColor: '#30363d', color: '#fff' }} />
                <Line type="monotone" dataKey="powerW" stroke="#3b82f6" strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          {history.every(h => h.powerW === null) && (
            <p className="text-center text-xs text-gray-600 mt-2">No data yet — chart will populate once the car publishes on {snapshot?.car_topic ?? 'the car topic'}</p>
          )}
        </div>
      </div>
    </div>
  )
}
