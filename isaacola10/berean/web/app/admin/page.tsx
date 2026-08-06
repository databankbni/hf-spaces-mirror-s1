"use client";

import { useCallback, useEffect, useState } from "react";

const TOKEN_KEY = "verseo.admin";

type Tab = "analytics" | "billing" | "topics" | "flags" | "lab" | "keys" | "feedback" | "services";

interface Stats {
  total: number;
  searches: number;
  asks: number;
  topTerms: { term: string; count: number }[];
  topVerses: { ref: string; count: number }[];
  modes: Record<string, number>;
  daily: { day: string; count: number }[];
}
interface Topic {
  id: number;
  label: string;
  emoji: string;
  query: string;
  position: number;
  enabled: number;
}

export default function AdminPage() {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("analytics");

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setToken(localStorage.getItem(TOKEN_KEY));
    setReady(true);
  }, []);

  const authedFetch = useCallback(
    (url: string, init: RequestInit = {}) =>
      fetch(url, {
        ...init,
        headers: { ...(init.headers ?? {}), Authorization: `Bearer ${token ?? ""}` },
      }),
    [token],
  );

  const login = async () => {
    setLoginError(null);
    try {
      const res = await fetch("/api/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Login failed");
      localStorage.setItem(TOKEN_KEY, data.token);
      setToken(data.token);
    } catch (e) {
      setLoginError(e instanceof Error ? e.message : "Login failed");
    }
  };

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
  };

  if (!ready) return null;

  if (!token) {
    return (
      <main className="flex flex-1 items-center justify-center px-5 py-20">
        <div className="w-full max-w-sm rounded-3xl border border-white/60 bg-white/70 p-8 shadow-lg backdrop-blur-xl dark:border-white/10 dark:bg-white/5">
          <h1 className="mb-1 text-2xl font-bold">Verseo Admin</h1>
          <p className="mb-5 text-sm text-slate-500 dark:text-slate-400">Sign in to manage the app.</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void login();
            }}
            className="flex flex-col gap-3"
          >
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Admin password"
              className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-400/30 dark:border-white/10 dark:bg-black/20"
            />
            <button
              type="submit"
              className="rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-500 px-4 py-2.5 font-medium text-white hover:brightness-110"
            >
              Sign in
            </button>
            {loginError && <p className="text-sm text-rose-600">{loginError}</p>}
          </form>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-4xl flex-1 px-5 py-10">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="bg-gradient-to-r from-violet-600 to-fuchsia-500 bg-clip-text text-2xl font-bold text-transparent">
          Verseo Admin
        </h1>
        <button onClick={logout} className="text-sm text-slate-500 hover:text-slate-700">
          Log out
        </button>
      </div>

      <div className="mb-6 flex flex-wrap gap-1 rounded-full bg-slate-100 p-1 dark:bg-white/5">
        {(["analytics", "billing", "topics", "flags", "lab", "keys", "feedback", "services"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={[
              "rounded-full px-4 py-2 text-sm font-medium capitalize transition",
              tab === t
                ? "bg-gradient-to-r from-violet-600 to-fuchsia-500 text-white"
                : "text-slate-500 hover:text-slate-700 dark:text-slate-400",
            ].join(" ")}
          >
            {t === "lab" ? "Search lab" : t === "keys" ? "Test keys" : t}
          </button>
        ))}
      </div>

      {tab === "analytics" && <Analytics authedFetch={authedFetch} />}
      {tab === "billing" && <Billing authedFetch={authedFetch} />}
      {tab === "topics" && <Topics authedFetch={authedFetch} />}
      {tab === "flags" && <Flags authedFetch={authedFetch} />}
      {tab === "lab" && <SearchLab authedFetch={authedFetch} />}
      {tab === "keys" && <TestKeys authedFetch={authedFetch} />}
      {tab === "feedback" && <Feedback authedFetch={authedFetch} />}
      {tab === "services" && <Services authedFetch={authedFetch} />}
    </main>
  );
}

type Fetcher = (url: string, init?: RequestInit) => Promise<Response>;

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-white/60 bg-white/70 p-5 shadow-sm backdrop-blur-xl dark:border-white/10 dark:bg-white/5">
      {children}
    </div>
  );
}

function Bars({ items }: { items: { label: string; count: number }[] }) {
  const max = Math.max(1, ...items.map((i) => i.count));
  return (
    <ul className="space-y-1.5">
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-2 text-sm">
          <span className="w-40 shrink-0 truncate" title={i.label}>{i.label}</span>
          <div className="h-3 flex-1 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10">
            <div className="h-full rounded-full bg-gradient-to-r from-violet-500 to-fuchsia-500" style={{ width: `${(i.count / max) * 100}%` }} />
          </div>
          <span className="w-8 text-right tabular-nums text-slate-500">{i.count}</span>
        </li>
      ))}
      {items.length === 0 && <li className="text-sm text-slate-400">No data yet.</li>}
    </ul>
  );
}

function Analytics({ authedFetch }: { authedFetch: Fetcher }) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [zero, setZero] = useState<{ query: string; count: number }[]>([]);

  useEffect(() => {
    const load = async () => {
      const s = await (await authedFetch("/api/admin/stats")).json();
      setStats(s);
      const z = await (await authedFetch("/api/admin/zero-results")).json();
      setZero(z.queries ?? []);
    };
    void load();
  }, [authedFetch]);

  if (!stats) return <p className="text-slate-400">Loading…</p>;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Searches" value={stats.searches} />
        <Stat label="Questions" value={stats.asks} />
        <Stat label="Total events" value={stats.total} />
      </div>
      <Card>
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Daily volume (30d)</h3>
        <Bars items={stats.daily.map((d) => ({ label: d.day, count: d.count }))} />
      </Card>
      <div className="grid gap-5 sm:grid-cols-2">
        <Card>
          <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Top searches</h3>
          <Bars items={stats.topTerms.slice(0, 10).map((t) => ({ label: t.term, count: t.count }))} />
        </Card>
        <Card>
          <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Most-found verses</h3>
          <Bars items={stats.topVerses.slice(0, 10).map((t) => ({ label: t.ref, count: t.count }))} />
        </Card>
      </div>
      <Card>
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-amber-500">
          Zero / low-confidence queries (coverage gaps)
        </h3>
        <Bars items={zero.map((z) => ({ label: z.query, count: z.count }))} />
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <div className="text-3xl font-bold tabular-nums">{value}</div>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
    </Card>
  );
}

function Topics({ authedFetch }: { authedFetch: Fetcher }) {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [label, setLabel] = useState("");
  const [emoji, setEmoji] = useState("");
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    const d = await (await authedFetch("/api/admin/topics")).json();
    setTopics(d.topics ?? []);
  }, [authedFetch]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const add = async () => {
    if (!label.trim() || !query.trim()) return;
    await authedFetch("/api/admin/topics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label, emoji, query }),
    });
    setLabel("");
    setEmoji("");
    setQuery("");
    void load();
  };
  const toggle = async (t: Topic) => {
    await authedFetch(`/api/admin/topics/${t.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: t.enabled ? 0 : 1 }),
    });
    void load();
  };
  const remove = async (t: Topic) => {
    await authedFetch(`/api/admin/topics/${t.id}`, { method: "DELETE" });
    void load();
  };

  return (
    <div className="space-y-4">
      <Card>
        <h3 className="mb-3 text-sm font-semibold">Add a topic</h3>
        <div className="flex flex-wrap gap-2">
          <input value={emoji} onChange={(e) => setEmoji(e.target.value)} placeholder="🙏" className="w-16 rounded-lg border border-slate-200 bg-white px-3 py-2 text-center dark:border-white/10 dark:bg-black/20" />
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Label" className="w-32 rounded-lg border border-slate-200 bg-white px-3 py-2 dark:border-white/10 dark:bg-black/20" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search query for this topic" className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 dark:border-white/10 dark:bg-black/20" />
          <button onClick={add} className="rounded-lg bg-gradient-to-r from-violet-600 to-fuchsia-500 px-4 py-2 font-medium text-white hover:brightness-110">Add</button>
        </div>
      </Card>
      <ul className="space-y-2">
        {topics.map((t) => (
          <li key={t.id} className={["flex items-center gap-3 rounded-xl border p-3", t.enabled ? "border-slate-200 bg-white dark:border-white/10 dark:bg-white/5" : "border-slate-200 bg-slate-50 opacity-60 dark:border-white/10 dark:bg-white/5"].join(" ")}>
            <span className="text-lg">{t.emoji}</span>
            <span className="w-32 shrink-0 font-medium">{t.label}</span>
            <span className="flex-1 truncate text-sm text-slate-500">{t.query}</span>
            <button onClick={() => toggle(t)} className="rounded-md px-2 py-1 text-xs font-medium text-slate-500 hover:bg-slate-100 dark:hover:bg-white/10">
              {t.enabled ? "Disable" : "Enable"}
            </button>
            <button onClick={() => remove(t)} className="rounded-md px-2 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-500/10">Delete</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Flags({ authedFetch }: { authedFetch: Fetcher }) {
  const [flags, setFlags] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const load = async () => {
      const d = await (await authedFetch("/api/admin/flags")).json();
      setFlags(d.flags ?? {});
    };
    void load();
  }, [authedFetch]);

  const setFlag = async (key: string, value: string) => {
    setFlags((f) => ({ ...f, [key]: value }));
    await authedFetch("/api/admin/flags", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [key]: value }),
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 1200);
  };

  const toggles: [string, string][] = [
    ["ask_enabled", "AI Q&A (Ask mode)"],
    ["listen_enabled", "Active listening"],
    ["crossrefs_enabled", "Cross-references"],
    ["similar_enabled", "Similar verses"],
    ["maintenance", "Maintenance mode"],
    ["test_mode", "Test mode (gate app behind test keys)"],
  ];

  const killOn = flags.disabled === "1";

  return (
    <div className="space-y-4">
      {/* Kill switch — prominent */}
      <div className={["rounded-2xl border p-5", flags.disabled === "1" ? "border-rose-300 bg-rose-50 dark:border-rose-400/30 dark:bg-rose-500/10" : "border-white/60 bg-white/70 backdrop-blur-xl dark:border-white/10 dark:bg-white/5"].join(" ")}>
        <div className="flex items-center justify-between gap-4">
          <div>
            <h3 className="font-semibold text-rose-700 dark:text-rose-300">⏸️ Disable all actions (kill switch)</h3>
            <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
              Instantly pauses search, speak, listen, and Q&amp;A across the app. The
              frontend shows an &ldquo;unavailable&rdquo; state within ~15s.
            </p>
          </div>
          <button
            onClick={() => setFlag("disabled", killOn ? "0" : "1")}
            className={["relative h-6 w-11 shrink-0 rounded-full transition", killOn ? "bg-gradient-to-r from-rose-500 to-rose-600" : "bg-slate-300 dark:bg-white/15"].join(" ")}
          >
            <span className={["absolute top-0.5 h-5 w-5 rounded-full bg-white transition", killOn ? "left-[22px]" : "left-0.5"].join(" ")} />
          </button>
        </div>
      </div>

      <Card>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold">Feature flags</h3>
          {saved && <span className="text-xs text-emerald-600">Saved ✓</span>}
        </div>
        <ul className="divide-y divide-slate-100 dark:divide-white/10">
          {toggles.map(([key, label]) => (
            <li key={key} className="flex items-center justify-between py-3">
              <span className="text-sm">{label}</span>
              <button
                onClick={() => setFlag(key, flags[key] === "1" ? "0" : "1")}
                className={["relative h-6 w-11 rounded-full transition", flags[key] === "1" ? "bg-gradient-to-r from-violet-600 to-fuchsia-500" : "bg-slate-300 dark:bg-white/15"].join(" ")}
              >
                <span className={["absolute top-0.5 h-5 w-5 rounded-full bg-white transition", flags[key] === "1" ? "left-[22px]" : "left-0.5"].join(" ")} />
              </button>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-slate-400">Changes apply immediately, no redeploy.</p>
      </Card>
    </div>
  );
}

const WEIGHT_KEYS: [string, string][] = [
  ["semantic", "Semantic"],
  ["lexical", "Lexical"],
  ["ce", "Cross-encoder"],
  ["ce_semantic", "CE · semantic"],
  ["ce_lexical", "CE · lexical"],
];

function SearchLab({ authedFetch }: { authedFetch: Fetcher }) {
  const [text, setText] = useState("for god so loved the world");
  const [weights, setWeights] = useState<Record<string, number>>({
    semantic: 0.65, lexical: 0.35, ce: 0.6, ce_semantic: 0.25, ce_lexical: 0.15,
  });
  const [results, setResults] = useState<Record<string, unknown>[]>([]);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  const run = useCallback(async () => {
    const res = await (
      await authedFetch("/api/admin/search-preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, weights }),
      })
    ).json();
    setResults(res.results ?? []);
  }, [authedFetch, text, weights]);

  const saveDefault = async () => {
    await authedFetch("/api/admin/flags", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        w_semantic: weights.semantic, w_lexical: weights.lexical, w_ce: weights.ce,
        w_ce_semantic: weights.ce_semantic, w_ce_lexical: weights.ce_lexical,
      }),
    });
    setSavedMsg("Saved as live default ✓");
    setTimeout(() => setSavedMsg(null), 1500);
  };

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex gap-2">
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Test query…" className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 dark:border-white/10 dark:bg-black/20" />
          <button onClick={() => void run()} className="rounded-lg bg-gradient-to-r from-violet-600 to-fuchsia-500 px-4 py-2 font-medium text-white hover:brightness-110">Run</button>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {WEIGHT_KEYS.map(([k, label]) => (
            <label key={k} className="text-sm">
              <span className="mb-1 flex justify-between text-slate-500">
                <span>{label}</span>
                <span className="tabular-nums">{weights[k].toFixed(2)}</span>
              </span>
              <input
                type="range" min={0} max={1} step={0.05} value={weights[k]}
                onChange={(e) => setWeights((w) => ({ ...w, [k]: Number(e.target.value) }))}
                className="w-full accent-fuchsia-500"
              />
            </label>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-3">
          <button onClick={saveDefault} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium hover:bg-slate-100 dark:border-white/10 dark:hover:bg-white/10">Save as live default</button>
          {savedMsg && <span className="text-xs text-emerald-600">{savedMsg}</span>}
        </div>
      </Card>
      <ol className="space-y-2">
        {results.map((r, i) => (
          <li key={i} className="rounded-xl border border-slate-200 bg-white p-3 dark:border-white/10 dark:bg-white/5">
            <div className="flex items-center justify-between">
              <span className="font-semibold">{String(r.ref)} <span className="text-xs text-slate-400">{String(r.version)}</span></span>
              <span className="text-sm tabular-nums text-fuchsia-600">{Number(r.score).toFixed(3)}</span>
            </div>
            <p className="mt-1 line-clamp-2 text-sm text-slate-500">{String(r.text)}</p>
            <div className="mt-2 flex gap-3 text-[11px] text-slate-400">
              <span>sem {Number(r.semantic).toFixed(2)}</span>
              <span>lex {Number(r.lexical).toFixed(2)}</span>
              <span>ce {Number(r.ce).toFixed(2)}</span>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

// -- Test keys ---------------------------------------------------------------
interface TestKey {
  id: number; key: string; label: string;
  created_at: number; last_used: number | null;
  enabled: number; speak: number; type_: number; ask: number; listen: number;
}

function TestKeys({ authedFetch }: { authedFetch: Fetcher }) {
  const [keys, setKeys] = useState<TestKey[]>([]);
  const [label, setLabel] = useState("");
  const [copied, setCopied] = useState<string | null>(null);

  const load = useCallback(async () => {
    const d = await (await authedFetch("/api/admin/test-keys")).json();
    setKeys(d.keys ?? []);
  }, [authedFetch]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const add = async () => {
    await authedFetch("/api/admin/test-keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label }),
    });
    setLabel("");
    void load();
  };
  const setField = async (k: TestKey, field: string, value: number | string) => {
    await authedFetch(`/api/admin/test-keys/${k.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [field]: value }),
    });
    void load();
  };
  const remove = async (k: TestKey) => {
    if (!confirm(`Delete test key for "${k.label || k.key}"?`)) return;
    await authedFetch(`/api/admin/test-keys/${k.id}`, { method: "DELETE" });
    void load();
  };
  const copyShare = async (k: TestKey) => {
    const url = `${window.location.origin}/?testkey=${encodeURIComponent(k.key)}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(k.key);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <h3 className="mb-2 text-sm font-semibold">Generate a new test key</h3>
        <div className="flex gap-2">
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Label (e.g. 'Pastor John')" className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 dark:border-white/10 dark:bg-black/20" />
          <button onClick={add} className="rounded-lg bg-gradient-to-r from-violet-600 to-fuchsia-500 px-4 py-2 font-medium text-white hover:brightness-110">Generate</button>
        </div>
        <p className="mt-2 text-xs text-slate-400">
          When Test mode is on (Flags tab), the app requires one of these keys.
          Each key&apos;s feature toggles control what the holder can use.
        </p>
      </Card>
      <ul className="space-y-2">
        {keys.length === 0 && <li className="text-sm text-slate-400">No test keys yet.</li>}
        {keys.map((k) => (
          <li key={k.id} className={["rounded-xl border p-3", k.enabled ? "border-slate-200 bg-white dark:border-white/10 dark:bg-white/5" : "border-slate-200 bg-slate-50 opacity-60 dark:border-white/10 dark:bg-white/5"].join(" ")}>
            <div className="flex flex-wrap items-center gap-2">
              <input
                defaultValue={k.label}
                onBlur={(e) => setField(k, "label", e.target.value)}
                placeholder="(no label)"
                className="w-44 rounded-md bg-transparent px-1 py-0.5 font-medium hover:bg-slate-100 focus:bg-white focus:outline-none focus:ring-2 focus:ring-violet-400/30 dark:hover:bg-white/10 dark:focus:bg-black/20"
              />
              <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs dark:bg-white/10">{k.key}</code>
              <button onClick={() => copyShare(k)} className="rounded-md px-2 py-1 text-xs font-medium text-slate-500 hover:bg-slate-100 dark:hover:bg-white/10">
                {copied === k.key ? "Copied ✓" : "Copy share link"}
              </button>
              <button onClick={() => setField(k, "enabled", k.enabled ? 0 : 1)} className="rounded-md px-2 py-1 text-xs font-medium text-slate-500 hover:bg-slate-100 dark:hover:bg-white/10">
                {k.enabled ? "Disable" : "Enable"}
              </button>
              <button onClick={() => remove(k)} className="ml-auto rounded-md px-2 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-500/10">Delete</button>
            </div>
            <div className="mt-2 flex flex-wrap gap-3 text-xs">
              {([
                ["speak", "Speak"], ["type_", "Type"], ["ask", "Ask"], ["listen", "Listen"],
              ] as [keyof TestKey, string][]).map(([col, label]) => (
                <label key={col as string} className="inline-flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={!!k[col]}
                    onChange={(e) => setField(k, col as string, e.target.checked ? 1 : 0)}
                    className="accent-fuchsia-500"
                  />
                  {label}
                </label>
              ))}
              <span className="ml-auto text-slate-400">
                last used {k.last_used ? new Date(k.last_used * 1000).toLocaleString() : "never"}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

// -- Feedback ----------------------------------------------------------------
interface FeedbackItem {
  id: number; ts: number; key: string; label: string; rating: number | null; message: string;
}

function Feedback({ authedFetch }: { authedFetch: Fetcher }) {
  const [items, setItems] = useState<FeedbackItem[]>([]);

  const load = useCallback(async () => {
    const d = await (await authedFetch("/api/admin/feedback")).json();
    setItems(d.feedback ?? []);
  }, [authedFetch]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const remove = async (id: number) => {
    if (!confirm("Delete this feedback?")) return;
    await authedFetch(`/api/admin/feedback/${id}`, { method: "DELETE" });
    void load();
  };

  if (items.length === 0) {
    return <Card><p className="text-sm text-slate-400">No feedback yet. Share a test key to start collecting it.</p></Card>;
  }
  return (
    <ul className="space-y-3">
      {items.map((f) => (
        <li key={f.id} className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-white/5">
          <div className="mb-2 flex items-center gap-2 text-xs">
            <span className="font-semibold">{f.label || "(no label)"}</span>
            <code className="rounded bg-slate-100 px-1 dark:bg-white/10">{f.key}</code>
            {f.rating != null && (
              <span className="text-amber-500">{"★".repeat(f.rating)}<span className="text-slate-200 dark:text-white/15">{"★".repeat(5 - f.rating)}</span></span>
            )}
            <span className="ml-auto text-slate-400">{new Date(f.ts * 1000).toLocaleString()}</span>
            <button onClick={() => remove(f.id)} className="rounded-md px-1.5 py-0.5 text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-500/10">Delete</button>
          </div>
          <p className="whitespace-pre-wrap text-sm">{f.message}</p>
        </li>
      ))}
    </ul>
  );
}

// -- Billing: users + payments -------------------------------------------------
interface AdminUser {
  id: string; email: string; name: string; plan: string; status: string;
  stripe_customer_id: string | null; created_at: number | null; last_seen: number | null;
}
interface Payment {
  id: number; ts: number; user_id: string; email: string; amount: number;
  currency: string; status: string; stripe_id: string; description: string;
}

function money(cents: number, currency = "usd") {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: currency.toUpperCase() }).format((cents || 0) / 100);
}

function Billing({ authedFetch }: { authedFetch: Fetcher }) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [bstats, setBstats] = useState<{ revenue_cents: number; payments: number; users: number; plans: Record<string, number> } | null>(null);

  useEffect(() => {
    const load = async () => {
      const [u, p, s] = await Promise.all([
        authedFetch("/api/admin/users").then((r) => r.json()),
        authedFetch("/api/admin/payments").then((r) => r.json()),
        authedFetch("/api/admin/billing-stats").then((r) => r.json()),
      ]);
      setUsers(u.users ?? []);
      setPayments(p.payments ?? []);
      setBstats(s);
    };
    void load();
  }, [authedFetch]);

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-3 gap-3">
        <Card>
          <div className="text-3xl font-bold tabular-nums">{bstats ? money(bstats.revenue_cents) : "—"}</div>
          <div className="text-xs uppercase tracking-wide text-slate-400">Revenue</div>
        </Card>
        <Stat label="Payments" value={bstats?.payments ?? 0} />
        <Stat label="Accounts" value={bstats?.users ?? 0} />
      </div>

      {bstats && Object.keys(bstats.plans).length > 0 && (
        <Card>
          <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Plans</h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(bstats.plans).map(([plan, n]) => (
              <span key={plan} className="rounded-full bg-slate-100 px-3 py-1 text-sm dark:bg-white/10">
                <span className="font-semibold capitalize">{plan}</span> · {n}
              </span>
            ))}
          </div>
        </Card>
      )}

      <Card>
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">User accounts</h3>
        {users.length === 0 ? (
          <p className="text-sm text-slate-400">No accounts yet — they appear when someone signs in.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-slate-400">
                  <th className="pb-2 pr-3">Email</th>
                  <th className="pb-2 pr-3">Plan</th>
                  <th className="pb-2 pr-3">Status</th>
                  <th className="pb-2">Joined</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-white/10">
                {users.map((u) => (
                  <tr key={u.id}>
                    <td className="py-2 pr-3">{u.email || u.id}</td>
                    <td className="py-2 pr-3 capitalize">{u.plan}</td>
                    <td className="py-2 pr-3">{u.status}</td>
                    <td className="py-2 text-slate-400">{u.created_at ? new Date(u.created_at * 1000).toLocaleDateString() : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Payments</h3>
        {payments.length === 0 ? (
          <p className="text-sm text-slate-400">No payments yet.</p>
        ) : (
          <ul className="space-y-2">
            {payments.map((p) => (
              <li key={p.id} className="flex items-center gap-3 rounded-xl border border-slate-200 p-3 text-sm dark:border-white/10">
                <span className="font-semibold tabular-nums">{money(p.amount, p.currency)}</span>
                <span className="truncate text-slate-500">{p.email || p.user_id}</span>
                <span className="truncate text-xs text-slate-400">{p.description}</span>
                <span className="ml-auto shrink-0 text-xs text-slate-400">{new Date(p.ts * 1000).toLocaleString()}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

// -- Services: app-key vault -----------------------------------------------------
interface AppKey {
  name: string; label: string; set: boolean; source: string; masked: string;
  updated_at: number | null;
}

function Services({ authedFetch }: { authedFetch: Fetcher }) {
  const [keys, setKeys] = useState<AppKey[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savedName, setSavedName] = useState<string | null>(null);

  const load = useCallback(async () => {
    const d = await (await authedFetch("/api/admin/app-keys")).json();
    setKeys(d.keys ?? []);
  }, [authedFetch]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const save = async (name: string) => {
    const value = (drafts[name] ?? "").trim();
    if (!value) return;
    await authedFetch("/api/admin/app-keys", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, value }),
    });
    setDrafts((d) => ({ ...d, [name]: "" }));
    setSavedName(name);
    setTimeout(() => setSavedName(null), 1500);
    void load();
  };

  const clear = async (name: string) => {
    if (!confirm(`Remove the stored value for ${name}? (Env fallback still applies.)`)) return;
    await authedFetch(`/api/admin/app-keys/${name}`, { method: "DELETE" });
    void load();
  };

  return (
    <div className="space-y-4">
      <Card>
        <h3 className="mb-1 text-sm font-semibold">Service keys</h3>
        <p className="text-xs text-slate-400">
          Keys used by Verseo (Claude, Stripe, …). Stored in the database and applied
          instantly — no redeploy. Values are write-only: once saved, only a masked
          preview is shown. Environment variables act as fallbacks.
        </p>
      </Card>
      <ul className="space-y-2">
        {keys.map((k) => (
          <li key={k.name} className="rounded-xl border border-slate-200 bg-white p-3 dark:border-white/10 dark:bg-white/5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="w-64 truncate text-sm font-medium">{k.label}</span>
              {k.set ? (
                <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold uppercase text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
                  set · {k.source}
                </span>
              ) : (
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase text-slate-500 dark:bg-white/10 dark:text-slate-400">
                  not set
                </span>
              )}
              {k.set && <code className="text-xs text-slate-400">{k.masked}</code>}
              {savedName === k.name && <span className="text-xs text-emerald-600">Saved ✓</span>}
            </div>
            <div className="mt-2 flex gap-2">
              <input
                type="password"
                value={drafts[k.name] ?? ""}
                onChange={(e) => setDrafts((d) => ({ ...d, [k.name]: e.target.value }))}
                placeholder={k.set ? "Replace value…" : "Paste value…"}
                className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm dark:border-white/10 dark:bg-black/20"
              />
              <button onClick={() => void save(k.name)} className="rounded-lg bg-gradient-to-r from-violet-600 to-fuchsia-500 px-3 py-1.5 text-sm font-medium text-white hover:brightness-110">
                Save
              </button>
              {k.source === "db" && (
                <button onClick={() => void clear(k.name)} className="rounded-lg px-2 py-1.5 text-sm text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-500/10">
                  Clear
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
