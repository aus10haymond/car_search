import { useState, useEffect, useCallback } from 'react'
import { api, type Profile, type DocFile } from '../api/client'
import { useAuth } from '../App'
import { ProfileForm } from '../components/ProfileForm'

type Tab = 'profile' | 'docs'

function Err({ msg }: { msg: string }) {
  return <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-3">{msg}</div>
}

const inputCls = 'block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'

// ══════════════════════════════════════════════════════════════════════════════
// Profile tab — edit own profile
// ══════════════════════════════════════════════════════════════════════════════

function ProfileTab({ docs }: { docs: DocFile[] }) {
  const { } = useAuth()
  const [profile, setProfile] = useState<Profile | null>(null)
  const [editing, setEditing] = useState(false)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const load = useCallback(async () => {
    try {
      const list = await api.profiles.list()
      setProfile(list[0] ?? null)
    } catch (e) { setErr(e instanceof Error ? e.message : 'Load failed') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const save = async (p: Profile) => {
    if (!profile) return
    await api.profiles.update(profile.profile_id, p)
    setEditing(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
    load()
  }

  if (loading) return <div className="text-sm text-gray-400 py-8 text-center">Loading your profile…</div>

  if (!profile) {
    return (
      <div className="py-12 text-center">
        <div className="text-gray-400 text-sm">No profile assigned to your account.</div>
        <p className="text-gray-400 text-xs mt-1">Ask an admin to assign you a profile.</p>
      </div>
    )
  }

  const vehicles = profile.vehicles.map(v => v.join(' ')).join(', ')
  const fuels = profile.fuel_type_filters.includes(null)
    ? 'All fuel types'
    : (profile.fuel_type_filters.filter(Boolean) as string[]).join(', ')

  return (
    <div className="max-w-2xl">
      {err && <div className="mb-4"><Err msg={err} /></div>}
      {saved && (
        <div className="mb-4 text-sm text-green-700 bg-green-50 border border-green-200 rounded p-3">
          Profile saved.
        </div>
      )}

      {/* Profile summary card */}
      <div className="bg-white border border-gray-200 rounded-xl p-6 mb-4">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">{profile.label}</h2>
            <p className="text-xs font-mono text-gray-400 mt-0.5">{profile.profile_id}</p>
          </div>
          <button onClick={() => setEditing(true)}
            className="px-3 py-1.5 text-sm text-indigo-600 border border-indigo-300 rounded-md hover:bg-indigo-50">
            Edit profile
          </button>
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
          <div>
            <dt className="text-xs text-gray-400 font-medium uppercase tracking-wide">Vehicles</dt>
            <dd className="text-gray-800 mt-0.5">{vehicles}</dd>
          </div>
          <div>
            <dt className="text-xs text-gray-400 font-medium uppercase tracking-wide">Fuel types</dt>
            <dd className="text-gray-800 mt-0.5">{fuels}</dd>
          </div>
          <div>
            <dt className="text-xs text-gray-400 font-medium uppercase tracking-wide">Max price</dt>
            <dd className="text-gray-800 mt-0.5">
              {profile.max_price != null ? `$${profile.max_price.toLocaleString()}` : 'No limit'}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-gray-400 font-medium uppercase tracking-wide">Max mileage</dt>
            <dd className="text-gray-800 mt-0.5">{profile.max_mileage.toLocaleString()} mi</dd>
          </div>
          <div>
            <dt className="text-xs text-gray-400 font-medium uppercase tracking-wide">Year range</dt>
            <dd className="text-gray-800 mt-0.5">{profile.min_year}–{profile.max_year}</dd>
          </div>
          <div>
            <dt className="text-xs text-gray-400 font-medium uppercase tracking-wide">Email alerts</dt>
            <dd className="text-gray-800 mt-0.5">
              {profile.email_only_on_new_or_drops ? 'New/drops only' : 'All qualifying'}
            </dd>
          </div>
          <div className="col-span-2">
            <dt className="text-xs text-gray-400 font-medium uppercase tracking-wide">Email recipients</dt>
            <dd className="text-gray-800 mt-0.5">{profile.email_to.join(', ') || '—'}</dd>
          </div>
          {profile.reference_doc_path && (
            <div className="col-span-2">
              <dt className="text-xs text-gray-400 font-medium uppercase tracking-wide">Reference doc</dt>
              <dd className="text-gray-800 mt-0.5 font-mono text-xs">{profile.reference_doc_path}</dd>
            </div>
          )}
          {profile.excluded_trim_keywords.length > 0 && (
            <div className="col-span-2">
              <dt className="text-xs text-gray-400 font-medium uppercase tracking-wide">Excluded trims</dt>
              <dd className="text-gray-800 mt-0.5">{profile.excluded_trim_keywords.join(', ')}</dd>
            </div>
          )}
          {profile.model_preference.length > 0 && (
            <div className="col-span-2">
              <dt className="text-xs text-gray-400 font-medium uppercase tracking-wide">Model preference</dt>
              <dd className="text-gray-800 mt-0.5">{profile.model_preference.join(' > ')}</dd>
            </div>
          )}
        </dl>
      </div>

      {editing && profile && (
        <ProfileForm
          initial={profile}
          docs={docs}
          onSave={save}
          onClose={() => setEditing(false)}
        />
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Docs tab — view docs relevant to their profile's vehicles + generate new
// ══════════════════════════════════════════════════════════════════════════════

function DocsTab() {
  const { user } = useAuth()
  const [docs, setDocs] = useState<DocFile[]>([])
  const [profile, setProfile] = useState<Profile | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [viewing, setViewing] = useState<{ filename: string; content: string } | null>(null)
  const [showGenerator, setShowGenerator] = useState(false)

  const load = useCallback(async () => {
    try {
      const [d, profiles] = await Promise.all([api.docs.list(), api.profiles.list()])
      setDocs(d)
      setProfile(profiles[0] ?? null)
    } catch (e) { setErr(e instanceof Error ? e.message : 'Load failed') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const openDoc = async (filename: string) => {
    try { setViewing(await api.docs.get(filename)) }
    catch (e) { setErr(e instanceof Error ? e.message : 'Load failed') }
  }

  const saveDoc = async () => {
    if (!viewing) return
    try { await api.docs.put(viewing.filename, viewing.content); setViewing(null); load() }
    catch (e) { setErr(e instanceof Error ? e.message : 'Save failed') }
  }

  if (loading) return <div className="text-sm text-gray-400 py-8 text-center">Loading…</div>

  // Highlight docs that match their profile's vehicles
  const matchedDocNames = new Set(
    docs.filter(d => d.matched_profiles.includes(user?.profile_id ?? '')).map(d => d.filename)
  )
  const relevantDocs = docs.filter(d => matchedDocNames.has(d.filename))
  const otherDocs = docs.filter(d => !matchedDocNames.has(d.filename))

  return (
    <div className="max-w-3xl">
      {err && <div className="mb-4"><Err msg={err} /></div>}

      <div className="flex justify-between items-center mb-4">
        <h2 className="text-base font-semibold text-gray-800">Vehicle Reference Docs</h2>
        <button onClick={() => setShowGenerator(true)}
          className="px-3 py-1.5 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700">
          + Generate new doc
        </button>
      </div>

      {relevantDocs.length > 0 && (
        <div className="mb-6">
          <p className="text-xs text-gray-400 mb-2 uppercase font-medium tracking-wide">Matched to your profile</p>
          <div className="divide-y divide-gray-100 border border-indigo-200 rounded-lg overflow-hidden">
            {relevantDocs.map(d => (
              <div key={d.filename} className="flex items-center gap-4 px-4 py-3 bg-indigo-50/40 hover:bg-indigo-50">
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm text-gray-900 font-mono">{d.filename}</div>
                  <div className="text-xs text-gray-400 mt-0.5">{(d.size_bytes / 1024).toFixed(1)} KB</div>
                </div>
                <button onClick={() => openDoc(d.filename)}
                  className="text-xs px-2.5 py-1 text-indigo-600 border border-indigo-300 rounded hover:bg-indigo-50">
                  View/Edit
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {otherDocs.length > 0 && (
        <div>
          <p className="text-xs text-gray-400 mb-2 uppercase font-medium tracking-wide">Other docs</p>
          <div className="divide-y divide-gray-100 border border-gray-200 rounded-lg overflow-hidden">
            {otherDocs.map(d => (
              <div key={d.filename} className="flex items-center gap-4 px-4 py-3 bg-white hover:bg-gray-50">
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm text-gray-900 font-mono">{d.filename}</div>
                  <div className="text-xs text-gray-400 mt-0.5">{(d.size_bytes / 1024).toFixed(1)} KB</div>
                </div>
                <button onClick={() => openDoc(d.filename)}
                  className="text-xs px-2.5 py-1 text-gray-600 border border-gray-300 rounded hover:bg-gray-50">
                  View
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {docs.length === 0 && (
        <div className="py-12 text-center">
          <p className="text-sm text-gray-400">No reference docs yet.</p>
          <p className="text-xs text-gray-400 mt-1">Generate one for a vehicle you're searching for.</p>
        </div>
      )}

      {/* Doc viewer/editor */}
      {viewing && (
        <div className="fixed inset-0 z-40 flex">
          <div className="fixed inset-0 bg-black/40" onClick={() => setViewing(null)} />
          <div className="relative ml-auto w-full max-w-3xl bg-white h-full overflow-y-auto shadow-xl z-50 flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
              <h2 className="text-base font-semibold text-gray-900 font-mono">{viewing.filename}</h2>
              <button onClick={() => setViewing(null)} className="text-gray-400 hover:text-gray-600 text-xl">×</button>
            </div>
            <div className="flex-1 p-4">
              <textarea
                className="w-full h-full min-h-[600px] font-mono text-xs border border-gray-200 rounded p-3 focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
                value={viewing.content}
                onChange={e => setViewing(v => v ? { ...v, content: e.target.value } : v)}
              />
            </div>
            <div className="px-6 py-4 border-t border-gray-200 flex gap-3">
              <button onClick={saveDoc} className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700">Save</button>
              <button onClick={() => setViewing(null)} className="px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-md hover:bg-gray-50">Cancel</button>
            </div>
          </div>
        </div>
      )}

      {showGenerator && (
        <UserGeneratorModal
          profile={profile}
          onClose={() => setShowGenerator(false)}
          onSaved={() => { setShowGenerator(false); load() }}
        />
      )}
    </div>
  )
}

function UserGeneratorModal({ profile, onClose, onSaved }: {
  profile: Profile | null
  onClose: () => void
  onSaved: () => void
}) {
  // Pre-fill make/model from profile if available
  const firstVehicle = profile?.vehicles[0]
  const [make, setMake] = useState(firstVehicle?.[0] ?? '')
  const [model, setModel] = useState(firstVehicle?.[1] ?? '')
  const [yearStart, setYearStart] = useState(profile?.min_year ?? 2021)
  const [yearEnd, setYearEnd] = useState(profile?.max_year ?? 2025)
  const [notes, setNotes] = useState('')
  const [generating, setGenerating] = useState(false)
  const [generated, setGenerated] = useState<string | null>(null)
  const [filename, setFilename] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const generate = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr(null); setGenerating(true)
    try {
      const res = await api.docs.generate(make, model, yearStart, yearEnd, notes)
      setGenerated(res.content)
      const slug = `${make}_${model}`.toLowerCase().replace(/[^a-z0-9]+/g, '_')
      setFilename(`${slug}.md`)
    } catch (e) { setErr(e instanceof Error ? e.message : 'Generation failed') }
    finally { setGenerating(false) }
  }

  const save = async () => {
    if (!generated || !filename) return
    setSaving(true); setErr(null)
    try { await api.docs.put(filename, generated); onSaved() }
    catch (e) { setErr(e instanceof Error ? e.message : 'Save failed') }
    finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 z-40 flex">
      <div className="fixed inset-0 bg-black/40" onClick={onClose} />
      <div className="relative ml-auto w-full max-w-2xl bg-white h-full overflow-y-auto shadow-xl z-50 flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">Generate Vehicle Reference Doc</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">×</button>
        </div>

        <div className="flex-1 p-6 space-y-4">
          {err && <Err msg={err} />}

          {!generated ? (
            <form onSubmit={generate} className="space-y-4">
              <p className="text-sm text-gray-500">
                Claude will generate a detailed reference guide for evaluating used listings.
              </p>
              {profile && profile.vehicles.length > 1 && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Quick select from your profile</label>
                  <div className="flex flex-wrap gap-2">
                    {profile.vehicles.map((v, i) => (
                      <button key={i} type="button"
                        onClick={() => { setMake(v[0]); setModel(v[1]) }}
                        className="text-xs px-2.5 py-1 border border-gray-300 rounded hover:border-indigo-400 hover:bg-indigo-50">
                        {v[0]} {v[1]}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Make</label>
                  <input className={inputCls} required placeholder="Honda" value={make} onChange={e => setMake(e.target.value)} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Model</label>
                  <input className={inputCls} required placeholder="CR-V" value={model} onChange={e => setModel(e.target.value)} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Year start</label>
                  <input type="number" className={inputCls} required value={yearStart} onChange={e => setYearStart(Number(e.target.value))} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Year end</label>
                  <input type="number" className={inputCls} required value={yearEnd} onChange={e => setYearEnd(Number(e.target.value))} />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Buyer context <span className="text-gray-400 font-normal">(optional)</span></label>
                <textarea
                  className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
                  rows={3} placeholder="e.g. Located in Phoenix, AZ. Budget up to $30k. Prefer hybrid trims."
                  value={notes} onChange={e => setNotes(e.target.value)}
                />
              </div>
              <button type="submit" disabled={generating}
                className="w-full bg-indigo-600 text-white rounded-md py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-50">
                {generating ? 'Generating with Claude…' : 'Generate reference doc'}
              </button>
            </form>
          ) : (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <div className="flex-1">
                  <label className="block text-sm font-medium text-gray-700 mb-1">Save as filename</label>
                  <input className={inputCls} value={filename} onChange={e => setFilename(e.target.value)}
                    pattern="[\w\-]+\.md" title="e.g. honda_crv.md" />
                </div>
                <button onClick={() => setGenerated(null)} className="mt-5 text-sm text-indigo-600 hover:underline shrink-0">
                  Regenerate
                </button>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Generated content (editable before saving)</label>
                <textarea
                  className="w-full font-mono text-xs border border-gray-200 rounded p-3 focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
                  rows={20}
                  value={generated}
                  onChange={e => setGenerated(e.target.value)}
                />
              </div>
              <div className="flex gap-3">
                <button onClick={save} disabled={saving}
                  className="flex-1 bg-indigo-600 text-white rounded-md py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-50">
                  {saving ? 'Saving…' : 'Save doc'}
                </button>
                <button onClick={onClose}
                  className="px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-md hover:bg-gray-50">
                  Discard
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// User page shell
// ══════════════════════════════════════════════════════════════════════════════

export default function UserPage() {
  const { user, logout } = useAuth()
  const [tab, setTab] = useState<Tab>('profile')
  const [docs, setDocs] = useState<DocFile[]>([])

  useEffect(() => {
    api.docs.list().then(setDocs).catch(() => {})
  }, [])

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top bar */}
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-4xl mx-auto px-4 h-14 flex items-center gap-4">
          <div className="flex items-center gap-2">
            <img src={`${import.meta.env.BASE_URL}autospy-logo.png`} alt="Autospy" className="w-7 h-7" />
            <span className="font-semibold text-gray-900 text-sm">Autospy</span>
          </div>
          <div className="flex-1" />
          <span className="text-sm text-gray-500">{user?.username}</span>
          <button onClick={logout} className="text-sm text-gray-500 hover:text-gray-700 border border-gray-300 rounded px-2.5 py-1 hover:bg-gray-50">
            Sign out
          </button>
        </div>

        <div className="max-w-4xl mx-auto px-4 flex gap-1">
          {(['profile', 'docs'] as Tab[]).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors capitalize ${
                tab === t
                  ? 'border-indigo-600 text-indigo-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}>
              {t === 'profile' ? 'My Profile' : 'Reference Docs'}
            </button>
          ))}
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 py-6">
        {tab === 'profile' && <ProfileTab docs={docs} />}
        {tab === 'docs'    && <DocsTab />}
      </main>
    </div>
  )
}
