import { useRef, useState } from 'react'

import { toClassNames } from '../lib/format'

interface DropZoneProps {
  title: string
  description: string
  multiple?: boolean
  accept?: string
  onFilesSelected: (files: File[]) => void
}

export function DropZone({ title, description, multiple = false, accept = '.pdf', onFilesSelected }: DropZoneProps) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [dragActive, setDragActive] = useState(false)

  function openPicker() {
    inputRef.current?.click()
  }

  function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) {
      return
    }
    onFilesSelected(Array.from(files))
  }

  return (
    <div
      className={toClassNames(
        'group rounded-3xl border border-dashed p-5 transition-colors',
        dragActive ? 'border-slateBlue-400 bg-slateBlue-50/70' : 'border-ink-900/15 bg-white/50',
      )}
      onDragOver={(event) => {
        event.preventDefault()
        setDragActive(true)
      }}
      onDragLeave={() => setDragActive(false)}
      onDrop={(event) => {
        event.preventDefault()
        setDragActive(false)
        handleFiles(event.dataTransfer.files)
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        className="hidden"
        onChange={(event) => handleFiles(event.target.files)}
      />
      <button
        type="button"
        onClick={openPicker}
        className="flex w-full flex-col items-center justify-center rounded-2xl border border-ink-900/10 bg-white/70 px-5 py-10 text-center transition hover:-translate-y-0.5 hover:shadow-lift"
      >
        <span className="font-display text-3xl text-ink-950">{title}</span>
        <span className="mt-3 max-w-xl text-sm leading-6 text-ink-700">{description}</span>
        <span className="mt-4 rounded-full bg-ink-900 px-4 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-paper">
          选择文件
        </span>
      </button>
    </div>
  )
}
