const MAX_SNAPSHOT_AGE_MS = 60_000;
const MAX_FUTURE_SKEW_MS = 30_000;

/** A broker snapshot is current only when the API supplies a parseable server timestamp. */
export function isCTraderSnapshotFresh(snapshot: any, now = Date.now()): boolean {
  const raw = snapshot?.as_of;
  if (typeof raw !== "string" || !raw.trim()) return false;
  const timestamp = Date.parse(raw);
  if (!Number.isFinite(timestamp)) return false;
  const age = now - timestamp;
  return age <= MAX_SNAPSHOT_AGE_MS && age >= -MAX_FUTURE_SKEW_MS;
}
