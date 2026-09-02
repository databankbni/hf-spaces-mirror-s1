// Browser transport for v10 multi-shot measurement sessions.
//
// Python owns all measurement aggregation and ring-size decisions. This
// helper only keeps the last server-returned state in sessionStorage and sends
// it back with the next photo. State is per-tab, survives a refresh, and is
// rotated when the measurement context changes or sits idle for 30 minutes.

(function attachMeasurementSession(global) {
  "use strict";

  const STORAGE_KEY = "ring-sizer-measurement-session-v1";
  const IDLE_TIMEOUT_MS = 30 * 60 * 1000;
  let memoryRecord = null;

  function newId() {
    if (global.crypto && typeof global.crypto.randomUUID === "function") {
      return global.crypto.randomUUID();
    }
    // RFC 4122 v4 fallback for older embedded browsers.
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = Math.floor(Math.random() * 16);
      const v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  function contextKey(context) {
    const normalized = {
      kol_email: String(context && context.kol_email || "").trim().toLowerCase(),
      ring_model: String(context && context.ring_model || "gen"),
      mode: String(context && context.mode || "multi"),
      finger_index: String(context && context.finger_index || "index"),
      source: String(context && context.source || "photo"),
    };
    return JSON.stringify(normalized);
  }

  function load() {
    try {
      const raw = global.sessionStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_err) {
      return memoryRecord;
    }
  }

  function save(record) {
    memoryRecord = record;
    try {
      global.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(record));
    } catch (_err) {
      // Private browsing / embedded webviews may reject storage. The in-memory
      // record still preserves the session for this page lifetime.
    }
  }

  function prepare(context) {
    const key = contextKey(context);
    const now = Date.now();
    let record = load();
    const expired = !record || !Number.isFinite(record.updated_at)
      || now - record.updated_at > IDLE_TIMEOUT_MS;
    if (expired || record.context_key !== key || !record.session_id) {
      record = {
        context_key: key,
        session_id: newId(),
        session_state: null,
        updated_at: now,
      };
      save(record);
    }
    return {
      session_id: record.session_id,
      session_state: record.session_state,
    };
  }

  function accept(context, response) {
    const prepared = prepare(context);
    const returnedState = response && response.session_state;
    if (!returnedState || returnedState.session_id !== prepared.session_id) {
      return;
    }
    save({
      context_key: contextKey(context),
      session_id: prepared.session_id,
      session_state: returnedState,
      updated_at: Date.now(),
    });
  }

  global.MeasurementSession = { prepare, accept };
})(window);

