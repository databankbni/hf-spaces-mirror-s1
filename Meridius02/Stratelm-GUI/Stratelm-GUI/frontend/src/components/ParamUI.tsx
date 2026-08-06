// Shared building blocks for editing tagged (MEASURED/PLACEHOLDER/...) numeric
// parameters -- used by both the Garage (vehicle/track spec forms) and, for
// per-run environment fields, the Sandbox.

export const TAG_COLOR: Record<string, string> = {
  MEASURED: 'bg-green-500/20 text-green-400 border-green-500/30',
  'MEASURED-CFD': 'bg-green-500/20 text-green-400 border-green-500/30',
  'RULE-DERIVED': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  PLACEHOLDER: 'bg-red-500/20 text-red-400 border-red-500/30',
  'PLACEHOLDER-CHOICE': 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  ASSUMPTION: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  DERIVED: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
}

export const inputCls = "w-full bg-[#0d1117] border border-dark-border rounded-lg px-4 py-2 focus:outline-none focus:border-brand-purple transition-colors text-sm"
export const inputClsDisabled = "w-full bg-[#0d1117]/50 border border-dark-border rounded-lg px-4 py-2 text-sm text-gray-600 cursor-not-allowed"

// Editable status badge: pick a field's confidence tag straight from the web
// UI. onChange omitted -> read-only badge (still shows current status).
export function TagSelect({ tag, validTags, onChange }: { tag?: string; validTags: string[]; onChange?: (tag: string) => void }) {
  if (!tag) return null
  const cls = TAG_COLOR[tag] ?? TAG_COLOR.DERIVED
  return (
    <select
      value={tag}
      onChange={e => onChange?.(e.target.value)}
      disabled={!onChange}
      title="Click to reclassify this parameter's confidence status"
      className={`px-1.5 py-0.5 text-[10px] rounded border whitespace-nowrap bg-transparent ${cls} ${onChange ? 'cursor-pointer' : ''}`}
    >
      {(validTags.length ? validTags : [tag]).map(t => (
        <option key={t} value={t} className="bg-[#161b22] text-white">{t}</option>
      ))}
    </select>
  )
}

export function Field({ label, tag, validTags, onTagChange, note, children }: {
  label: string; tag?: string; validTags?: string[]; onTagChange?: (tag: string) => void; note?: string; children: React.ReactNode
}) {
  return (
    <div>
      <div className="flex justify-between items-center mb-1">
        <label className="block text-sm font-medium text-gray-400">{label}</label>
        <TagSelect tag={tag} validTags={validTags ?? []} onChange={onTagChange} />
      </div>
      {children}
      {note && <p className="text-[11px] text-gray-600 mt-1">{note}</p>}
    </div>
  )
}
