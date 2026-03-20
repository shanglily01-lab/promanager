export function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

export function mondayISO(d: Date = new Date()): string {
  const day = d.getUTCDay();
  const diff = (day + 6) % 7;
  const mon = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - diff));
  return mon.toISOString().slice(0, 10);
}
