import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { i18n } from './i18n'
import { createAppRouter } from './router'
import { installApplication } from './runtime/application'
import { useUiStore } from './stores/ui'
import './style.css'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
const router = createAppRouter(pinia)
const stop = installApplication(pinia, router)
app.config.errorHandler = () => useUiStore(pinia).notify(i18n.global.t('errors.UNKNOWN'), 'error')
app.use(i18n).use(router).mount('#app')
if (import.meta.hot) import.meta.hot.dispose(stop)
