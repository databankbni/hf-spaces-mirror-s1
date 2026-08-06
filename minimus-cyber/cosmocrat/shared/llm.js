// ═══════════════════════════════════════════════════════════
//  COSMOCRAT LLM — Hugging Face Inference API only
//  Design: unico provider, chiavi solo lato client, richieste dirette a HF.
//  Motivazione: sistema fisso e trasparente per competizione LLM (analogo a
//  Hexel/Weinrot su VPS James). Modelli aperti, replicabilità, no costi API.
// ═══════════════════════════════════════════════════════════

window.LLM_PROVIDERS = {
  huggingface: {
    id: 'huggingface',
    name: 'Hugging Face',
    // OpenAI-compatible chat completions endpoint
    url: 'https://router.huggingface.co/v1/chat/completions',
    keyPrefix: 'hf_',
    keyHint: 'hf_...',
    signup: 'https://huggingface.co/settings/tokens',
    notes: 'Token gratuito. Scope: "Make calls to Inference Providers" (o token Read).',
    models: [
      // Large — competizione tra modelli grandi
      { id: 'meta-llama/Llama-3.3-70B-Instruct',            label: 'Llama 3.3 70B',            tier: 'large' },
      { id: 'Qwen/Qwen2.5-72B-Instruct',                     label: 'Qwen 2.5 72B',             tier: 'large' },
      { id: 'meta-llama/Llama-3.1-70B-Instruct',             label: 'Llama 3.1 70B',            tier: 'large' },
      { id: 'mistralai/Mixtral-8x7B-Instruct-v0.1',          label: 'Mixtral 8x7B',             tier: 'large' },
      // Reasoning specialists
      { id: 'Qwen/QwQ-32B-Preview',                          label: 'QwQ 32B (reasoning)',      tier: 'reasoning' },
      { id: 'deepseek-ai/DeepSeek-R1-Distill-Llama-70B',     label: 'DeepSeek R1 Distill 70B',  tier: 'reasoning' },
      // Medium
      { id: 'mistralai/Mistral-Nemo-Instruct-2407',          label: 'Mistral Nemo 12B',         tier: 'medium' },
      { id: 'Qwen/Qwen2.5-32B-Instruct',                     label: 'Qwen 2.5 32B',             tier: 'medium' },
      { id: 'google/gemma-2-27b-it',                         label: 'Gemma 2 27B',              tier: 'medium' },
      // Fast — utili per turni timerati e differenza di velocità
      { id: 'meta-llama/Llama-3.2-3B-Instruct',              label: 'Llama 3.2 3B',             tier: 'fast' },
      { id: 'Qwen/Qwen2.5-7B-Instruct',                      label: 'Qwen 2.5 7B',              tier: 'fast' },
      { id: 'HuggingFaceH4/zephyr-7b-beta',                  label: 'Zephyr 7B',                tier: 'fast' },
    ],
  },
};

window.LLM_CATALOG = (() => {
  const out = [];
  Object.values(window.LLM_PROVIDERS).forEach(p => {
    p.models.forEach(m => {
      out.push({
        providerId: p.id,
        modelId: m.id,
        label: m.label,
        provider: p.name,
        tier: m.tier,
        fullId: `${p.id}:${m.id}`,
      });
    });
  });
  return out;
})();

window.getLLMByFullId = (fullId) => window.LLM_CATALOG.find(e => e.fullId === fullId);

window.LLM_KEYS = {
  _store: {},

  load() {
    try {
      const raw = localStorage.getItem('cosmocrat.llm.keys');
      if (raw) this._store = JSON.parse(raw);
    } catch(e) { console.warn('LLM key load failed', e); }
  },
  save() {
    try {
      localStorage.setItem('cosmocrat.llm.keys', JSON.stringify(this._store));
    } catch(e) { console.warn('LLM key save failed', e); }
  },
  set(providerId, key) {
    if (!key || !key.trim()) delete this._store[providerId];
    else this._store[providerId] = key.trim();
    this.save();
  },
  get(providerId) { return this._store[providerId] || ''; },
  has(providerId) { return !!this._store[providerId]; },
  clear() { this._store = {}; this.save(); },
};

// ═══════════════════════════════════════════════════════════
//  UNIFIED CALL — supporta AbortController per il timer
// ═══════════════════════════════════════════════════════════
window.callLLM = async function callLLM(opts) {
  const {
    provider, model,
    system = '',
    user = '',
    temperature = 0,
    maxTokens = 800,
    signal,   // AbortSignal — per timeout hardware
  } = opts;

  const P = window.LLM_PROVIDERS[provider];
  if (!P) throw new Error(`Provider sconosciuto: ${provider}`);
  const key = window.LLM_KEYS.get(provider);
  if (!key) throw new Error(`Nessuna API key per ${P.name}. Configurala nel setup.`);

  const body = {
    model,
    max_tokens: maxTokens,
    temperature,
    messages: [
      { role: 'system', content: system },
      { role: 'user',   content: user   },
    ],
  };

  const r = await fetch(P.url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${key}`,
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!r.ok) {
    const txt = await r.text();
    throw new Error(`${P.name} ${r.status}: ${txt.substring(0, 300)}`);
  }
  const d = await r.json();
  return d.choices?.[0]?.message?.content || '';
};

window.LLM_KEYS.load();
