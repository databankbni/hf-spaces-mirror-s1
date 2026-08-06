"use client";

import { useCallback, useEffect, useState } from "react";
import type { FavoriteItem, HistoryItem } from "../types";

const HISTORY_KEY = "vf.history";
const FAV_KEY = "vf.favorites";
const THEME_KEY = "vf.theme";
const TEST_KEY_KEY = "verseo.testkey";
const MAX_HISTORY = 25;

export const testKeyStore = {
  get(): string {
    if (typeof window === "undefined") return "";
    try {
      return window.localStorage.getItem(TEST_KEY_KEY) ?? "";
    } catch {
      return "";
    }
  },
  set(key: string) {
    try {
      window.localStorage.setItem(TEST_KEY_KEY, key);
    } catch {
      /* ignore */
    }
  },
  clear() {
    try {
      window.localStorage.removeItem(TEST_KEY_KEY);
    } catch {
      /* ignore */
    }
  },
};

function read<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write<T>(key: string, value: T) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* ignore quota / private-mode errors */
  }
}

export function useHistory() {
  const [history, setHistory] = useState<HistoryItem[]>([]);
  // Load persisted history once on mount (client-only store).
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setHistory(read<HistoryItem[]>(HISTORY_KEY, [])), []);

  const add = useCallback((item: Omit<HistoryItem, "at">) => {
    setHistory((prev) => {
      const next = [
        { ...item, at: Date.now() },
        // drop any prior identical query+mode so the list stays useful
        ...prev.filter((p) => !(p.query === item.query && p.mode === item.mode)),
      ].slice(0, MAX_HISTORY);
      write(HISTORY_KEY, next);
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    setHistory([]);
    write(HISTORY_KEY, []);
  }, []);

  return { history, add, clear };
}

export function useFavorites() {
  const [favorites, setFavorites] = useState<FavoriteItem[]>([]);
  // Load persisted favorites once on mount (client-only store).
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setFavorites(read<FavoriteItem[]>(FAV_KEY, [])), []);

  const isFavorite = useCallback(
    (ref: string, version: string) =>
      favorites.some((f) => f.ref === ref && f.version === version),
    [favorites],
  );

  const toggle = useCallback((item: Omit<FavoriteItem, "at">) => {
    setFavorites((prev) => {
      const exists = prev.some(
        (f) => f.ref === item.ref && f.version === item.version,
      );
      const next = exists
        ? prev.filter((f) => !(f.ref === item.ref && f.version === item.version))
        : [{ ...item, at: Date.now() }, ...prev];
      write(FAV_KEY, next);
      return next;
    });
  }, []);

  return { favorites, isFavorite, toggle };
}

export type Theme = "light" | "dark";

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>("dark");

  useEffect(() => {
    const saved = read<Theme | null>(THEME_KEY, null);
    const initial: Theme =
      saved ??
      (window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light");
    // Sync React state with the theme already applied by the no-flash script.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTheme(initial);
    applyTheme(initial);
  }, []);

  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === "dark" ? "light" : "dark";
      applyTheme(next);
      write(THEME_KEY, next);
      return next;
    });
  }, []);

  return { theme, toggle };
}
