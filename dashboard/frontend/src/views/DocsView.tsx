import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DocFile } from '../api/client'

export function DocsView() {
  const [docs, setDocs]           = useState<DocFile[]>([])
  const [selected, setSelected]   = useState<string | null>(null)
  const [content, setContent]     = useState('')
  const [draft, setDraft]         = useState('')
  const [newName, setNewName]     = useState('')
  const [creating, setCreating]   = useState(false)
  const [saving, setSaving]       = useState(false)
  const [deleting, setDeleting]   = useState<string | null>(null)
  const [error, setError]         = useState<string | null>(null)
  const [saved, setSaved]         = useState(false)

  const load = () => { api.docs.list().then(setDocs).catch(console.error) }
  useEffect(load, [])

  const openDoc = async (filename: string) => {
    setError(null)
    setSaved(false)
    try {
      const { content: c } = await api.docs.get(filename)
      setSelected(filename)
      setContent(c)
      setDraft(c)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load doc')
    }
  }

  const saveDoc = async () => {
    const filename = creating ? newName : selected
    if (!filename) return
    setSaving(true)
    setError(null)
    try {
      await api.docs.put(filename, draft)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
      if (creating) {
        setCreating(false)
        setNewName('')
        setSelected(filename)
        setContent(draft)
      } else {
        setContent(draft)
      }
      load()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const confirmDelete = async () => {
    if (!deleting) return
    try {
      await api.docs.delete(deleting)
      if (selected === deleting) { setSelected(null); setContent(''); setDraft('') }
      setDeleting(null)
      load()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Delete failed')
      setDeleting(null)
    }
  }

  const startNew = () => {
    setCreating(true)
    setSelected(null)
    setNewName('')
    setDraft('')
    setContent('')
  }

  const isDirty = draft !== content

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Reference Docs</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            Name files <code className="bg-gray-100 px-1 rounded">make_model.md</code> for auto-discovery, e.g. <code className="bg-gray-100 px-1 rounded">honda_crv.md</code>
          </p>
        </div>
        <button onClick={startNew}
          className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700">
          + New doc
        </button>
      </div>

      {error && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-3 flex justify-between">
          {error} <button onClick={() => setError(null)} className="font-bold ml-2">×</button>
        </div>
      )}

      <div className="flex gap-4 h-[calc(100vh-220px)]">
        {/* File list */}
        <div className="w-64 flex-shrink-0 bg-white border border-gray-200 rounded-lg overflow-y-auto">
          {docs.map(d => (
            <div key={d.filename}
              className={`flex items-start justify-between px-3 py-2.5 cursor-pointer border-b border-gray-100 hover:bg-gray-50 ${selected === d.filename ? 'bg-indigo-50' : ''}`}
              onClick={() => openDoc(d.filename)}
            >
              <div className="min-w-0">
                <div className="text-sm font-medium text-gray-800 truncate">{d.filename}</div>
                <div className="text-xs text-gray-400">{(d.size_bytes / 1024).toFixed(1)} KB</div>
                <div className="flex flex-wrap gap-1 mt-1">
                  {d.matched_profiles.map(p => (
                    <span key={p} className="text-xs bg-indigo-100 text-indigo-700 rounded px-1.5">{p}</span>
                  ))}
                </div>
              </div>
              <button onClick={e => { e.stopPropagation(); setDeleting(d.filename) }}
                className="text-gray-300 hover:text-red-500 ml-2 mt-0.5 text-sm flex-shrink-0">✕</button>
            </div>
          ))}
          {docs.length === 0 && (
            <div className="text-center py-8 text-sm text-gray-400">No docs yet</div>
          )}
        </div>

        {/* Editor */}
        <div className="flex-1 flex flex-col bg-white border border-gray-200 rounded-lg overflow-hidden">
          {(selected || creating) ? (
            <>
              <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-200 bg-gray-50">
                {creating ? (
                  <input
                    className="text-sm border border-gray-300 rounded px-2 py-1 w-48 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    placeholder="filename.md"
                    value={newName}
                    onChange={e => setNewName(e.target.value)}
                    autoFocus
                  />
                ) : (
                  <span className="text-sm font-medium text-gray-700">{selected}</span>
                )}
                <div className="flex items-center gap-2">
                  {saved && <span className="text-xs text-emerald-600">✓ Saved</span>}
                  {isDirty && !saved && <span className="text-xs text-amber-500">Unsaved changes</span>}
                  <button onClick={saveDoc} disabled={saving || (!creating && !isDirty) || (creating && !newName)}
                    className="px-3 py-1 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 disabled:opacity-40">
                    {saving ? 'Saving…' : 'Save'}
                  </button>
                </div>
              </div>
              <textarea
                className="flex-1 p-4 font-mono text-sm resize-none focus:outline-none"
                value={draft}
                onChange={e => setDraft(e.target.value)}
                placeholder="# Vehicle reference content…"
                spellCheck={false}
              />
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-gray-400">
              Select a doc to edit, or create a new one
            </div>
          )}
        </div>
      </div>

      {deleting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-sm w-full mx-4">
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Delete doc?</h3>
            <p className="text-sm text-gray-600 mb-4">
              Delete <code className="text-xs bg-gray-100 px-1 rounded">{deleting}</code>? Profiles that reference it directly will need to be updated.
            </p>
            <div className="flex gap-3">
              <button onClick={confirmDelete}
                className="flex-1 bg-red-600 text-white rounded-md py-2 text-sm font-medium hover:bg-red-700">Delete</button>
              <button onClick={() => setDeleting(null)}
                className="flex-1 border border-gray-300 rounded-md py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
