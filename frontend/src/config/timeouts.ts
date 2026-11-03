const configuredScale = Number(import.meta.env.VITE_TIMEOUT_SCALE ?? 1)
export const timeoutScale =
  Number.isFinite(configuredScale) && configuredScale > 0 ? configuredScale : 1
const scaled = (milliseconds: number): number =>
  Math.max(1, Math.min(2_147_483_647, Math.round(milliseconds * timeoutScale)))

// Request deadlines/slow thresholds are declared only here. Transport/lease timing
// follows the server protocol and stays independent of request timeout scaling.
export const timeouts = {
  lookup: scaled(8_000),
  search: scaled(8_000),
  list: scaled(10_000),
  api: scaled(10_000), // Compatibility for the existing readiness client.
  noteSave: scaled(15_000),
  task: scaled(10_000),
  profile: scaled(10_000),
  export: scaled(60_000),
  warmup: scaled(45_000),
  slow: scaled(3_000),
  websocketConnect: scaled(8_000),
  routeWatchdog: 20_000,
  visibilityRefresh: 60_000,
  retryJitter: 300,
  retryJitterRange: 200,
  realtimeBackoff: [1_000, 2_000, 5_000, 15_000] as readonly number[],
  lockHeartbeat: 30_000,
  notificationDebounce: 200,
  notice: 7_000,
} as const
