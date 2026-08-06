import { useEffect, useMemo, useState } from 'react'
import { MapPin, Plus, Trash2, Save, FileBarChart } from 'lucide-react'
import {
  listTracks, getTrack, createTrack, updateTrack, deleteTrack, listDataFiles,
  type TrackDoc,
} from '../api'
import { inputCls } from './ParamUI'
import TrackAnalysis from './TrackAnalysis'

type Mode = 'registry' | 'analysis'

const BLANK_TRACK: Omit<TrackDoc, 'id'> = {
  name: 'New Track',
  location: '',
  notes: '',
  coordinates_csv: '',
  turns_csv: '',
  edges_csv: '',
  lap_distance_km: 3.7,
  total_laps: 4,
  total_distance_km: 14.8,
  max_attempt_time_min: 35.0,
  stops_per_lap: 2,
  stop_locations_km: [0.0],
}

export default function Tracks() {
  const [mode, setMode] = useState<Mode>('registry')

  return (
    <div className="p-8 h-full overflow-y-auto">
      <div className="mb-8 flex items-end justify-between flex-wrap gap-4">
        <div>
          <h2 className="text-3xl font-bold flex items-center gap-3"><MapPin className="text-brand-purple" />Tracks</h2>
          <p className="text-gray-400">Every registered circuit — the source of truth the Sandbox and Strategy tabs pick from</p>
        </div>
        <div className="flex gap-2 bg-dark-card border border-dark-border rounded-lg p-1">
          <button onClick={() => setMode('registry')}
            className={`px-4 py-2 rounded-md text-sm font-medium flex items-center gap-2 transition-colors ${mode === 'registry' ? 'bg-brand-purple/20 text-brand-purple' : 'text-gray-400 hover:text-white'}`}>
            <MapPin size={16} /> Registry
          </button>
          <button onClick={() => setMode('analysis')}
            className={`px-4 py-2 rounded-md text-sm font-medium flex items-center gap-2 transition-colors ${mode === 'analysis' ? 'bg-brand-purple/20 text-brand-purple' : 'text-gray-400 hover:text-white'}`}>
            <FileBarChart size={16} /> Track Analysis
          </button>
        </div>
      </div>

      {mode === 'registry' ? <TracksPanel /> : <TrackAnalysis />}
    </div>
  )
}

function TracksPanel() {
  const [tracks, setTracks] = useState<TrackDoc[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<TrackDoc | null>(null)
  const [isNew, setIsNew] = useState(false)
  const [csvFiles, setCsvFiles] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refreshList = () => listTracks().then(r => setTracks(r.tracks)).catch(e => setError(String(e)))

  useEffect(() => {
    refreshList()
    listDataFiles().then(r => setCsvFiles(r.files)).catch(() => {})
  }, [])

  useEffect(() => {
    if (!selectedId) { setDraft(null); return }
    setIsNew(false)
    getTrack(selectedId).then(setDraft).catch(e => setError(String(e)))
  }, [selectedId])

  const startNew = () => {
    setSelectedId(null)
    setIsNew(true)
    setDraft({ id: '__new__', ...BLANK_TRACK })
  }

  const handleSave = async () => {
    if (!draft) return
    setSaving(true)
    setError(null)
    try {
      const { id, ...body } = draft
      if (isNew) {
        const created = await createTrack(body)
        setIsNew(false)
        setSelectedId(created.id)
        setDraft(created)
      } else {
        const updated = await updateTrack(id, body)
        setDraft(updated)
      }
      await refreshList()
    } catch (e) {
      setError(String(e))
    }
    setSaving(false)
  }

  const handleDelete = async () => {
    if (!draft || isNew) return
    if (!confirm(`Delete track "${draft.name}"? This cannot be undone.`)) return
    const res = await deleteTrack(draft.id)
    if (!res.success) { setError(res.error ?? 'delete failed'); return }
    setSelectedId(null)
    await refreshList()
  }

  const num = (v: string) => parseFloat(v)
  const csvOptions = useMemo(() => csvFiles, [csvFiles])

  return (
    <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
      <div className="xl:col-span-1 flex flex-col gap-3">
        {tracks.map(t => (
          <button key={t.id} onClick={() => setSelectedId(t.id)}
            className={`text-left bg-dark-card border rounded-xl p-4 transition-colors ${
              selectedId === t.id ? 'border-brand-purple' : 'border-dark-border hover:border-gray-600'}`}>
            <div className="font-semibold text-white">{t.name}</div>
            <div className="text-xs text-gray-500 mt-0.5">{t.location}</div>
            <div className="text-xs text-gray-400 mt-2">{t.lap_distance_km} km × {t.total_laps} laps</div>
          </button>
        ))}
        <button onClick={startNew}
          className="border border-dashed border-dark-border rounded-xl p-4 text-gray-500 hover:text-brand-purple hover:border-brand-purple transition-colors flex items-center justify-center gap-2">
          <Plus size={16} /> New Track
        </button>
      </div>

      <div className="xl:col-span-3">
        {error && <div className="mb-4 bg-red-500/10 border border-red-500/30 text-red-400 rounded-lg px-4 py-3 text-sm">{error}</div>}
        {!draft && (
          <div className="bg-dark-card border border-dark-border rounded-xl p-12 text-center text-gray-500">
            Select a track to view/edit it, or register a new one.
          </div>
        )}
        {draft && (
          <div className="flex flex-col gap-6">
            <div className="bg-dark-card border border-dark-border rounded-xl p-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">Name</label>
                  <input className={inputCls} value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">Location</label>
                  <input className={inputCls} value={draft.location} onChange={e => setDraft({ ...draft, location: e.target.value })} />
                </div>
              </div>
              <label className="block text-sm font-medium text-gray-400 mb-1">Notes</label>
              <textarea className={inputCls} rows={2} value={draft.notes} onChange={e => setDraft({ ...draft, notes: e.target.value })} />
            </div>

            <div className="bg-dark-card border border-dark-border rounded-xl p-6">
              <h3 className="text-lg font-bold mb-2 flex items-center gap-2"><MapPin size={18} className="text-brand-purple" />Source Data</h3>
              <p className="text-xs text-gray-600 mb-4">GPS/turns/width digitization happens outside this GUI (it's a data-engineering task) — this just points a track profile at the resulting CSVs already under data/.</p>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">Coordinates CSV</label>
                  <select className={inputCls} value={draft.coordinates_csv} onChange={e => setDraft({ ...draft, coordinates_csv: e.target.value })}>
                    <option value="">-- select --</option>
                    {csvOptions.map(f => <option key={f} value={f}>{f}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">Turns CSV</label>
                  <select className={inputCls} value={draft.turns_csv} onChange={e => setDraft({ ...draft, turns_csv: e.target.value })}>
                    <option value="">-- select --</option>
                    {csvOptions.map(f => <option key={f} value={f}>{f}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">Edges/Width CSV</label>
                  <select className={inputCls} value={draft.edges_csv} onChange={e => setDraft({ ...draft, edges_csv: e.target.value })}>
                    <option value="">-- select --</option>
                    {csvOptions.map(f => <option key={f} value={f}>{f}</option>)}
                  </select>
                </div>
              </div>
            </div>

            <div className="bg-dark-card border border-dark-border rounded-xl p-6">
              <h3 className="text-lg font-bold mb-5">Attempt Format</h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">Lap Distance (km)</label>
                  <input type="number" step="0.001" className={inputCls} value={draft.lap_distance_km} onChange={e => setDraft({ ...draft, lap_distance_km: num(e.target.value) })} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">Total Laps</label>
                  <input type="number" className={inputCls} value={draft.total_laps} onChange={e => setDraft({ ...draft, total_laps: parseInt(e.target.value, 10) })} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">Total Distance (km)</label>
                  <input type="number" step="0.01" className={inputCls} value={draft.total_distance_km} onChange={e => setDraft({ ...draft, total_distance_km: num(e.target.value) })} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">Max Attempt Time (min)</label>
                  <input type="number" step="0.5" className={inputCls} value={draft.max_attempt_time_min} onChange={e => setDraft({ ...draft, max_attempt_time_min: num(e.target.value) })} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">Stops Per Lap</label>
                  <input type="number" className={inputCls} value={draft.stops_per_lap} onChange={e => setDraft({ ...draft, stops_per_lap: parseInt(e.target.value, 10) })} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">Stop Locations (km, comma-separated)</label>
                  <input className={inputCls} value={draft.stop_locations_km.join(', ')}
                    onChange={e => setDraft({ ...draft, stop_locations_km: e.target.value.split(',').map(s => parseFloat(s.trim())).filter(n => !isNaN(n)) })} />
                </div>
              </div>
            </div>

            <div className="flex gap-3">
              <button onClick={handleSave} disabled={saving}
                className="flex-1 bg-brand-purple hover:bg-brand-purple/80 text-white font-bold py-3 rounded-lg transition-colors flex justify-center items-center gap-2">
                <Save size={18} /> {saving ? 'Saving...' : isNew ? 'Create Track' : 'Save Changes'}
              </button>
              {!isNew && (
                <button onClick={handleDelete}
                  className="px-6 bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 text-red-400 font-bold py-3 rounded-lg transition-colors flex items-center gap-2">
                  <Trash2 size={18} /> Delete
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
