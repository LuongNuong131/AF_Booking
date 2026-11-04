// Bundled as an external script so the first theme render obeys script-src self.
try {
  const preference = localStorage.getItem('booking.theme')
  const dark =
    preference === 'dark' ||
    (preference !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
  document.documentElement.classList.toggle('dark', dark)
} catch {
  /* Storage can be unavailable in private browsing. */
}
export {}
