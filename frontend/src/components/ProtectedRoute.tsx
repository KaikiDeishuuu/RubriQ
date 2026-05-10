import { useEffect, useState, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { checkAuthToken, getAdminToken, getAuthStatus, setAdminToken, setAuthExpiredHandler } from '../lib/api'

interface ProtectedRouteProps {
  children: ReactNode
}

type AuthState = 'checking' | 'ok' | 'login_required'

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const location = useLocation()
  const [state, setState] = useState<AuthState>('checking')

  useEffect(() => {
    let active = true
    void (async () => {
      try {
        const status = await getAuthStatus()
        if (!active) return
        if (!status.auth_required) {
          setState('ok')
          return
        }
        const token = getAdminToken()
        if (!token) {
          setState('login_required')
          return
        }
        try {
          await checkAuthToken()
          if (active) setState('ok')
        } catch {
          if (active) {
            setAdminToken(null)
            setState('login_required')
          }
        }
      } catch {
        // Backend unreachable — let the user retry; show login screen so they can re-enter credentials.
        if (active) setState('login_required')
      }
    })()
    return () => {
      active = false
    }
  }, [location.pathname])

  useEffect(() => {
    setAuthExpiredHandler(() => {
      setAdminToken(null)
      setState('login_required')
    })
    return () => setAuthExpiredHandler(null)
  }, [])

  if (state === 'checking') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper text-sm text-ink-700">
        正在验证登录状态……
      </div>
    )
  }
  if (state === 'login_required') {
    return <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />
  }
  return <>{children}</>
}
