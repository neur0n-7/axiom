import { useEffect, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { revealItemInDir } from "@tauri-apps/plugin-opener";
import "./App.css";

type SearchResult = { title: string; snippet: string; path: string };
type BackendResult = { path?: string; snippet?: string; score?: number };
type SearchMode = "hybrid" | "keyword" | "semantic";
type Screen = "onboarding" | "search" | "settings";
type Config = { root_dir: string; exclude_patterns: string[]; is_first_run?: boolean };
type Progress = { indexing: boolean; total: number; done: number };

async function pickDirectory(): Promise<string | null> {
  const selected = await open({ directory: true, multiple: false });
  return typeof selected === "string" ? selected : null;
}

function toSearchResult(item: BackendResult): SearchResult {
  const path = item.path ?? "";
  const title = path.split(/[\\/]/).pop() || path;
  const snippet = (item.snippet ?? "").replace(/\s+/g, " ").trim();
  return { title, path, snippet: snippet || "No preview available." };
}

const EXT_ICONS: Record<string, string> = {
  py: "🐍", js: "📜", ts: "📘", json: "📋", md: "📝", txt: "📄",
};
function getIcon(path: string) {
  return EXT_ICONS[path.split(".").pop()?.toLowerCase() ?? ""] ?? "📄";
}

export default function App() {
  const [screen, setScreen] = useState<Screen>("search");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<SearchMode>("semantic");

  const [config, setConfig] = useState<Config>({ root_dir: "", exclude_patterns: [] });
  const [draft, setDraft] = useState<Config>({ root_dir: "", exclude_patterns: [] });
  const [newExclude, setNewExclude] = useState("");
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const [progress, setProgress] = useState<Progress>({ indexing: false, total: 0, done: 0 });
  const [onboardPicking, setOnboardPicking] = useState(false);
  const [ready, setReady] = useState(false);

  // also decides onboarding vs search, and gates removing #splash so there's no flash
  useEffect(() => {
    fetch("http://localhost:8000/config")
      .then((r) => r.json())
      .then((d: Config) => {
        setConfig(d);
        setDraft(d);
        if (d.is_first_run) setScreen("onboarding");
      })
      .catch(() => {})
      .finally(() => {
        setReady(true);
        const splash = document.getElementById("splash");
        if (!splash) return;
        splash.style.opacity = "0";
        setTimeout(() => splash.remove(), 200);
      });
  }, []);

  useEffect(() => {
    let cancelled = false;
    const poll = () => {
      fetch("http://localhost:8000/status")
        .then((r) => r.json())
        .then((d: Progress) => { if (!cancelled) setProgress(d); })
        .catch(() => {});
    };
    poll();
    const id = setInterval(poll, 600);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  async function completeOnboarding() {
    setOnboardPicking(true);
    try {
      const dir = await pickDirectory();
      if (!dir) return;
      await fetch("http://localhost:8000/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root_dir: dir }),
      });
      const next = { ...config, root_dir: dir, is_first_run: false };
      setConfig(next);
      setDraft(next);
      setScreen("search");
    } finally {
      setOnboardPicking(false);
    }
  }

  async function browseForDirectory() {
    const dir = await pickDirectory();
    if (dir) setDraft((d) => ({ ...d, root_dir: dir }));
  }

  async function search(q: string, m: SearchMode) {
    if (!q.trim()) { setResults([]); setError(null); return; }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `http://localhost:8000/search?q=${encodeURIComponent(q)}&mode=${m}`
      );
      if (!res.ok) throw new Error();
      const data = await res.json();
      setResults((data.results ?? []).map(toSearchResult));
    } catch {
      setResults([]);
      setError("Backend unreachable - is the server running?");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const t = setTimeout(() => search(query, mode), 180);
    return () => clearTimeout(t);
  }, [query, mode]);

  async function saveConfig() {
    try {
      const res = await fetch("http://localhost:8000/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
      });
      if (!res.ok) throw new Error(`Save failed: ${res.status}`);
      setConfig(draft);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      setSaveError(true);
      setTimeout(() => setSaveError(false), 2500);
    }
  }

  function addExclude() {
    const v = newExclude.trim();
    if (!v || draft.exclude_patterns.includes(v)) return;
    setDraft((d) => ({ ...d, exclude_patterns: [...d.exclude_patterns, v] }));
    setNewExclude("");
  }

  function removeExclude(p: string) {
    setDraft((d) => ({ ...d, exclude_patterns: d.exclude_patterns.filter((x) => x !== p) }));
  }

  const onSettings = screen === "settings";

  return (
    <div className={`app ${ready ? "ready" : ""}`}>
      {/* ── ONBOARDING SCREEN ── */}
      {screen === "onboarding" && (
        <div className="screen screen-onboarding">
          <div className="onboarding-body">
            <span className="wordmark onboarding-wordmark">Axiom</span>
            <p className="onboarding-copy">
              Pick a folder for Axiom to index and search. You can change this
              later in Settings.
            </p>
            <button
              className="save-btn"
              onClick={completeOnboarding}
              disabled={onboardPicking}
            >
              {onboardPicking ? "Choosing…" : "Choose folder"}
            </button>
          </div>
        </div>
      )}

      {/* ── SEARCH SCREEN ── */}
      <div className={`screen screen-search ${onSettings ? "exit" : ""}`}>
        <div className="header">
          <div className="header-inner">
            <span className="wordmark">Axiom</span>

            <div className="mode-tabs">
              {(["hybrid", "keyword", "semantic"] as SearchMode[]).map((m) => (
                <button
                  key={m}
                  className={`mode-tab ${mode === m ? "active" : ""}`}
                  onClick={() => setMode(m)}
                >
                  {m === "semantic" && <span className="ai-dot" />}
                  {m}
                </button>
              ))}
            </div>

            <button
              className="settings-btn"
              onClick={() => setScreen("settings")}
              title="Settings"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path
                  fillRule="evenodd"
                  clipRule="evenodd"
                  d="M6.974 1a.75.75 0 0 0-.743.648l-.12.865a5.043 5.043 0 0 0-.918.534l-.831-.332a.75.75 0 0 0-.9.308L2.436 4.4a.75.75 0 0 0 .15.96l.674.573a5.07 5.07 0 0 0 0 1.134l-.674.573a.75.75 0 0 0-.15.96l1.026 1.777a.75.75 0 0 0 .9.308l.831-.332c.286.202.593.375.918.534l.12.865A.75.75 0 0 0 6.974 12h2.052a.75.75 0 0 0 .743-.648l.12-.865a5.04 5.04 0 0 0 .918-.534l.831.332a.75.75 0 0 0 .9-.308l1.026-1.777a.75.75 0 0 0-.15-.96l-.674-.573a5.1 5.1 0 0 0 0-1.134l.674-.573a.75.75 0 0 0 .15-.96L12.538 3.023a.75.75 0 0 0-.9-.308l-.831.332a5.043 5.043 0 0 0-.918-.534l-.12-.865A.75.75 0 0 0 9.026 1H6.974ZM8 9.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z"
                  fill="currentColor"
                />
              </svg>
            </button>
          </div>
        </div>

        <main className="main">
          <div className="search-box">
            <svg className="search-icon" width="16" height="16" viewBox="0 0 16 16" fill="none">
              <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.4" />
              <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={mode === "semantic" ? "Describe what you're looking for…" : "Search your files…"}
              className="search-input"
              autoFocus
              autoComplete="off"
              spellCheck={false}
            />
            {query && (
              <button className="clear-btn" onClick={() => setQuery("")}>×</button>
            )}
          </div>

          {mode !== "keyword" && (
            <div className="mode-badge">
              <span className="ai-dot" />
              {mode === "semantic" ? "Semantic search" : "Hybrid search"}
            </div>
          )}

          {progress.indexing && (
            <div className="index-progress">
              <div className="index-progress-track">
                <div
                  className="index-progress-fill"
                  style={{
                    width: `${progress.total ? Math.round((progress.done / progress.total) * 100) : 0}%`,
                  }}
                />
              </div>
              <span className="index-progress-label">
                Indexing {progress.done}/{progress.total}…
              </span>
            </div>
          )}

          <div className="results">
            {loading && (
              <div className="status-row">
                <div className="spinner" />
                <span>Searching…</span>
              </div>
            )}
            {!loading && error && <div className="status-row error">{error}</div>}
            {!loading && !error && query.trim() && results.length === 0 && (
              <div className="status-row">No results for "{query}"</div>
            )}
            {!loading && results.map((r, i) => (
              <div
                key={i}
                className="result-card"
                style={{ animationDelay: `${i * 25}ms` }}
                onClick={() => revealItemInDir(r.path).catch(() => {})}
                title="Show in file explorer"
              >
                <div className="result-header">
                  <span className="result-icon">{getIcon(r.path)}</span>
                  <span className="result-title">{r.title}</span>
                </div>
                <p className="result-snippet">{r.snippet}</p>
                <span className="result-path">{r.path}</span>
              </div>
            ))}
          </div>
        </main>
      </div>

      {/* ── SETTINGS SCREEN ── */}
      <div className={`screen screen-settings ${onSettings ? "enter" : ""}`}>
        <div className="header">
          <div className="header-inner">
            <button className="back-btn" onClick={() => setScreen("search")}>
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M9 2L4 7l5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Search
            </button>
            <span className="header-title">Settings</span>
          </div>
        </div>

        <div className="settings-body">
          <div className="settings-section">
            <span className="settings-section-label">Directory</span>

            <div className="setting-row">
              <span className="setting-label">Search directory</span>
              <span className="setting-hint">
                The folder Axiom indexes. Defaults to your Downloads folder.
                Saving rebuilds the index automatically.
              </span>
              <div className="directory-picker-row">
                <input
                  className="setting-input"
                  value={draft.root_dir}
                  readOnly
                  placeholder="No folder selected"
                />
                <button className="add-btn" onClick={browseForDirectory}>
                  Browse…
                </button>
              </div>
            </div>
          </div>

          <div className="settings-section">
            <span className="settings-section-label">Exclusions</span>

            <div className="setting-row">
              <span className="setting-label">Excluded folders</span>
              <span className="setting-hint">
                Folder names matching these patterns are skipped during indexing.
              </span>
            </div>

            <div className="exclude-list">
              {draft.exclude_patterns.map((p) => (
                <span key={p} className="exclude-chip">
                  {p}
                  <button className="chip-remove" onClick={() => removeExclude(p)}>×</button>
                </span>
              ))}
            </div>

            <div className="exclude-add-row">
              <input
                className="setting-input exclude-add-input"
                placeholder="Add a pattern…"
                value={newExclude}
                onChange={(e) => setNewExclude(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addExclude()}
              />
              <button className="add-btn" onClick={addExclude}>Add</button>
            </div>
          </div>

          <div className="settings-save-row">
            <button
              className={`save-btn ${saved ? "saved" : ""}`}
              onClick={saveConfig}
              disabled={saved}
            >
              {saved ? "Saved" : "Save changes"}
            </button>
            <span className="settings-note">
              {saveError
                ? "Couldn't save - backend unreachable. Try again."
                : "Changing the directory triggers a full reindex in the background."}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}