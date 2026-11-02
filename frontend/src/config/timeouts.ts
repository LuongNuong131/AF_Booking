const configuredScale = Number(import.meta.env.VITE_TIMEOUT_SCALE ?? 1)
const scale = Number.isFinite(configuredScale) && configuredScale > 0 ? configuredScale : 1

export const timeouts = {
  api: 10_000 * scale,
  noteSave: 15_000 * scale,
  export: 60_000 * scale,
  websocketSend: 7_000 * scale,
} as const
