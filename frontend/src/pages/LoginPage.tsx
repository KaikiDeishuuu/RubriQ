import { useEffect, useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { checkAuthToken, getAdminToken, getAuthStatus, setAdminToken } from '../lib/api'

function safeRedirectPath(value: unknown): string {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) {
    return '/'
  }
  return value
}

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const redirectTo = safeRedirectPath((location.state as { from?: unknown } | null)?.from)
  const [token, setToken] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [authRequired, setAuthRequired] = useState<boolean | null>(null)

  useEffect(() => {
    let active = true
    void (async () => {
      try {
        const status = await getAuthStatus()
        if (!active) return
        setAuthRequired(status.auth_required)
        if (!status.auth_required) {
          navigate(redirectTo, { replace: true })
          return
        }
        const existing = getAdminToken()
        if (existing) {
          try {
            await checkAuthToken()
            navigate(redirectTo, { replace: true })
          } catch {
            setAdminToken(null)
          }
        }
      } catch (err) {
        if (!active) return
        setError(err instanceof Error ? err.message : '无法连接到后端服务')
      }
    })()
    return () => {
      active = false
    }
  }, [navigate, redirectTo])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmed = token.trim()
    if (!trimmed) {
      setError('请输入管理员令牌')
      return
    }
    setSubmitting(true)
    setError(null)
    setAdminToken(trimmed)
    try {
      await checkAuthToken()
      setToken('')
      navigate(redirectTo, { replace: true })
    } catch (err) {
      setAdminToken(null)
      setError(err instanceof Error && err.message ? err.message : '令牌无效或后端不可用')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4">
      <section className="w-full max-w-md rounded-3xl border border-ink-900/10 bg-white p-8 shadow-soft">
        <h1 className="font-display text-3xl text-ink-950">QuizOCR 管理员登录</h1>
        <p className="mt-2 text-sm text-ink-700">
          请使用部署管理员配置的 <code className="rounded bg-paper px-1 py-0.5 font-mono text-xs">ADMIN_API_TOKEN</code> 登录。
        </p>
        {authRequired === false ? (
          <p className="mt-4 rounded-2xl bg-sage-50 px-4 py-3 text-sm text-sage-600">
            后端未启用令牌校验，正在跳转……
          </p>
        ) : (
          <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
            <label className="block">
              <span className="text-sm font-semibold text-ink-700">管理员令牌</span>
              <input
                type="password"
                autoComplete="current-password"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                disabled={submitting}
                className="mt-1 w-full rounded-2xl border border-ink-900/10 bg-paper px-4 py-3 text-sm text-ink-950 outline-none transition focus:border-slateBlue-400 focus:ring-2 focus:ring-slateBlue-100"
                placeholder="粘贴 token..."
              />
            </label>
            {error ? <p className="rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p> : null}
            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-full bg-ink-950 px-4 py-3 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:opacity-50"
            >
              {submitting ? '正在校验...' : '登录'}
            </button>
          </form>
        )}
      </section>
    </div>
  )
}
