import { NavLink, Outlet } from 'react-router-dom'

import { toClassNames } from '../lib/format'

const navItems = [
  { to: '/exams', label: '考试列表' },
  { to: '/exams/new', label: '新建考试' },
]

export function AppShell() {
  return (
    <div className="min-h-screen text-ink-950" style={{ backgroundImage: 'var(--page-texture)' }}>
      <div className="mx-auto flex min-h-screen max-w-[1600px] flex-col lg:flex-row">
        <aside className="border-b border-ink-900/10 bg-ink-950 px-6 py-6 text-paper lg:w-80 lg:border-b-0 lg:border-r">
          <div className="flex h-full flex-col justify-between gap-8">
            <div>
              <div className="inline-flex items-center rounded-full border border-gold-200/30 bg-white/5 px-3 py-1 text-[11px] uppercase tracking-[0.28em] text-gold-100">
                智能阅卷工作台
              </div>
              <h1 className="mt-4 font-display text-4xl leading-none text-white">QuizOCR</h1>
              <p className="mt-4 max-w-sm text-sm leading-6 text-slate-300">
                面向手写和中英混合试卷的 AI 预评分系统，评分依据可追溯到每条评分标准和证据。
              </p>
            </div>
            <nav className="space-y-2">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    toClassNames(
                      'block rounded-2xl px-4 py-3 text-sm font-semibold transition',
                      isActive
                        ? 'bg-gold-100 text-ink-950 shadow-soft'
                        : 'bg-white/5 text-slate-200 hover:bg-white/10 hover:text-white',
                    )
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm leading-6 text-slate-300">
              <p className="font-semibold text-white">人工复核优先</p>
              <p className="mt-2">
                每个分数都保留评分标准、证据片段和人工改分记录，方便老师复查。
              </p>
            </div>
          </div>
        </aside>
        <main className="flex-1 px-4 py-4 sm:px-6 lg:px-8 lg:py-8">
          <div className="rounded-[2rem] border border-ink-900/10 bg-white/70 p-4 shadow-soft backdrop-blur sm:p-6 lg:p-8">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
