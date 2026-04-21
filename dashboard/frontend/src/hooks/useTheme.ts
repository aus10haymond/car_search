import { useEffect, useState } from 'react'

export type ThemePreference = 'light' | 'dark' | 'system'

function resolveTheme(pref: ThemePreference): 'light' | 'dark' {
  if (pref === 'system') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  return pref
}

function applyTheme(pref: ThemePreference) {
  const resolved = resolveTheme(pref)
  document.documentElement.classList.toggle('dark', resolved === 'dark')
  // Let the browser style its own UI elements (scrollbars, form controls) correctly
  document.documentElement.style.colorScheme = resolved
}

export function useTheme() {
  const [preference, setPreference] = useState<ThemePreference>(() => {
    return (localStorage.getItem('theme') as ThemePreference) ?? 'system'
  })

  useEffect(() => {
    applyTheme(preference)

    // When set to 'system', re-apply whenever the OS preference changes
    if (preference !== 'system') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => applyTheme('system')
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [preference])

  const setTheme = (pref: ThemePreference) => {
    localStorage.setItem('theme', pref)
    setPreference(pref)
  }

  return { preference, setTheme }
}
