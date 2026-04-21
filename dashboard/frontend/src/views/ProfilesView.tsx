import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Profile, DocFile } from '../api/client'
import { ProfileForm } from '../components/ProfileForm'

export function ProfilesView() {
  const [profiles, setProfiles]   = useState<Profile[]>([])
  const [docs, setDocs]           = useState<DocFile[]>([])
  const [editing, setEditing]     = useState<Profile | null | undefined>(undefined) // undefined = closed
  const [deleting, setDeleting]   = useState<string | null>(null)
  const [error, setError]         = useState<string | null>(null)

  const load = () => {
    api.profiles.list().then(setProfiles).catch(console.error)
    api.docs.list().then(setDocs).catch(console.error)
  }
  useEffect(load, [])

  const handleSave = async (p: Profile) => {
    if (editing === null) {
      await api.profiles.create(p)
    } else if (editing) {
      await api.profiles.update(editing.profile_id, p)
    }
    setEditing(undefined)
    load()
  }

  const confirmDelete = async () => {
    if (!deleting) return
    try {
      await api.profiles.delete(deleting)
      setDeleting(null)
      load()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Delete failed')
      setDeleting(null)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">Profiles</h1>
        <button
          onClick={() => setEditing(null)}
          className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700"
        >
          + New profile
        </button>
      </div>

      {error && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-3 flex justify-between">
          {error}
          <button onClick={() => setError(null)} className="ml-2 font-bold">×</button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {profiles.map(p => (
          <div key={p.profile_id} className="bg-white border border-gray-200 rounded-lg p-4 hover:border-gray-300 transition-colors">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="font-semibold text-gray-900">{p.label}</h3>
                <code className="text-xs text-gray-400">{p.profile_id}</code>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setEditing(p)}
                  className="text-xs px-2.5 py-1 border border-gray-200 rounded hover:bg-gray-50 text-gray-600"
                >
                  Edit
                </button>
                <button
                  onClick={() => setDeleting(p.profile_id)}
                  className="text-xs px-2.5 py-1 border border-red-200 rounded hover:bg-red-50 text-red-600"
                >
                  Delete
                </button>
              </div>
            </div>

            <div className="mt-3 space-y-1.5 text-sm text-gray-600">
              <div>
                <span className="font-medium">Vehicles: </span>
                {p.vehicles.map(v => v.join(' ')).join(', ')}
              </div>
              <div className="flex gap-4">
                <span><span className="font-medium">Max price: </span>{p.max_price ? `$${p.max_price.toLocaleString()}` : 'No limit'}</span>
                <span><span className="font-medium">Max miles: </span>{p.max_mileage.toLocaleString()}</span>
              </div>
              <div>
                <span className="font-medium">Years: </span>{p.min_year}–{p.max_year}
                {p.excluded_years.length > 0 && ` (excl. ${p.excluded_years.join(', ')})`}
              </div>
              <div>
                <span className="font-medium">Fuel: </span>
                {p.fuel_type_filters.map(f => f ?? 'All').join(', ')}
              </div>
              <div>
                <span className="font-medium">Recipients: </span>
                {p.email_to.join(', ')}
              </div>
            </div>
          </div>
        ))}

        {profiles.length === 0 && (
          <div className="col-span-2 text-center py-16 text-gray-400 border-2 border-dashed border-gray-200 rounded-lg">
            No profiles yet — click "New profile" to create one.
          </div>
        )}
      </div>

      {/* Edit / create slide-over */}
      {editing !== undefined && (
        <ProfileForm
          initial={editing}
          docs={docs}
          onSave={handleSave}
          onClose={() => setEditing(undefined)}
        />
      )}

      {/* Delete confirmation dialog */}
      {deleting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-sm w-full mx-4">
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Delete profile?</h3>
            <p className="text-sm text-gray-600 mb-4">
              This removes <code className="text-xs bg-gray-100 px-1 rounded">{deleting}</code> from profiles.yaml. Existing run history is not affected.
            </p>
            <div className="flex gap-3">
              <button onClick={confirmDelete}
                className="flex-1 bg-red-600 text-white rounded-md py-2 text-sm font-medium hover:bg-red-700">
                Delete
              </button>
              <button onClick={() => setDeleting(null)}
                className="flex-1 border border-gray-300 rounded-md py-2 text-sm text-gray-600 hover:bg-gray-50">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
