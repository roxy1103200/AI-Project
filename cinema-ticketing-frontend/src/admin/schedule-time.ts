export const TURNOVER_MINUTES = 20;

export function wallTime(value: string): number {
  return value ? Date.parse(`${value}+08:00`) : NaN;
}

export function wallString(time: number): string {
  return new Date(time + 8 * 3600000).toISOString().slice(0, 19);
}

export function endAfterDuration(start: string, duration: number): string {
  const time = wallTime(start);
  return Number.isFinite(time) && Number.isInteger(duration) && duration > 0
    ? wallString(time + (duration + TURNOVER_MINUTES) * 60000) : "";
}

export function dateAfter(date: string, days: number): string {
  return new Date(Date.parse(`${date}T00:00:00Z`) + days * 86400000).toISOString().slice(0, 10);
}
