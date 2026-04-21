interface Props { html: string }

export function EmailPreview({ html }: Props) {
  const blob = new Blob([html], { type: 'text/html' })
  const url  = URL.createObjectURL(blob)
  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <div className="bg-gray-50 px-4 py-2 border-b border-gray-200 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">Email Preview</span>
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-indigo-600 hover:underline"
        >
          Open in tab ↗
        </a>
      </div>
      <iframe
        src={url}
        title="Email preview"
        className="w-full h-[600px] border-0"
        sandbox="allow-same-origin"
      />
    </div>
  )
}
