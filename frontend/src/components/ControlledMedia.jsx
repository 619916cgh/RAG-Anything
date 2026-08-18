import { useEffect, useState } from 'react'
import { getToken } from '../utils/api'
import { controlledMediaUrl, publicMediaUrl } from '../utils/controlledMedia'

export function useControlledMediaSource(media) {
  return useControlledMediaState(media).source
}

export function useControlledMediaState(media) {
  const protectedUrl = controlledMediaUrl(media)
  const directUrl = publicMediaUrl(media)
  const [source, setSource] = useState(directUrl)
  const [loading, setLoading] = useState(Boolean(protectedUrl))

  useEffect(() => {
    if (!protectedUrl) {
      setSource(directUrl)
      setLoading(false)
      return undefined
    }
    const token = getToken()
    if (!token) {
      setSource('')
      setLoading(false)
      return undefined
    }

    let active = true
    let objectUrl = ''
    setSource('')
    setLoading(true)
    fetch(protectedUrl, { headers: { Authorization: `Bearer ${token}` } })
      .then(response => (response.ok ? response.blob() : null))
      .then(blob => {
        if (!active || !blob) return
        objectUrl = URL.createObjectURL(blob)
        setSource(objectUrl)
      })
      .catch(() => {
        if (active) setSource('')
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [protectedUrl, directUrl])

  return { source, loading }
}

export function ControlledMediaImage({ media, alt = '', className = '', onError, ...props }) {
  const source = useControlledMediaSource(media)
  if (!source) return null
  return (
    <img
      src={source}
      alt={alt}
      className={className}
      loading="lazy"
      onError={onError}
      {...props}
    />
  )
}
