import React, { useEffect, useState, type ImgHTMLAttributes, type CSSProperties } from 'react'

import { fetchStorageBlob } from '../lib/api'

interface AuthenticatedImageProps extends Omit<ImgHTMLAttributes<HTMLImageElement>, 'src'> {
  storagePath: string
  /** Optional placeholder rendered while the blob is being fetched. */
  placeholder?: string
  /** Optional error message rendered if the fetch fails. */
  errorMessage?: string
  /** Inline styles applied to the wrapper when showing placeholder/error states. */
  wrapperStyle?: CSSProperties
}

/**
 * Renders an `<img>` whose source is fetched via the auth-aware fetch wrapper
 * and exposed as a blob: URL. Required because the browser cannot send the
 * `Authorization` header on a plain `<img src=...>`.
 */
export function AuthenticatedImage({
  storagePath,
  placeholder = '正在加载图片...',
  errorMessage = '图片加载失败',
  wrapperStyle,
  alt = '',
  className,
  ...imgProps
}: AuthenticatedImageProps) {
  const [src, setSrc] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setSrc(null)
    setError(null)
    let createdUrl: string | null = null
    void (async () => {
      try {
        const blob = await fetchStorageBlob(storagePath)
        if (!active) return
        createdUrl = URL.createObjectURL(blob)
        setSrc(createdUrl)
      } catch {
        if (active) {
          setError(errorMessage)
        }
      }
    })()
    return () => {
      active = false
      if (createdUrl) {
        URL.revokeObjectURL(createdUrl)
      }
    }
  }, [storagePath, errorMessage])

  if (error) {
    return (
      <div
        className={className}
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#9f1239', ...wrapperStyle }}
      >
        {error}
      </div>
    )
  }
  if (!src) {
    return (
      <div
        className={className}
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#6b7280', ...wrapperStyle }}
      >
        {placeholder}
      </div>
    )
  }
  return <img {...imgProps} src={src} alt={alt} className={className} />
}
