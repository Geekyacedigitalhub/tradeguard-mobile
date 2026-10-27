// On-device crash journal — the app's black box.
//
// Every startup event, stage marker, error and heartbeat is appended SYNCHRONOUSLY
// to a local file (no network involved). If the app dies mid-session, the NEXT
// launch reads the journal and shows the full trace on a crash-report screen,
// which the user can screenshot and send back.
//
// Guarantees:
// - never throws, never blocks meaningfully (file is capped at ~24 KB)
// - sync writes via expo-file-system so the line is on disk before the next line of JS runs
// - keeps the last 2 sessions; older ones are dropped
import { File, Paths } from "expo-file-system";

const FILE_NAME = "tradeguard-crash-journal.txt";
const MAX_FILE_CHARS = 24000;
const SESSION_HEADER = "=== SESSION ";

let file: InstanceType<typeof File> | null | undefined;
let ready = false;
let inited = false;
let buffer = "";

function journalFile() {
  if (file !== undefined) return file;
  try {
    file = new File(Paths.document, FILE_NAME);
  } catch {
    file = null;
  }
  return file;
}

function trimSessions(content: string, keep: number): string {
  try {
    // Sessions start with "=== SESSION ..." on their own line.
    const idx: number[] = [];
    let pos = 0;
    while (true) {
      const i = content.indexOf(SESSION_HEADER, pos);
      if (i === -1) break;
      idx.push(i);
      pos = i + SESSION_HEADER.length;
    }
    if (idx.length <= keep) return content;
    return content.slice(idx[idx.length - keep]);
  } catch {
    return content;
  }
}

// Initialize a new session. Call once, as early as possible (bootstrap.ts).
export function initJournal(meta: Record<string, unknown> = {}) {
  if (inited) return;
  inited = true;
  try {
    const f = journalFile();
    if (!f) return;
    let old = "";
    try {
      old = f.exists ? f.textSync() : "";
    } catch {
      old = "";
    }
    old = trimSessions(old, 1); // keep the previous session only
    const header =
      `${SESSION_HEADER}${new Date().toISOString()} ` +
      JSON.stringify(meta) + "\n";
    buffer = old + header;
    persist();
    ready = true;
  } catch {
    ready = false;
  }
}

function persist() {
  try {
    const f = journalFile();
    if (!f) return;
    let content = buffer;
    if (content.length > MAX_FILE_CHARS) content = content.slice(-MAX_FILE_CHARS);
    f.write(content);
  } catch {
    // ignore — the journal must never crash the app
  }
}

// Append a stage/event line. Safe to call from anywhere, even before init.
export function jstage(name: string, payload: Record<string, unknown> = {}) {
  if (!ready) return;
  try {
    const extra =
      Object.keys(payload).length > 0 ? " " + JSON.stringify(payload) : "";
    buffer += `${new Date().toISOString()} ${name}${extra}\n`;
    persist();
  } catch {
    // ignore
  }
}

// Read the previous (pre-current-session) session.
// Returns null if there is no previous session.
export function readPreviousSession(): { lines: string[]; clean: boolean } | null {
  try {
    const f = journalFile();
    if (!f) return null;
    const text = f.exists ? f.textSync() : "";
    if (!text) return null;
    const idx: number[] = [];
    let pos = 0;
    while (true) {
      const i = text.indexOf(SESSION_HEADER, pos);
      if (i === -1) break;
      idx.push(i);
      pos = i + SESSION_HEADER.length;
    }
    if (idx.length < 2) return null; // no session before the current one
    const prev = text.slice(idx[idx.length - 2], idx[idx.length - 1]);
    const lines = prev.split("\n").map((l) => l.trimEnd()).filter((l) => l !== "");
    const clean = /session_end\b/.test(prev);
    return { lines, clean };
  } catch {
    return null;
  }
}

// Full journal text (all sessions) for display on the error screen.
export function readJournalText(): string {
  try {
    const f = journalFile();
    if (!f) return "(journal unavailable)";
    return f.exists ? f.textSync() : "(journal is empty)";
  } catch {
    return "(journal unreadable)";
  }
}
