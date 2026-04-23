import { useState, useEffect } from 'react'
import type { Profile, DocFile } from '../api/client'

interface Props {
  initial?: Profile | null
  docs: DocFile[]
  onSave: (p: Profile) => Promise<void>
  onClose: () => void
}

const EMPTY: Profile = {
  profile_id: '', label: '', vehicles: [['', '']], max_price: null,
  max_mileage: 80000, min_year: 2020, max_year: 2025, email_to: [],
  fuel_type_filters: [null], model_preference: [], reference_doc_path: null,
  excluded_trim_keywords: [], excluded_years: [], show_financing: true, down_payment: null,
  email_only_on_new_or_drops: false,
}

// Simple tag-input: Enter/comma adds, click removes
function TagInput({ values, onChange, type = 'text', placeholder }: {
  values: string[]; onChange: (v: string[]) => void; type?: string; placeholder?: string
}) {
  const [draft, setDraft] = useState('')
  const add = () => {
    const t = draft.trim()
    if (t && !values.includes(t)) onChange([...values, t])
    setDraft('')
  }
  return (
    <div className="flex flex-wrap gap-1 min-h-[36px] border border-gray-300 rounded-md px-2 py-1 focus-within:ring-2 focus-within:ring-indigo-500 focus-within:border-indigo-500">
      {values.map(v => (
        <span key={v} className="inline-flex items-center gap-1 bg-indigo-100 text-indigo-800 text-xs rounded px-2 py-0.5">
          {v}
          <button type="button" onClick={() => onChange(values.filter(x => x !== v))} className="hover:text-red-600">×</button>
        </span>
      ))}
      <input
        type={type} value={draft} placeholder={placeholder}
        onChange={e => setDraft(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add() } }}
        onBlur={add}
        className="flex-1 min-w-[120px] outline-none text-sm bg-transparent"
      />
    </div>
  )
}

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      {children}
      {hint && <p className="text-xs text-gray-400 mt-0.5">{hint}</p>}
    </div>
  )
}

const inputCls = 'block w-full rounded-md border-gray-300 border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500'

export function ProfileForm({ initial, docs, onSave, onClose }: Props) {
  const isEdit = Boolean(initial)
  const [form, setForm] = useState<Profile>(initial ?? EMPTY)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { setForm(initial ?? EMPTY) }, [initial])

  const set = <K extends keyof Profile>(k: K, v: Profile[K]) =>
    setForm(f => ({ ...f, [k]: v }))

  // Fuel type helpers
  const FUELS = ['Gas', 'Hybrid']
  const activeFuels = form.fuel_type_filters.filter(Boolean) as string[]
  const hasAll = form.fuel_type_filters.includes(null)
  const toggleFuel = (fuel: string) => {
    const active = activeFuels.includes(fuel)
      ? activeFuels.filter(f => f !== fuel)
      : [...activeFuels, fuel]
    set('fuel_type_filters', active.length ? active : [null])
  }
  const toggleAll = () => set('fuel_type_filters', hasAll ? [] : [null])

  // Vehicles
  const setVehicle = (i: number, idx: 0 | 1, val: string) => {
    const updated = form.vehicles.map((v, j) => j === i ? (idx === 0 ? [val, v[1]] : [v[0], val]) as [string, string] : v)
    set('vehicles', updated)
    // Sync model_preference to vehicle model list
    const models = updated.map(v => v[1]).filter(Boolean)
    const pref = form.model_preference.filter(m => models.includes(m))
    const added = models.filter(m => !pref.includes(m))
    set('model_preference', [...pref, ...added])
  }
  const addVehicle = () => set('vehicles', [...form.vehicles, ['', '']])
  const removeVehicle = (i: number) => {
    const updated = form.vehicles.filter((_, j) => j !== i)
    set('vehicles', updated)
    const models = updated.map(v => v[1]).filter(Boolean)
    set('model_preference', form.model_preference.filter(m => models.includes(m)))
  }

  // Model preference ordering
  const moveModel = (i: number, dir: -1 | 1) => {
    const arr = [...form.model_preference]
    const j = i + dir
    if (j < 0 || j >= arr.length) return
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
    set('model_preference', arr)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await onSave(form)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    /* Slide-over overlay */
    <div className="fixed inset-0 z-40 flex">
      <div className="fixed inset-0 bg-black/40" onClick={onClose} />
      <div className="relative ml-auto w-full max-w-xl bg-white h-full overflow-y-auto shadow-xl z-50 flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">
            {isEdit ? `Edit: ${initial?.label}` : 'New Profile'}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
          {error && (
            <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-3">{error}</div>
          )}

          <Field label="Profile ID" hint="Lowercase letters, numbers, underscores only. Cannot be changed after creation.">
            <input
              className={inputCls} value={form.profile_id} required
              pattern="[a-z0-9_]+" title="[a-z0-9_]+ only"
              disabled={isEdit}
              onChange={e => set('profile_id', e.target.value)}
            />
          </Field>

          <Field label="Label">
            <input className={inputCls} value={form.label} required onChange={e => set('label', e.target.value)} />
          </Field>

          {/* Vehicles */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Vehicles</label>
            <div className="space-y-2">
              {form.vehicles.map((v, i) => (
                <div key={i} className="flex gap-2 items-center">
                  <input className={`${inputCls} flex-1`} placeholder="Make" value={v[0]} onChange={e => setVehicle(i, 0, e.target.value)} />
                  <input className={`${inputCls} flex-1`} placeholder="Model" value={v[1]} onChange={e => setVehicle(i, 1, e.target.value)} />
                  <button type="button" onClick={() => removeVehicle(i)} disabled={form.vehicles.length === 1}
                    className="text-gray-400 hover:text-red-500 disabled:opacity-30 px-1">✕</button>
                </div>
              ))}
            </div>
            <button type="button" onClick={addVehicle} className="mt-2 text-sm text-indigo-600 hover:underline">+ Add vehicle</button>
          </div>

          {/* Fuel types */}
          <Field label="Fuel types">
            <div className="flex flex-wrap gap-2">
              {(['All', ...FUELS] as const).map(f => {
                const isAll = f === 'All'
                const active = isAll ? hasAll : activeFuels.includes(f)
                return (
                  <button key={f} type="button"
                    onClick={() => isAll ? toggleAll() : toggleFuel(f)}
                    className={`px-3 py-1 rounded-full text-sm border transition-colors ${
                      active ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-gray-600 border-gray-300 hover:border-indigo-400'
                    }`}
                  >{f}</button>
                )
              })}
            </div>
          </Field>

          {/* Price / mileage / years */}
          <div className="grid grid-cols-2 gap-4">
            <Field label="Max price">
              <div className="space-y-1">
                <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
                  <input type="checkbox" checked={form.max_price === null}
                    onChange={e => set('max_price', e.target.checked ? null : 30000)} />
                  No limit
                </label>
                {form.max_price !== null && (
                  <input type="number" className={inputCls} value={form.max_price}
                    onChange={e => set('max_price', Number(e.target.value))} />
                )}
              </div>
            </Field>
            <Field label="Max mileage">
              <input type="number" className={inputCls} value={form.max_mileage} required
                onChange={e => set('max_mileage', Number(e.target.value))} />
            </Field>
            <Field label="Min year">
              <input type="number" className={inputCls} value={form.min_year} required
                onChange={e => set('min_year', Number(e.target.value))} />
            </Field>
            <Field label="Max year">
              <input type="number" className={inputCls} value={form.max_year} required
                onChange={e => set('max_year', Number(e.target.value))} />
            </Field>
          </div>

          {/* Model preference */}
          {form.model_preference.length > 0 && (
            <Field label="Model preference" hint="Drag-free: use arrows to reorder best → worst">
              <div className="space-y-1">
                {form.model_preference.map((m, i) => (
                  <div key={m} className="flex items-center gap-2 bg-gray-50 rounded px-2 py-1 text-sm">
                    <span className="text-gray-400 w-5 text-center text-xs">{i + 1}</span>
                    <span className="flex-1 font-medium">{m}</span>
                    <button type="button" onClick={() => moveModel(i, -1)} disabled={i === 0} className="text-gray-400 hover:text-gray-700 disabled:opacity-30">↑</button>
                    <button type="button" onClick={() => moveModel(i, 1)} disabled={i === form.model_preference.length - 1} className="text-gray-400 hover:text-gray-700 disabled:opacity-30">↓</button>
                  </div>
                ))}
              </div>
            </Field>
          )}

          {/* Email */}
          <Field label="Email recipients" hint="Press Enter or comma to add each address">
            <TagInput values={form.email_to} onChange={v => set('email_to', v)} type="email" placeholder="you@example.com" />
          </Field>

          {/* Excluded trim keywords */}
          <Field label="Excluded trim keywords" hint="Case-insensitive substrings, e.g. Sport, MAX">
            <TagInput values={form.excluded_trim_keywords} onChange={v => set('excluded_trim_keywords', v)} placeholder="Sport" />
          </Field>

          {/* Excluded years */}
          <Field label="Excluded years" hint="Specific years to skip within min/max range">
            <TagInput
              values={form.excluded_years.map(String)}
              onChange={v => set('excluded_years', v.map(Number).filter(n => !isNaN(n)))}
              type="number" placeholder="2022"
            />
          </Field>

          {/* Financing */}
          <div className="grid grid-cols-2 gap-4">
            <Field label="Show financing column">
              <label className="flex items-center gap-2 text-sm cursor-pointer mt-1">
                <input type="checkbox" checked={form.show_financing}
                  onChange={e => set('show_financing', e.target.checked)} />
                Show est. payment in email table
              </label>
            </Field>
            <Field label="Down payment">
              <div className="space-y-1">
                <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
                  <input type="checkbox" checked={form.down_payment === null}
                    onChange={e => set('down_payment', e.target.checked ? null : 3000)} />
                  Use global default
                </label>
                {form.down_payment !== null && (
                  <input type="number" className={inputCls} value={form.down_payment}
                    onChange={e => set('down_payment', Number(e.target.value))} />
                )}
              </div>
            </Field>
          </div>

          {/* Email alert mode */}
          <Field label="Email alert mode" hint="When enabled, emails are only sent when new vehicles appear for the first time or an existing vehicle drops in price. Disables the normal value-score / under-budget triggers.">
            <label className="flex items-center gap-2 text-sm cursor-pointer mt-1">
              <input type="checkbox" checked={form.email_only_on_new_or_drops}
                onChange={e => set('email_only_on_new_or_drops', e.target.checked)} />
              Only email on new listings or price drops
            </label>
          </Field>

          {/* Reference doc */}
          <Field label="Reference doc" hint='Auto-discover finds matching files in vehicle_reference/. "Manual" lets you pick one.'>
            <select className={inputCls} value={form.reference_doc_path ?? ''}
              onChange={e => set('reference_doc_path', e.target.value || null)}>
              <option value="">Auto-discover</option>
              {docs.map(d => (
                <option key={d.filename} value={`./vehicle_reference/${d.filename}`}>{d.filename}</option>
              ))}
            </select>
          </Field>

          <div className="pt-2 pb-6 flex gap-3">
            <button type="submit" disabled={saving}
              className="flex-1 bg-indigo-600 text-white rounded-md py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-50">
              {saving ? 'Saving…' : isEdit ? 'Save changes' : 'Create profile'}
            </button>
            <button type="button" onClick={onClose}
              className="px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-md hover:bg-gray-50">
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
