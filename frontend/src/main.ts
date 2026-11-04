import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { i18n } from './i18n'
import { createAppRouter } from './router'
import { installApplication } from './runtime/application'
import { useUiStore } from './stores/ui'
import './style.css'
import { initializeMonitoring } from './monitoring'
import { installPwa } from './pwa/register'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
const router = createAppRouter(pinia)
const stop = installApplication(pinia, router)
const stopPwa = installPwa(pinia)
app.config.errorHandler = () =>
  useUiStore(pinia).notify(i18n.global.t('errors.UNKNOWN'), 'error')
app.use(i18n).use(router)
if (import.meta.env.VITE_SENTRY_DSN)
  void initializeMonitoring(app)
    .catch(() => false)
    .then(() => app.mount('#app'))
else app.mount('#app')
if (import.meta.hot)
  import.meta.hot.dispose(() => {
    stop()
    stopPwa()
  })
