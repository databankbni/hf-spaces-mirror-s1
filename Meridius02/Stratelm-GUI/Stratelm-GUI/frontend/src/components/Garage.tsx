import { useEffect, useState } from 'react'
import { Car, Plus, Trash2, Save, Zap, Wind, SlidersHorizontal, Gauge, Disc } from 'lucide-react'
import {
  listVehicles, getVehicle, createVehicle, updateVehicle, deleteVehicle, setVehicleFieldTag,
  calcPowertrainEfficiency, getJSON, VALID_TAGS,
  type VehicleSummary, type VehicleDoc, type VehicleFields,
  type MotorInfo, type FuelCellInfo, type ConverterInfo, type DerivedPowertrainEfficiency,
} from '../api'
import { Field, inputCls } from './ParamUI'

const ENERGY_CLASSES = ['hydrogen_fuel_cell', 'battery_electric', 'other']

const BLANK_FIELDS: VehicleFields = {
  vehicle_mass_kg: { value: 100.0, unit: 'kg', tag: 'PLACEHOLDER' },
  driver_mass_kg: { value: 70.0, unit: 'kg', tag: 'RULE-DERIVED' },
  cruise_target_kmh: { value: 30.0, unit: 'km/h', tag: 'PLACEHOLDER' },
  crr: { value: 0.004, tag: 'PLACEHOLDER' },
  body_geometry: { value: 'geom2', tag: 'PLACEHOLDER-CHOICE' },
  drivetrain_efficiency: { value: 0.80, tag: 'PLACEHOLDER' },
  wheel_radius_m: { value: 0.2, unit: 'm', tag: 'PLACEHOLDER' },
  frontal_area_m2: { value: 0.5, unit: 'm^2', tag: 'PLACEHOLDER' },
  accel_max_ms2: { value: 0.833, unit: 'm/s^2', tag: 'PLACEHOLDER' },
  brake_max_ms2: { value: 3.0, unit: 'm/s^2', tag: 'PLACEHOLDER' },
  stop_dwell_time_s: { value: 3.0, unit: 's', tag: 'PLACEHOLDER' },
  cornering_scrub_coeff: { value: 0.05, tag: 'PLACEHOLDER' },
  cornering_friction_mu: { value: 0.85, tag: 'PLACEHOLDER' },
  fc_parasitic_load_w: { value: 10.0, unit: 'W', tag: 'PLACEHOLDER' },
  accessory_load_w: { value: 15.0, unit: 'W', tag: 'PLACEHOLDER' },
  buffer_path_efficiency: { value: 0.90, tag: 'PLACEHOLDER' },
  buffer_capacity_wh: { value: 200.0, unit: 'Wh', tag: 'PLACEHOLDER' },
  buffer_max_charge_w: { value: 500.0, unit: 'W', tag: 'PLACEHOLDER' },
  buffer_max_discharge_w: { value: 3000.0, unit: 'W', tag: 'PLACEHOLDER' },
  buffer_round_trip_eff: { value: 0.93, tag: 'PLACEHOLDER' },
  buffer_soc_min_frac: { value: 0.2, tag: 'PLACEHOLDER' },
  buffer_soc_max_frac: { value: 0.9, tag: 'PLACEHOLDER' },
  max_electrical_voltage_v: { value: 60.0, unit: 'V', tag: 'RULE-DERIVED' },
  max_buffer_capacity_wh: { value: 1000.0, unit: 'Wh', tag: 'RULE-DERIVED' },
}

// default_motor/default_fc are pre-filled (not left null) so a freshly
// created vehicle is immediately runnable from the Sandbox without relying
// on catalog fallback logic -- swap them in the Powertrain section below.
const BLANK_VEHICLE: Omit<VehicleDoc, 'id'> = {
  name: 'New Vehicle',
  energy_class: 'hydrogen_fuel_cell',
  notes: '',
  default_motor: 'Innotec Power 145-DZS48-010',
  default_fc: 'G-HFCS 600W 24V',
  motor_catalog_csv: 'data/motor_candidates.csv',
  fc_catalog_csv: 'data/fc_candidates.csv',
  aero_cda_by_geometry: { geom2: [[30.0, 0.09]] },
  fields: BLANK_FIELDS,
}

export default function Garage() {
  return (
    <div className="p-8 h-full overflow-y-auto">
      <div className="mb-8 flex items-end justify-between flex-wrap gap-4">
        <div>
          <h2 className="text-3xl font-bold flex items-center gap-3"><Car className="text-brand-purple" />Garage</h2>
          <p className="text-gray-400">Every vehicle spec — the source of truth the Sandbox and Strategy tabs pick from</p>
        </div>
      </div>

      <VehiclesPanel />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Vehicles
// ---------------------------------------------------------------------------
function VehiclesPanel() {
  const [summaries, setSummaries] = useState<VehicleSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<VehicleDoc | null>(null)
  const [derivedEff, setDerivedEff] = useState<DerivedPowertrainEfficiency | null>(null)
  const [isNew, setIsNew] = useState(false)
  const [motors, setMotors] = useState<MotorInfo[]>([])
  const [fuelCells, setFuelCells] = useState<FuelCellInfo[]>([])
  const [converters, setConverters] = useState<ConverterInfo[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refreshList = () => listVehicles().then(r => setSummaries(r.vehicles)).catch(e => setError(String(e)))

  useEffect(() => {
    refreshList()
    getJSON<{ motors: MotorInfo[] }>('/api/motors').then(r => setMotors(r.motors)).catch(() => {})
    getJSON<{ fuel_cells: FuelCellInfo[] }>('/api/fuel-cells').then(r => setFuelCells(r.fuel_cells)).catch(() => {})
    getJSON<{ converters: ConverterInfo[] }>('/api/converters').then(r => setConverters(r.converters)).catch(() => {})
  }, [])

  useEffect(() => {
    if (!selectedId) { setDraft(null); setDerivedEff(null); return }
    setIsNew(false)
    getVehicle(selectedId).then(v => {
      setDraft(v)
      if (v.derived_powertrain_efficiency) {
        setDerivedEff(v.derived_powertrain_efficiency)
      }
    }).catch(e => setError(String(e)))
  }, [selectedId])

  useEffect(() => {
    if (!draft) {
      setDerivedEff(null)
      return
    }
    calcPowertrainEfficiency(draft)
      .then(r => { if (r.efficiency) setDerivedEff(r.efficiency) })
      .catch(() => {})
  }, [
    draft?.default_motor,
    draft?.default_motor_cruise,
    draft?.default_cruise_converter,
    draft?.default_fc,
    draft?.fields?.drivetrain_efficiency?.value,
    draft?.fields?.buffer_path_efficiency?.value,
    draft?.fields?.fc_parasitic_load_w?.value,
  ])

  const startNew = () => {
    setSelectedId(null)
    setIsNew(true)
    setDraft({ id: '__new__', ...BLANK_VEHICLE })
  }

  const updateField = (field: string, patch: Partial<{ value: number | string; tag: string }>) => {
    setDraft(d => d ? { ...d, fields: { ...d.fields, [field]: { ...d.fields[field], ...patch } } } : d)
  }

  // Keeps the "Body Geometry" selection in sync with whatever the user does
  // to the custom drag-curve editor below (rename the active geometry, or
  // delete it out from under the current selection).
  const updateAeroGeometry = (next: Record<string, [number, number][]>, renamedFrom?: string, renamedTo?: string) => {
    setDraft(d => {
      if (!d) return d
      let bodyGeom = d.fields.body_geometry?.value
      if (renamedFrom && renamedTo && bodyGeom === renamedFrom) bodyGeom = renamedTo
      if (typeof bodyGeom !== 'string' || !(bodyGeom in next)) bodyGeom = Object.keys(next)[0] ?? bodyGeom
      return {
        ...d,
        aero_cda_by_geometry: next,
        fields: { ...d.fields, body_geometry: { ...d.fields.body_geometry, value: bodyGeom } },
      }
    })
  }

  const handleTagChange = (field: string, tag: string) => {
    updateField(field, { tag })
    if (!isNew && draft) setVehicleFieldTag(draft.id, field, tag).catch(() => {})
  }

  const handleSave = async () => {
    if (!draft) return
    setSaving(true)
    setError(null)
    try {
      const { id, ...body } = draft
      if (isNew) {
        const created = await createVehicle(body)
        setIsNew(false)
        setSelectedId(created.id)
        setDraft(created)
      } else {
        const updated = await updateVehicle(id, body)
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
    if (!confirm(`Delete vehicle "${draft.name}"? This cannot be undone.`)) return
    const res = await deleteVehicle(draft.id)
    if (!res.success) { setError(res.error ?? 'delete failed'); return }
    setSelectedId(null)
    await refreshList()
  }

  const num = (v: string) => parseFloat(v)

  return (
    <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
      <div className="xl:col-span-1 flex flex-col gap-3">
        {summaries.map(v => (
          <button key={v.id} onClick={() => setSelectedId(v.id)}
            className={`text-left bg-dark-card border rounded-xl p-4 transition-colors ${
              selectedId === v.id ? 'border-brand-purple' : 'border-dark-border hover:border-gray-600'}`}>
            <div className="font-semibold text-white">{v.name}</div>
            <div className="text-xs text-gray-500 uppercase tracking-wider mt-0.5">{v.energy_class?.replace(/_/g, ' ')}</div>
            <div className="text-xs text-gray-400 mt-2">{v.vehicle_mass_kg} kg + {v.driver_mass_kg} kg driver</div>
            <div className="text-xs text-gray-600 mt-1 truncate">{v.default_motor}</div>
          </button>
        ))}
        <button onClick={startNew}
          className="border border-dashed border-dark-border rounded-xl p-4 text-gray-500 hover:text-brand-purple hover:border-brand-purple transition-colors flex items-center justify-center gap-2">
          <Plus size={16} /> New Vehicle
        </button>
      </div>

      <div className="xl:col-span-3">
        {error && <div className="mb-4 bg-red-500/10 border border-red-500/30 text-red-400 rounded-lg px-4 py-3 text-sm">{error}</div>}
        {!draft && (
          <div className="bg-dark-card border border-dark-border rounded-xl p-12 text-center text-gray-500">
            Select a vehicle to view/edit its full spec, or create a new one.
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
                  <label className="block text-sm font-medium text-gray-400 mb-1">Energy Class</label>
                  <select className={inputCls} value={draft.energy_class} onChange={e => setDraft({ ...draft, energy_class: e.target.value })}>
                    {ENERGY_CLASSES.map(c => <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>)}
                  </select>
                </div>
              </div>
              <label className="block text-sm font-medium text-gray-400 mb-1">Notes</label>
              <textarea className={inputCls} rows={2} value={draft.notes} onChange={e => setDraft({ ...draft, notes: e.target.value })} />
            </div>

            <FieldGrid title="Mass & Cruise" icon={<Gauge size={16} className="text-brand-purple" />}>
              <Field label="Vehicle Mass (kg)" tag={draft.fields.vehicle_mass_kg?.tag} validTags={VALID_TAGS} onTagChange={t => handleTagChange('vehicle_mass_kg', t)}>
                <input type="number" className={inputCls} value={draft.fields.vehicle_mass_kg?.value} onChange={e => updateField('vehicle_mass_kg', { value: num(e.target.value) })} />
              </Field>
              <Field label="Driver Mass (kg)" tag={draft.fields.driver_mass_kg?.tag} validTags={VALID_TAGS} onTagChange={t => handleTagChange('driver_mass_kg', t)}>
                <input type="number" className={inputCls} value={draft.fields.driver_mass_kg?.value} onChange={e => updateField('driver_mass_kg', { value: num(e.target.value) })} />
              </Field>
              <Field label="Cruise Target (km/h)" tag={draft.fields.cruise_target_kmh?.tag} validTags={VALID_TAGS} onTagChange={t => handleTagChange('cruise_target_kmh', t)} note="Nominal design cruise speed; the Sandbox can override or disable this per run">
                <input type="number" className={inputCls} value={draft.fields.cruise_target_kmh?.value} onChange={e => updateField('cruise_target_kmh', { value: num(e.target.value) })} />
              </Field>
            </FieldGrid>

            <FieldGrid title="Aerodynamics" icon={<Wind size={16} className="text-blue-400" />}>
              <Field label="Body Geometry" tag={draft.fields.body_geometry?.tag} validTags={VALID_TAGS} onTagChange={t => handleTagChange('body_geometry', t)} note="Which drag-curve variant (edited below) this vehicle currently uses">
                <select
                  className={inputCls}
                  value={String(draft.fields.body_geometry?.value)}
                  onChange={e => updateField('body_geometry', { value: e.target.value })}
                >
                  {Object.keys(draft.aero_cda_by_geometry ?? {}).map(g => <option key={g} value={g}>{g}</option>)}
                </select>
              </Field>
              <Field label="Frontal Area (m²)" tag={draft.fields.frontal_area_m2?.tag} validTags={VALID_TAGS} onTagChange={t => handleTagChange('frontal_area_m2', t)}>
                <input type="number" step="0.001" className={inputCls} value={draft.fields.frontal_area_m2?.value} onChange={e => updateField('frontal_area_m2', { value: num(e.target.value) })} />
              </Field>
            </FieldGrid>

            <div className="bg-dark-card border border-dark-border rounded-xl p-6">
              <h3 className="text-lg font-bold mb-2 flex items-center gap-2"><Wind size={16} className="text-blue-400" />Body Geometry &amp; Drag Curve</h3>
              <p className="text-xs text-gray-600 mb-4">
                Build your own CdA-vs-speed curve for each body variant you've tested (from CFD, wind-tunnel, or coast-down data) — add as many speed/drag points and geometries as you like, then pick the active one above.
              </p>
              <AeroGeometryEditor value={draft.aero_cda_by_geometry ?? {}} onChange={updateAeroGeometry} />
            </div>

            <FieldGrid title="Rolling Resistance & Drivetrain" icon={<Disc size={16} className="text-orange-400" />}>
              <Field label="Rolling Resistance (Crr)" tag={draft.fields.crr?.tag} validTags={VALID_TAGS} onTagChange={t => handleTagChange('crr', t)}>
                <input type="number" step="0.0001" className={inputCls} value={draft.fields.crr?.value} onChange={e => updateField('crr', { value: num(e.target.value) })} />
              </Field>
              <Field label="Wheel Radius (m)" tag={draft.fields.wheel_radius_m?.tag} validTags={VALID_TAGS} onTagChange={t => handleTagChange('wheel_radius_m', t)} note="Only feeds gear-ratio calc, not exercised by the current simulator phase">
                <input type="number" step="0.001" className={inputCls} value={draft.fields.wheel_radius_m?.value} onChange={e => updateField('wheel_radius_m', { value: num(e.target.value) })} />
              </Field>
              <Field label="Drivetrain Efficiency" tag={draft.fields.drivetrain_efficiency?.tag} validTags={VALID_TAGS} onTagChange={t => handleTagChange('drivetrain_efficiency', t)}>
                <input type="number" step="0.01" min="0.01" max="1" className={inputCls} value={draft.fields.drivetrain_efficiency?.value} onChange={e => updateField('drivetrain_efficiency', { value: num(e.target.value) })} />
              </Field>
            </FieldGrid>

            <FieldGrid title="Performance Limits" icon={<SlidersHorizontal size={16} className="text-brand-purple" />}>
              <Field label="Max Acceleration (m/s²)" tag={draft.fields.accel_max_ms2?.tag} validTags={VALID_TAGS} onTagChange={t => handleTagChange('accel_max_ms2', t)}>
                <input type="number" step="0.01" className={inputCls} value={draft.fields.accel_max_ms2?.value} onChange={e => updateField('accel_max_ms2', { value: num(e.target.value) })} />
              </Field>
              <Field label="Max Braking (m/s²)" tag={draft.fields.brake_max_ms2?.tag} validTags={VALID_TAGS} onTagChange={t => handleTagChange('brake_max_ms2', t)}>
                <input type="number" step="0.1" className={inputCls} value={draft.fields.brake_max_ms2?.value} onChange={e => updateField('brake_max_ms2', { value: num(e.target.value) })} />
              </Field>
              <Field label="Cornering Friction μ" tag={draft.fields.cornering_friction_mu?.tag} validTags={VALID_TAGS} onTagChange={t => handleTagChange('cornering_friction_mu', t)} note="Bakes into a track's precomputed v_safe_kmh -- not read live by the Sandbox run">
                <input type="number" step="0.01" className={inputCls} value={draft.fields.cornering_friction_mu?.value} onChange={e => updateField('cornering_friction_mu', { value: num(e.target.value) })} />
              </Field>
              <Field label="Stop Dwell Time (s)" tag={draft.fields.stop_dwell_time_s?.tag} validTags={VALID_TAGS} onTagChange={t => handleTagChange('stop_dwell_time_s', t)} note="Art. 227: full stop required, no dwell duration specified">
                <input type="number" step="0.5" className={inputCls} value={draft.fields.stop_dwell_time_s?.value} onChange={e => updateField('stop_dwell_time_s', { value: num(e.target.value) })} />
              </Field>
            </FieldGrid>

            <div className="bg-dark-card border border-dark-border rounded-xl p-6">
              <h3 className="text-lg font-bold mb-5 flex items-center justify-between">
                <span className="flex items-center gap-2"><Zap className="text-yellow-500" size={18} />Powertrain &amp; Dual-Motor Configuration</span>
                <span className="text-xs text-gray-500 font-normal">Dual Motor Setup Supported</span>
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm font-medium text-amber-400 mb-1">⚡ Acceleration Motor (Dual-Motor)</label>
                  <select className={inputCls} value={draft.default_motor_accel ?? draft.default_motor ?? ''} onChange={e => setDraft({ ...draft, default_motor_accel: e.target.value })}>
                    <option value="">-- none --</option>
                    {motors.map(m => <option key={m.name} value={m.name}>{m.name} ({m.voltage_v}V, {m.max_mech_power_w}W)</option>)}
                  </select>
                  <p className="text-[11px] text-gray-500 mt-1">High-torque motor used during acceleration phases</p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-blue-400 mb-1">🏁 Cruise Motor (Dual-Motor)</label>
                  <select className={inputCls} value={draft.default_motor_cruise ?? draft.default_motor ?? ''} onChange={e => setDraft({ ...draft, default_motor_cruise: e.target.value })}>
                    <option value="">-- none --</option>
                    {motors.map(m => <option key={m.name} value={m.name}>{m.name} ({m.voltage_v}V, {m.max_mech_power_w}W)</option>)}
                  </select>
                  <p className="text-[11px] text-gray-500 mt-1">High-efficiency motor used during constant-speed cruising</p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-cyan-400 mb-1">🔌 DC/DC Converter (Cruise Rail)</label>
                  <select className={inputCls} value={draft.default_cruise_converter ?? ''} onChange={e => setDraft({ ...draft, default_cruise_converter: e.target.value })}>
                    <option value="">-- none --</option>
                    {converters.map(c => <option key={c.name} value={c.name}>{c.name} ({c.output_v}V, {c.rated_power_w}W, {c.efficiency_pct}%)</option>)}
                  </select>
                  <p className="text-[11px] text-gray-500 mt-1">Buck converter stepping the 48V bus down for the cruise motor -- the accel motor sits on the bus directly and doesn't need one</p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">Primary / Single Motor</label>
                  <select className={inputCls} value={draft.default_motor ?? ''} onChange={e => setDraft({ ...draft, default_motor: e.target.value })}>
                    <option value="">-- none --</option>
                    {motors.map(m => <option key={m.name} value={m.name}>{m.name} ({m.voltage_v}V, {m.max_mech_power_w}W)</option>)}
                  </select>
                  <p className="text-[11px] text-gray-500 mt-1">Default baseline motor fallback</p>
                </div>
                <div className="md:col-span-2 xl:col-span-3">
                  <label className="block text-sm font-medium text-gray-400 mb-1">Default Fuel Cell</label>
                  <select className={inputCls} value={draft.default_fc ?? ''} onChange={e => setDraft({ ...draft, default_fc: e.target.value })}>
                    <option value="">-- none --</option>
                    {fuelCells.map(f => <option key={f.name} value={f.name}>{f.name} ({f.rated_power_w}W)</option>)}
                  </select>
                </div>
              </div>

              {derivedEff && (
                <div className="mt-5 pt-5 border-t border-dark-border">
                  <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
                    <div className="flex items-center gap-2">
                      <Gauge className="text-brand-purple" size={18} />
                      <span className="font-bold text-sm text-white">Overall Powertrain Efficiency at Cruise (~{derivedEff.speed_kmh} km/h)</span>
                    </div>
                    <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-blue-500/20 text-blue-400 border border-blue-500/30">
                      DERIVED (READ-ONLY)
                    </span>
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-5 gap-3 bg-[#0d1117] p-4 rounded-lg border border-dark-border mb-3">
                    <div>
                      <div className="text-[11px] text-gray-400 font-medium">Overall Efficiency</div>
                      <div className="text-xl font-extrabold text-emerald-400">{derivedEff.overall_eff_pct.toFixed(1)}%</div>
                      <div className="text-[10px] text-gray-500 mt-0.5">wheel / chemical H₂</div>
                    </div>
                    <div>
                      <div className="text-[11px] text-gray-400 font-medium">Wheel Power</div>
                      <div className="text-xl font-extrabold text-white">{derivedEff.p_wheel_w.toFixed(1)} W</div>
                      <div className="text-[10px] text-gray-500 mt-0.5">at 30 km/h flat cruise</div>
                    </div>
                    <div>
                      <div className="text-[11px] text-gray-400 font-medium">Cruise Motor Eff.</div>
                      <div className="text-xl font-extrabold text-blue-400">{derivedEff.motor_eff_pct.toFixed(1)}%</div>
                      <div className="text-[10px] text-gray-500 mt-0.5 truncate">{derivedEff.motor_name}</div>
                    </div>
                    {derivedEff.converter_eff_pct != null && (
                      <div>
                        <div className="text-[11px] text-gray-400 font-medium">DC/DC Converter Eff.</div>
                        <div className="text-xl font-extrabold text-cyan-400">{derivedEff.converter_eff_pct.toFixed(1)}%</div>
                        <div className="text-[10px] text-gray-500 mt-0.5 truncate">{derivedEff.converter_name}</div>
                      </div>
                    )}
                    <div>
                      <div className="text-[11px] text-gray-400 font-medium">Fuel Cell Eff.</div>
                      <div className="text-xl font-extrabold text-amber-400">{derivedEff.fc_eff_pct.toFixed(1)}%</div>
                      <div className="text-[10px] text-gray-500 mt-0.5 truncate">{derivedEff.fc_name}</div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 text-[11px] text-gray-400 flex-wrap pt-2 border-t border-dark-border/50">
                    <span className="font-semibold text-gray-300">Stage Chain:</span>
                    <span>Drivetrain ({derivedEff.drivetrain_eff_pct}%)</span>
                    <span>→</span>
                    <span>Motor ({derivedEff.motor_eff_pct}%)</span>
                    {derivedEff.converter_eff_pct != null && (
                      <>
                        <span>→</span>
                        <span>DC/DC Converter ({derivedEff.converter_eff_pct}%)</span>
                      </>
                    )}
                    <span>→</span>
                    <span>Buffer ({derivedEff.buffer_eff_pct}%)</span>
                    <span>→</span>
                    <span>Fuel Cell ({derivedEff.fc_eff_pct}%)</span>
                  </div>
                  <p className="text-[10px] text-gray-500 mt-2 italic">
                    Computed at a representative operating point (~30 km/h, {derivedEff.p_wheel_w.toFixed(1)} W wheel power). Stage efficiencies are load-dependent curves and not a single flat number.
                    {derivedEff.converter_eff_pct != null && ' DC/DC converter efficiency is extrapolated below its datasheet\'s validated load floor -- see data/dcdc_candidates.csv.'}
                  </p>
                </div>
              )}
            </div>

            {/* Parasitic Loads & Buffer Path fields still exist on draft.fields (used by the backend) -- just hidden from this tab per request. */}

            <div className="flex gap-3">
              <button onClick={handleSave} disabled={saving}
                className="flex-1 bg-brand-purple hover:bg-brand-purple/80 text-white font-bold py-3 rounded-lg transition-colors flex justify-center items-center gap-2">
                <Save size={18} /> {saving ? 'Saving...' : isNew ? 'Create Vehicle' : 'Save Changes'}
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

function FieldGrid({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="bg-dark-card border border-dark-border rounded-xl p-6">
      <h3 className="text-lg font-bold mb-5 flex items-center gap-2">{icon}{title}</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">{children}</div>
    </div>
  )
}

// Full CRUD over a vehicle's aero_cda_by_geometry: any number of named body
// variants, each an arbitrary list of (speed_kmh, CdA_m2) points -- lets a
// team key in their own CFD/wind-tunnel/coast-down curve instead of being
// stuck with whatever geometry a previous vehicle happened to ship with.
function AeroGeometryEditor({
  value,
  onChange,
}: {
  value: Record<string, [number, number][]>
  onChange: (next: Record<string, [number, number][]>, renamedFrom?: string, renamedTo?: string) => void
}) {
  const names = Object.keys(value)

  const addGeometry = () => {
    let name = 'custom'
    let n = 2
    while (name in value) { name = `custom-${n}`; n++ }
    onChange({ ...value, [name]: [[30.0, 0.09]] })
  }

  const removeGeometry = (geom: string) => {
    if (names.length <= 1) return
    const rest = { ...value }
    delete rest[geom]
    onChange(rest)
  }

  const renameGeometry = (oldName: string, newName: string) => {
    if (!newName || newName === oldName || newName in value) return
    const next: Record<string, [number, number][]> = {}
    for (const [k, v] of Object.entries(value)) next[k === oldName ? newName : k] = v
    onChange(next, oldName, newName)
  }

  const updatePoint = (geom: string, idx: number, axis: 0 | 1, n: number) => {
    if (Number.isNaN(n)) return
    const pts = value[geom].map((p, i): [number, number] => (i === idx ? (axis === 0 ? [n, p[1]] : [p[0], n]) : p))
    onChange({ ...value, [geom]: pts })
  }

  const addPoint = (geom: string) => {
    const pts = value[geom]
    const last = pts[pts.length - 1]
    onChange({ ...value, [geom]: [...pts, [last ? last[0] + 10 : 10, last ? last[1] : 0.05]] })
  }

  const removePoint = (geom: string, idx: number) => {
    if (value[geom].length <= 1) return
    onChange({ ...value, [geom]: value[geom].filter((_, i) => i !== idx) })
  }

  return (
    <div className="flex flex-col gap-4">
      {names.map(geom => (
        <div key={geom} className="border border-dark-border rounded-lg p-4">
          <div className="flex items-center justify-between gap-2 mb-3">
            <input
              className="bg-transparent border-b border-dark-border text-sm font-semibold text-white focus:outline-none focus:border-brand-purple px-1 py-0.5 w-40"
              value={geom}
              onChange={e => renameGeometry(geom, e.target.value.trim())}
            />
            <button type="button" onClick={() => removeGeometry(geom)} disabled={names.length <= 1}
              title={names.length <= 1 ? 'At least one geometry is required' : 'Remove this geometry'}
              className="text-gray-500 hover:text-red-400 disabled:opacity-30 disabled:cursor-not-allowed">
              <Trash2 size={14} />
            </button>
          </div>
          <div className="flex flex-col gap-2">
            {value[geom].map((pt, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <input type="number" step="1" className={`${inputCls} !py-1.5`} value={pt[0]}
                  onChange={e => updatePoint(geom, idx, 0, parseFloat(e.target.value))} />
                <span className="text-[11px] text-gray-500 whitespace-nowrap">km/h speed</span>
                <input type="number" step="0.001" className={`${inputCls} !py-1.5`} value={pt[1]}
                  onChange={e => updatePoint(geom, idx, 1, parseFloat(e.target.value))} />
                <span className="text-[11px] text-gray-500 whitespace-nowrap">m² CdA drag</span>
                <button type="button" onClick={() => removePoint(geom, idx)} disabled={value[geom].length <= 1}
                  className="text-gray-500 hover:text-red-400 disabled:opacity-30 disabled:cursor-not-allowed">
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
          </div>
          <button type="button" onClick={() => addPoint(geom)}
            className="mt-2 text-xs text-gray-500 hover:text-brand-purple flex items-center gap-1">
            <Plus size={12} /> Add speed/drag point
          </button>
        </div>
      ))}
      <button type="button" onClick={addGeometry}
        className="border border-dashed border-dark-border rounded-lg p-3 text-gray-500 hover:text-brand-purple hover:border-brand-purple transition-colors flex items-center justify-center gap-2 text-sm">
        <Plus size={14} /> Add Body Geometry Variant
      </button>
    </div>
  )
}

