import { useState, useEffect, useCallback } from 'react'
import { api, type Profile, type DocFile, type PortalUser, type Settings } from '../api/client'
import { useAuth } from '../App'
import { ProfileForm } from '../components/ProfileForm'

type Tab = 'profiles' | 'docs' | 'settings' | 'users'

// ── Shared UI helpers ─────────────────────────────────────────────────────────

const inputCls = 'block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'

function Err({ msg }: { msg: string }) {
  return <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-3">{msg}</div>
}

// ══════════════════════════════════════════════════════════════════════════════
// Profiles tab
// ══════════════════════════════════════════════════════════════════════════════

function ProfilesTab({ docs }: { docs: DocFile[] }) {
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [editing, setEditing] = useState<Profile | null | 'new'>(null)

  const load = useCallback(async () => {
    try { setProfiles(await api.profiles.list()) }
    catch (e) { setErr(e instanceof Error ? e.message : 'Load failed') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const save = async (p: Profile) => {
    if (editing === 'new') await api.profiles.create(p)
    else await api.profiles.update(p.profile_id, p)
    setEditing(null)
    load()
  }

  const del = async (id: string) => {
    if (!confirm(`Delete profile "${id}"? This cannot be undone.`)) return
    try { await api.profiles.delete(id); load() }
    catch (e) { setErr(e instanceof Error ? e.message : 'Delete failed') }
  }

  if (loading) return <div className="text-sm text-gray-400 py-8 text-center">Loading profiles…</div>

  return (
    <div>
      {err && <div className="mb-4"><Err msg={err} /></div>}
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-base font-semibold text-gray-800">Profiles ({profiles.length})</h2>
        <button onClick={() => setEditing('new')}
          className="px-3 py-1.5 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700">
          + New profile
        </button>
      </div>

      {profiles.length === 0
        ? <div className="text-sm text-gray-400 py-8 text-center">No profiles yet.</div>
        : (
          <div className="divide-y divide-gray-100 border border-gray-200 rounded-lg overflow-hidden">
            {profiles.map(p => (
              <div key={p.profile_id} className="flex items-center gap-4 px-4 py-3 bg-white hover:bg-gray-50">
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm text-gray-900">{p.label}</div>
                  <div className="text-xs text-gray-400 font-mono">{p.profile_id}</div>
                  <div className="text-xs text-gray-500 mt-0.5">
                    {p.vehicles.map(v => v.join(' ')).join(' · ')}
                    {' · '}${p.max_price?.toLocaleString() ?? 'no limit'} max
                    {' · '}{p.min_year}–{p.max_year}
                  </div>
                </div>
                <div className="flex gap-2 shrink-0">
                  <button onClick={() => setEditing(p)}
                    className="text-xs px-2.5 py-1 text-indigo-600 border border-indigo-300 rounded hover:bg-indigo-50">
                    Edit
                  </button>
                  <button onClick={() => del(p.profile_id)}
                    className="text-xs px-2.5 py-1 text-red-600 border border-red-300 rounded hover:bg-red-50">
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )
      }

      {editing !== null && (
        <ProfileForm
          initial={editing === 'new' ? null : editing}
          docs={docs}
          onSave={save}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Docs tab
// ══════════════════════════════════════════════════════════════════════════════

function DocsTab() {
  const [docs, setDocs] = useState<DocFile[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [viewing, setViewing] = useState<{ filename: string; content: string } | null>(null)
  const [showGenerator, setShowGenerator] = useState(false)

  const load = useCallback(async () => {
    try { setDocs(await api.docs.list()) }
    catch (e) { setErr(e instanceof Error ? e.message : 'Load failed') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const openDoc = async (filename: string) => {
    try {
      const d = await api.docs.get(filename)
      setViewing(d)
    } catch (e) { setErr(e instanceof Error ? e.message : 'Load failed') }
  }

  const saveDoc = async () => {
    if (!viewing) return
    try {
      await api.docs.put(viewing.filename, viewing.content)
      setViewing(null)
      load()
    } catch (e) { setErr(e instanceof Error ? e.message : 'Save failed') }
  }

  const delDoc = async (filename: string) => {
    if (!confirm(`Delete "${filename}"?`)) return
    try { await api.docs.delete(filename); load() }
    catch (e) { setErr(e instanceof Error ? e.message : 'Delete failed') }
  }

  if (loading) return <div className="text-sm text-gray-400 py-8 text-center">Loading docs…</div>

  return (
    <div>
      {err && <div className="mb-4"><Err msg={err} /></div>}
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-base font-semibold text-gray-800">Vehicle Reference Docs ({docs.length})</h2>
        <button onClick={() => setShowGenerator(true)}
          className="px-3 py-1.5 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700">
          + Generate new doc
        </button>
      </div>

      {docs.length === 0
        ? <div className="text-sm text-gray-400 py-8 text-center">No reference docs yet.</div>
        : (
          <div className="divide-y divide-gray-100 border border-gray-200 rounded-lg overflow-hidden">
            {docs.map(d => (
              <div key={d.filename} className="flex items-center gap-4 px-4 py-3 bg-white hover:bg-gray-50">
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm text-gray-900 font-mono">{d.filename}</div>
                  <div className="text-xs text-gray-400 mt-0.5">
                    {(d.size_bytes / 1024).toFixed(1)} KB
                    {d.matched_profiles.length > 0 && ` · used by: ${d.matched_profiles.join(', ')}`}
                  </div>
                </div>
                <div className="flex gap-2 shrink-0">
                  <button onClick={() => openDoc(d.filename)}
                    className="text-xs px-2.5 py-1 text-indigo-600 border border-indigo-300 rounded hover:bg-indigo-50">
                    View/Edit
                  </button>
                  <button onClick={() => delDoc(d.filename)}
                    className="text-xs px-2.5 py-1 text-red-600 border border-red-300 rounded hover:bg-red-50">
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )
      }

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
              <button onClick={saveDoc} className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700">
                Save
              </button>
              <button onClick={() => setViewing(null)} className="px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-md hover:bg-gray-50">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Generator modal */}
      {showGenerator && (
        <GeneratorModal
          onClose={() => setShowGenerator(false)}
          onSaved={() => { setShowGenerator(false); load() }}
        />
      )}
    </div>
  )
}

function GeneratorModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [make, setMake] = useState('')
  const [model, setModel] = useState('')
  const [yearStart, setYearStart] = useState(2021)
  const [yearEnd, setYearEnd] = useState(2025)
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
    try {
      await api.docs.put(filename, generated)
      onSaved()
    } catch (e) { setErr(e instanceof Error ? e.message : 'Save failed') }
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
                Uses AI to generate a comprehensive reference guide for evaluating used listings.
              </p>
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
                {generating ? 'Generating…' : 'Generate reference doc'}
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
                <label className="block text-sm font-medium text-gray-700 mb-1">Generated content (editable)</label>
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
// Settings tab
// ══════════════════════════════════════════════════════════════════════════════

function SettingsTab() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.settings.get()
      .then(s => setSettings(s))
      .catch(e => setErr(e instanceof Error ? e.message : 'Load failed'))
      .finally(() => setLoading(false))
  }, [])

  const update = (key: string, value: unknown) =>
    setSettings(s => s ? { ...s, [key]: value } : s)

  const save = async () => {
    if (!settings) return
    setSaving(true); setErr(null); setSaved(false)
    try {
      await api.settings.patch(settings)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e) { setErr(e instanceof Error ? e.message : 'Save failed') }
    finally { setSaving(false) }
  }

  if (loading) return <div className="text-sm text-gray-400 py-8 text-center">Loading settings…</div>
  if (!settings) return <Err msg={err ?? 'Failed to load settings'} />

  const numField = (key: string, label: string, hint?: string) => (
    <div key={key}>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      <input type="number" className={inputCls}
        value={settings[key] as number ?? ''}
        onChange={e => update(key, Number(e.target.value))} />
      {hint && <p className="text-xs text-gray-400 mt-0.5">{hint}</p>}
    </div>
  )

  const boolField = (key: string, label: string, hint?: string) => (
    <div key={key}>
      <label className="flex items-center gap-2 text-sm font-medium text-gray-700 cursor-pointer">
        <input type="checkbox" checked={Boolean(settings[key])}
          onChange={e => update(key, e.target.checked)} />
        {label}
      </label>
      {hint && <p className="text-xs text-gray-400 mt-0.5 ml-5">{hint}</p>}
    </div>
  )

  const strField = (key: string, label: string, hint?: string) => (
    <div key={key}>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      <input className={inputCls} value={String(settings[key] ?? '')}
        onChange={e => update(key, e.target.value)} />
      {hint && <p className="text-xs text-gray-400 mt-0.5">{hint}</p>}
    </div>
  )

  return (
    <div className="max-w-2xl space-y-8">
      {err && <Err msg={err} />}
      {saved && <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded p-3">Settings saved.</div>}

      <section>
        <h3 className="text-sm font-semibold text-gray-900 mb-3 uppercase tracking-wide">Location & Payment</h3>
        <div className="grid grid-cols-2 gap-4">
          {strField('zip_code', 'ZIP code')}
          {numField('down_payment', 'Down payment ($)')}
          {numField('interest_rate', 'Interest rate (%)')}
          {numField('loan_term_months', 'Loan term (months)')}
        </div>
      </section>

      <section>
        <h3 className="text-sm font-semibold text-gray-900 mb-3 uppercase tracking-wide">Email</h3>
        <div className="space-y-3">
          {boolField('send_email', 'Send email alerts')}
        </div>
      </section>

      <section>
        <h3 className="text-sm font-semibold text-gray-900 mb-3 uppercase tracking-wide">Scraping</h3>
        <div className="grid grid-cols-2 gap-4">
          {numField('max_pages_per_search', 'Max pages per search')}
          {numField('request_delay_seconds', 'Request delay (seconds)')}
          {numField('page_timeout_seconds', 'Page timeout (seconds)')}
        </div>
        <div className="mt-3">
          {boolField('headless', 'Run browser headless')}
        </div>
      </section>

      <section>
        <h3 className="text-sm font-semibold text-gray-900 mb-3 uppercase tracking-wide">AI Analysis</h3>
        <div className="space-y-3">
          {boolField('anthropic_enabled', 'Enable Anthropic (Claude) API')}
          {strField('anthropic_model', 'Anthropic model')}
          {numField('anthropic_max_tokens', 'Max tokens per response')}
          {boolField('ollama_enabled', 'Enable Ollama (local LLM)')}
          {numField('ollama_timeout', 'Ollama timeout (seconds)')}
        </div>
      </section>

      <section>
        <h3 className="text-sm font-semibold text-gray-900 mb-3 uppercase tracking-wide">Output paths</h3>
        <div className="space-y-3">
          {strField('output_dir', 'Output directory')}
          {strField('vehicle_reference_dir', 'Vehicle reference directory')}
          {strField('db_path', 'Database path')}
          {strField('log_file', 'Log file path')}
        </div>
      </section>

      <div>
        <button onClick={save} disabled={saving}
          className="px-6 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700 disabled:opacity-50">
          {saving ? 'Saving…' : 'Save settings'}
        </button>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Users tab
// ══════════════════════════════════════════════════════════════════════════════

function UsersTab({ profiles }: { profiles: Profile[] }) {
  const { user: currentUser } = useAuth()
  const [users, setUsers] = useState<PortalUser[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [pwdTarget, setPwdTarget] = useState<string | null>(null)

  const load = useCallback(async () => {
    try { setUsers(await api.users.list()) }
    catch (e) { setErr(e instanceof Error ? e.message : 'Load failed') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const del = async (username: string) => {
    if (!confirm(`Delete user "${username}"?`)) return
    try { await api.users.delete(username); load() }
    catch (e) { setErr(e instanceof Error ? e.message : 'Delete failed') }
  }

  const assignProfile = async (username: string, profile_id: string | null) => {
    try { await api.users.assignProfile(username, profile_id); load() }
    catch (e) { setErr(e instanceof Error ? e.message : 'Assign failed') }
  }

  if (loading) return <div className="text-sm text-gray-400 py-8 text-center">Loading users…</div>

  return (
    <div>
      {err && <div className="mb-4"><Err msg={err} /></div>}
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-base font-semibold text-gray-800">Users ({users.length})</h2>
        <button onClick={() => setShowCreate(true)}
          className="px-3 py-1.5 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700">
          + New user
        </button>
      </div>

      <div className="divide-y divide-gray-100 border border-gray-200 rounded-lg overflow-hidden">
        {users.map(u => (
          <div key={u.username} className="flex items-center gap-4 px-4 py-3 bg-white hover:bg-gray-50">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium text-sm text-gray-900">{u.username}</span>
                <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                  u.role === 'admin' ? 'bg-indigo-100 text-indigo-700' : 'bg-gray-100 text-gray-600'
                }`}>{u.role}</span>
                {u.username === currentUser?.username && (
                  <span className="text-xs text-gray-400">(you)</span>
                )}
              </div>
            </div>
            {/* Profile assignment (non-admin users only) */}
            {u.role !== 'admin' && (
              <select
                className="text-sm border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                value={u.profile_id ?? ''}
                onChange={e => assignProfile(u.username, e.target.value || null)}
              >
                <option value="">— no profile —</option>
                {profiles.map(p => (
                  <option key={p.profile_id} value={p.profile_id}>{p.label}</option>
                ))}
              </select>
            )}
            <div className="flex gap-2 shrink-0">
              <button onClick={() => setPwdTarget(u.username)}
                className="text-xs px-2.5 py-1 text-gray-600 border border-gray-300 rounded hover:bg-gray-50">
                Password
              </button>
              {u.username !== currentUser?.username && (
                <button onClick={() => del(u.username)}
                  className="text-xs px-2.5 py-1 text-red-600 border border-red-300 rounded hover:bg-red-50">
                  Delete
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {showCreate && <CreateUserModal profiles={profiles} onClose={() => setShowCreate(false)} onCreated={load} />}
      {pwdTarget && <ChangePasswordModal username={pwdTarget} onClose={() => setPwdTarget(null)} />}
    </div>
  )
}

function CreateUserModal({ profiles, onClose, onCreated }: {
  profiles: Profile[]
  onClose: () => void
  onCreated: () => void
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('user')
  const [profileId, setProfileId] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true); setErr(null)
    try {
      await api.users.create(username, password, role, profileId || null)
      onCreated(); onClose()
    } catch (e) { setErr(e instanceof Error ? e.message : 'Create failed') }
    finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-white rounded-xl shadow-xl w-full max-w-md p-6 z-50">
        <h2 className="text-base font-semibold text-gray-900 mb-4">New User</h2>
        {err && <div className="mb-3"><Err msg={err} /></div>}
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
            <input className={inputCls} required value={username} onChange={e => setUsername(e.target.value)} />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input type="password" className={inputCls} required minLength={8} value={password} onChange={e => setPassword(e.target.value)} />
            <p className="text-xs text-gray-400 mt-0.5">At least 8 characters</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
            <select className={inputCls} value={role} onChange={e => setRole(e.target.value)}>
              <option value="user">User (profile only)</option>
              <option value="admin">Admin (full access)</option>
            </select>
          </div>
          {role === 'user' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Assign profile</label>
              <select className={inputCls} value={profileId} onChange={e => setProfileId(e.target.value)}>
                <option value="">— none —</option>
                {profiles.map(p => (
                  <option key={p.profile_id} value={p.profile_id}>{p.label} ({p.profile_id})</option>
                ))}
              </select>
            </div>
          )}
          <div className="flex gap-3 pt-2">
            <button type="submit" disabled={saving}
              className="flex-1 bg-indigo-600 text-white rounded-md py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-50">
              {saving ? 'Creating…' : 'Create user'}
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

function ChangePasswordModal({ username, onClose }: { username: string; onClose: () => void }) {
  const [password, setPassword] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true); setErr(null)
    try {
      await api.users.changePassword(username, password)
      setDone(true)
    } catch (e) { setErr(e instanceof Error ? e.message : 'Failed') }
    finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-white rounded-xl shadow-xl w-full max-w-sm p-6 z-50">
        <h2 className="text-base font-semibold text-gray-900 mb-4">Change Password — {username}</h2>
        {err && <div className="mb-3"><Err msg={err} /></div>}
        {done ? (
          <div className="space-y-3">
            <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded p-3">Password updated.</div>
            <button onClick={onClose} className="w-full border border-gray-300 text-sm text-gray-600 rounded-md py-2 hover:bg-gray-50">Close</button>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">New password</label>
              <input type="password" className={inputCls} required minLength={8} value={password} onChange={e => setPassword(e.target.value)} />
              <p className="text-xs text-gray-400 mt-0.5">At least 8 characters</p>
            </div>
            <div className="flex gap-3">
              <button type="submit" disabled={saving}
                className="flex-1 bg-indigo-600 text-white rounded-md py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-50">
                {saving ? 'Saving…' : 'Update password'}
              </button>
              <button type="button" onClick={onClose}
                className="px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-md hover:bg-gray-50">
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Admin page shell
// ══════════════════════════════════════════════════════════════════════════════

export default function AdminPage() {
  const { user, logout } = useAuth()
  const [tab, setTab] = useState<Tab>('profiles')
  const [docs, setDocs] = useState<DocFile[]>([])
  const [profiles, setProfiles] = useState<Profile[]>([])

  useEffect(() => {
    api.docs.list().then(setDocs).catch(() => {})
    api.profiles.list().then(setProfiles).catch(() => {})
  }, [tab])

  const tabs: { id: Tab; label: string }[] = [
    { id: 'profiles', label: 'Profiles' },
    { id: 'docs', label: 'Docs' },
    { id: 'settings', label: 'Settings' },
    { id: 'users', label: 'Users' },
  ]

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top bar */}
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center gap-4">
          <div className="flex items-center gap-2">
            <img src={`${import.meta.env.BASE_URL}autospy-logo.svg`} alt="Autospy" className="w-7 h-7" />
            <span className="font-semibold text-gray-900 text-sm">Autospy</span>
            <span className="text-gray-300 text-sm">|</span>
            <span className="text-xs text-gray-500">Admin Portal</span>
          </div>
          <div className="flex-1" />
          <span className="text-sm text-gray-500">{user?.username}</span>
          <button onClick={logout} className="text-sm text-gray-500 hover:text-gray-700 border border-gray-300 rounded px-2.5 py-1 hover:bg-gray-50">
            Sign out
          </button>
        </div>

        {/* Tabs */}
        <div className="max-w-6xl mx-auto px-4 flex gap-1">
          {tabs.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                tab === t.id
                  ? 'border-indigo-600 text-indigo-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}>
              {t.label}
            </button>
          ))}
        </div>
      </header>

      {/* Content */}
      <main className="max-w-6xl mx-auto px-4 py-6">
        {tab === 'profiles' && <ProfilesTab docs={docs} />}
        {tab === 'docs'     && <DocsTab />}
        {tab === 'settings' && <SettingsTab />}
        {tab === 'users'    && <UsersTab profiles={profiles} />}
      </main>
    </div>
  )
}
