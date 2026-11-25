const DAY = 86400000;
export const moscowDate = (now = new Date()) => new Date(now.getTime() + 3 * 3600000).toISOString().slice(0, 10);
const shift = (date, days) => new Date(Date.parse(`${date}T00:00:00Z`) + days * DAY).toISOString().slice(0, 10);
export function periodRange(kind, selected = moscowDate(), now = new Date()) {
  const today = moscowDate(now);
  let start = today, end = shift(today, 1);
  if (kind === "week" || kind === "previous" || kind === "selected") {
    const anchor = kind === "selected" ? selected || today : today;
    const weekday = new Date(`${anchor}T00:00:00Z`).getUTCDay();
    start = shift(anchor, -((weekday + 6) % 7) - (kind === "previous" ? 7 : 0));
    end = shift(start, 7);
  } else if (kind === "month") {
    start = today.slice(0, 8) + "01";
    const next = new Date(`${start}T00:00:00Z`);
    next.setUTCMonth(next.getUTCMonth() + 1);
    end = next.toISOString().slice(0, 10);
  }
  return { start, end, from: `${start}T00:00:00+03:00`, to: `${end}T00:00:00+03:00`, label: `${start.split("-").reverse().join(".")} — ${shift(end, -1).split("-").reverse().join(".")} · МСК` };
}
