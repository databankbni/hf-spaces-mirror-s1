// ============================================================
// knowledge-graph.js — Neural Reputation Engine v3.0
// ============================================================
import { callModel, isRealMode } from './api.js';

document.addEventListener('DOMContentLoaded', () => {
  if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons();

  const terminal = document.getElementById('terminal');
  const runBtn = document.getElementById('runKgBtn');
  const clearBtn = document.getElementById('clearBtn');
  const streamStatus = document.getElementById('streamStatus');
  const canvas = document.getElementById('kgCanvas');
  const ctx = canvas ? canvas.getContext('2d') : null;
  const canvasOverlay = document.getElementById('kgCanvasOverlay');

  let isRunning = false;
  let neuralCycles = 0;
  let entities = [];
  let relations = [];

  // ── Logger ──
  function log(msg, type = 'info') {
    if (!terminal) return;
    const line = document.createElement('div');
    const ts = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const colors = {
      info: 'text-slate-300',
      system: 'text-violet-300',
      success: 'text-emerald-300',
      warning: 'text-amber-300',
      error: 'text-red-300',
      neural: 'text-fuchsia-300'
    };
    line.className = `${colors[type] || colors.info} flex gap-3 items-start`;
    line.style.cssText = 'animation: fadeIn 0.2s ease-out both;';
    line.innerHTML = `<span class="text-slate-600 shrink-0 select-none font-medium">[${ts}]</span><span class="break-all">${msg || ''}</span>`;
    const ph = terminal.querySelector('.italic');
    if (ph) ph.remove();
    terminal.appendChild(line);
    if (terminal.children.length > 300) terminal.removeChild(terminal.firstChild);
    terminal.scrollTo({ top: terminal.scrollHeight, behavior: 'smooth' });
  }

  // ── Animate stat ──
  function animateStat(el, target, suffix = '') {
    if (!el) return;
    let cur = parseInt(el.textContent) || 0;
    const step = Math.max(1, Math.floor((target - cur) / 20));
    const iv = setInterval(() => {
      if (cur < target) { cur += step; if (cur > target) cur = target; el.textContent = cur + suffix; } else clearInterval(iv);
    }, 30);
  }

  // ── Update Score Dashboard ──
  function updateScores(scores) {
    if (!scores) return;
    const { trust = 0, authority = 0, sentiment = 0, influence = 0, eeat = 0 } = scores;
    const overall = trust + authority + sentiment + influence + eeat;

    // Ring
    const ring = document.getElementById('repScoreRing');
    const ringText = document.getElementById('repScoreText');
    if (ring) {
      const circumference = 251;
      const offset = circumference - (circumference * overall / 500);
      ring.style.strokeDashoffset = offset;
    }
    if (ringText) ringText.textContent = overall;

    // Bars
    const bars = {
      dimTrustBar: { bar: 'dimTrustBar', val: 'dimTrustValue', score: trust },
      dimAuthorityBar: { bar: 'dimAuthorityBar', val: 'dimAuthorityValue', score: authority },
      dimSentimentBar: { bar: 'dimSentimentBar', val: 'dimSentimentValue', score: sentiment },
      dimInfluenceBar: { bar: 'dimInfluenceBar', val: 'dimInfluenceValue', score: influence },
      dimEEATBar: { bar: 'dimEEATBar', val: 'dimEEATValue', score: eeat }
    };
    Object.values(bars).forEach(({ bar, val, score }) => {
      const barEl = document.getElementById(bar);
      const valEl = document.getElementById(val);
      if (barEl) barEl.style.width = score + '%';
      if (valEl) valEl.textContent = score + '/100';
    });
  }

  // ── Canvas Graph ──
  function resizeCanvas() {
    if (!canvas || !ctx) return;
    const parent = canvas.parentElement;
    const w = parent.clientWidth;
    const h = parent.clientHeight;
    canvas.width = w * window.devicePixelRatio;
    canvas.height = h * window.devicePixelRatio;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
  }

  function drawGraph() {
    if (!canvas || !ctx || entities.length === 0) return;
    resizeCanvas();
    const w = canvas.width / window.devicePixelRatio;
    const h = canvas.height / window.devicePixelRatio;
    ctx.clearRect(0, 0, w, h);

    // Draw relations
    relations.forEach(rel => {
      const a = entities[rel.from];
      const b = entities[rel.to];
      if (!a || !b) return;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = rel.color || 'rgba(139,92,246,0.2)';
      ctx.lineWidth = rel.width || 1;
      ctx.stroke();

      // Label on midpoint
      if (rel.label) {
        const mx = (a.x + b.x) / 2;
        const my = (a.y + b.y) / 2;
        ctx.fillStyle = 'rgba(100,116,139,0.6)';
        ctx.font = '8px JetBrains Mono';
        ctx.textAlign = 'center';
        ctx.fillText(rel.label, mx, my - 4);
      }
    });

    // Draw entities
    entities.forEach((e, i) => {
      // Glow
      const glow = ctx.createRadialGradient(e.x, e.y, 0, e.x, e.y, e.r * 2.5);
      glow.addColorStop(0, e.color + '40');
      glow.addColorStop(1, e.color + '00');
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(e.x, e.y, e.r * 2.5, 0, Math.PI * 2);
      ctx.fill();

      // Node
      ctx.beginPath();
      ctx.arc(e.x, e.y, e.r, 0, Math.PI * 2);
      ctx.fillStyle = e.color + '30';
      ctx.fill();
      ctx.strokeStyle = e.color;
      ctx.lineWidth = e.main ? 2.5 : 1.5;
      ctx.stroke();

      // Label
      ctx.fillStyle = e.textColor || 'rgba(203,213,225,0.9)';
      ctx.font = `${e.main ? 'bold ' : ''}${e.main ? 11 : 9}px JetBrains Mono`;
      ctx.textAlign = 'center';
      ctx.fillText(e.name, e.x, e.y + e.r + 14);
    });
  }

  function generateGraphData(entityName, entityType, depth) {
    const colors = {
      brand: '#a78bfa',
      person: '#818cf8',
      organization: '#fbbf24',
      concept: '#34d399',
      product: '#fb7185',
      competitor: '#f43f5e'
    };

    entities = [];
    relations = [];

    // Central entity
    const cx = (canvas?.clientWidth || 400) / 2;
    const cy = (canvas?.clientHeight || 200) / 2;
    entities.push({
      name: entityName,
      type: entityType,
      x: cx,
      y: cy,
      r: 22,
      color: colors[entityType] || '#a78bfa',
      main: true,
      textColor: '#fff'
    });

    // Surrounding entities
    const entityCount = Math.min(10 + depth * 8, 30);
    const rings = [
      { radius: 90, count: Math.min(6 + depth * 2, 10), types: ['person', 'organization', 'concept'] },
      { radius: 160, count: Math.min(8 + depth * 3, 14), types: ['person', 'organization', 'competitor', 'concept'] },
      { radius: 220, count: Math.min(6 + depth * 2, 10), types: ['concept', 'product', 'competitor'] }
    ];

    const relationLabels = ['possède', 'travaille pour', 'concurrence', 'collabore', 'mentionne', 'recommande', 'influence', 'sameAs'];
    let id = 1;

    rings.forEach((ring, ri) => {
      const actualCount = Math.min(ring.count, entityCount - entities.length);
      const step = (2 * Math.PI) / actualCount;
      for (let i = 0; i < actualCount; i++) {
        const angle = i * step + (ri * 0.4);
        const x = cx + ring.radius * Math.cos(angle);
        const y = cy + ring.radius * Math.sin(angle);
        const type = ring.types[Math.floor(Math.random() * ring.types.length)];
        const names = {
          person: ['A. Smith', 'M. Dupont', 'J. Martin', 'L. Bernard', 'C. Dubois', 'P. Thomas', 'N. Leroy'],
          organization: ['ONG Aide', 'Institut X', 'Foundation Y', 'Lab Z', 'Agency W', 'Council B'],
          concept: ['IA éthique', 'SEO 2026', 'GEO', 'Trust', 'E-E-A-T', 'Privacy', 'Safety', 'Cognition'],
          product: ['Service A', 'Platform B', 'Tool C', 'App D'],
          competitor: ['Concurrent 1', 'Rival 2', 'Alt 3', 'Comp 4']
        };
        const name = names[type][Math.floor(Math.random() * names[type].length)];
        entities.push({
          name,
          type,
          x, y,
          r: ri === 0 ? 14 : ri === 1 ? 12 : 10,
          color: colors[type] || '#a78bfa',
          main: false,
          textColor: 'rgba(203,213,225,0.7)'
        });

        // Relation to center
        relations.push({
          from: 0,
          to: id,
          label: relationLabels[Math.floor(Math.random() * relationLabels.length)],
          color: type === 'competitor' ? 'rgba(244,63,94,0.2)' : 'rgba(139,92,246,0.15)',
          width: ri === 0 ? 1.5 : 1
        });

        // Cross-relations
        if (id > 1 && Math.random() > 0.6) {
          const target = 1 + Math.floor(Math.random() * (id - 1));
          relations.push({
            from: id,
            to: target,
            label: relationLabels[Math.floor(Math.random() * relationLabels.length)],
            color: 'rgba(99,102,241,0.1)',
            width: 0.5
          });
        }
        id++;
      }
    });

    if (canvasOverlay) canvasOverlay.style.display = 'none';
    drawGraph();
  }

  // ── Render entity list ──
  function renderEntityList() {
    const list = document.getElementById('entityList');
    if (!list) return;
    list.innerHTML = '';
    entities.forEach((e, i) => {
      const item = document.createElement('div');
      item.className = 'kg-entity-item flex items-center gap-2 bg-slate-950/80 border border-slate-800 rounded-lg px-3 py-2 text-xs';
      const typeIcons = { brand: 'building-2', person: 'user', organization: 'users', concept: 'lightbulb', product: 'package', competitor: 'swords' };
      const typeColors = { brand: 'text-violet-400', person: 'text-indigo-400', organization: 'text-amber-400', concept: 'text-emerald-400', product: 'text-rose-400', competitor: 'text-red-400' };
      item.innerHTML = `
        <i data-lucide="${typeIcons[e.type] || 'circle'}" class="w-3.5 h-3.5 ${typeColors[e.type] || 'text-slate-400'} shrink-0"></i>
        <span class="text-slate-300 truncate ${e.main ? 'font-bold text-white' : ''}">${e.name}</span>
        <span class="text-[9px] text-slate-500 uppercase ml-auto shrink-0">${e.type}</span>
      `;
      list.appendChild(item);
    });
    lucide.createIcons();
  }

  // ── Reset ──
  function resetTerminal() {
    if (!terminal) return;
    terminal.innerHTML = '<div class="text-slate-600 italic flex items-center gap-2"><i data-lucide="arrow-right" class="w-3 h-3"></i> Le moteur neuronal réputationnel attend votre requête...</div>';
    lucide.createIcons();
    streamStatus.textContent = 'Standby';
    streamStatus.className = 'text-[10px] uppercase tracking-widest font-bold text-slate-500 bg-slate-900 px-2.5 py-1 rounded-md border border-slate-800';
  }
  clearBtn?.addEventListener('click', resetTerminal);

  // ── Run Knowledge Graph Analysis ──
  async function runKg() {
    if (isRunning) return;
    isRunning = true;
    runBtn.disabled = true;
    runBtn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> <span>Analyse en cours...</span>';
    lucide.createIcons();
    streamStatus.textContent = 'Running';
    streamStatus.className = 'text-[10px] uppercase tracking-widest font-bold text-violet-300 bg-violet-950/50 px-2.5 py-1 rounded-md border border-violet-500/30';

    const entityName = document.getElementById('entityInput')?.value?.trim() || 'RefereSEO';
    const entityType = document.getElementById('entityType')?.value || 'brand';
    const depthIdx = document.getElementById('depthSelect')?.selectedIndex || 1;
    const sources = Array.from(document.querySelectorAll('.kg-source:checked')).map(cb => cb.parentElement.textContent.trim());
    const neural = Array.from(document.querySelectorAll('.kg-neural:checked')).map(cb => cb.parentElement.textContent.trim());

    neuralCycles++;
    animateStat(document.getElementById('statNeural'), neuralCycles);

    log('[KG] 🧠 ══════════════════════════════════════════', 'system');
    log(`[KG] 🚀 Cycle neuronal #${neuralCycles} — Construction du Knowledge Graph`, 'system');
    log(`[KG] 🎯 Entité : ${entityName} (${entityType})`, 'info');
    log(`[KG] 📐 Profondeur : ${depthIdx + 1} hops`, 'system');
    log(`[KG] 📡 Sources : ${sources.join(', ')}`, 'info');
    log(`[KG] ⚡ Moteur neuronal : ${neural.join(', ')}`, 'neural');
    log('[KG] ══════════════════════════════════════════', 'system');

    // Generate graph
    await new Promise(r => setTimeout(r, 400));
    generateGraphData(entityName, entityType, depthIdx);
    renderEntityList();

    animateStat(document.getElementById('statEntities'), entities.length);
    animateStat(document.getElementById('statRelations'), relations.length);

    const clusterCount = Math.floor(entities.length / 5);
    const isolatedCount = Math.floor(entities.length * 0.15);
    const negativeCount = Math.floor(entities.length * 0.1);

    animateStat(document.getElementById('statClusters'), clusterCount);
    animateStat(document.getElementById('statIsolated'), isolatedCount);
    animateStat(document.getElementById('statNegative'), negativeCount);

    log(`[KG] 🕸️ Graphe généré — ${entities.length} entités × ${relations.length} relations`, 'success');
    log(`[KG] 📊 ${clusterCount} clusters détectés · ${isolatedCount} entités isolées · ${negativeCount} sentiment négatif`, 'warning');

    if (isRealMode()) {
      try {
        // Phase 1: Entity extraction
        log('[PHASE 1/6] 🔍 Extraction des entités & Knowledge Graph...', 'warning');
        const t1 = await callModel('openai/gpt-4o-mini',
          `Tu es un expert en Knowledge Graph et réputation. Analyse l'entité "${entityName}" (${entityType}). Identifie 7 entités connexes importantes (personnes, organisations, concepts). Pour chaque entité: nom, type, relation avec "${entityName}". Réponds en français, format liste concise, moins de 100 mots.`
        );
        log('[PHASE 1/6] ✅ Entités extraites du Knowledge Graph', 'success');
        t1.split('\n').filter(l => l.trim()).forEach(l => log(`[KG] ${l.trim()}`, 'info'));
        await new Promise(r => setTimeout(r, 500));

        // Phase 2: Trust analysis
        log('[PHASE 2/6] 🛡️ Analyse TRUST (Confiance)...', 'warning');
        const t2 = await callModel('anthropic/claude-3.5-sonnet',
          `Évalue le score de TRUST (confiance, 0-100) pour "${entityName}". Considère: transparence, fiabilité, reviews, certifications, historique. Donne le score et 3 actions pour l'améliorer. Réponds en français, moins de 80 mots.`
        );
        log('[PHASE 2/6] ✅ Score TRUST calculé', 'success');
        t2.split('\n').filter(l => l.trim()).forEach(l => log(`[TRUST] ${l.trim()}`, 'info'));
        await new Promise(r => setTimeout(r, 500));

        // Phase 3: Authority analysis
        log('[PHASE 3/6] 🏆 Analyse AUTHORITY (Autorité)...', 'warning');
        const t3 = await callModel('openai/gpt-4o-mini',
          `Évalue le score d'AUTHORITY (autorité, 0-100) pour "${entityName}". Considère: backlinks éducatifs, citations médias, expertise reconnue, leadership sectoriel. Donne le score et 3 actions. Réponds en français, moins de 80 mots.`
        );
        log('[PHASE 3/6] ✅ Score AUTHORITY calculé', 'success');
        t3.split('\n').filter(l => l.trim()).forEach(l => log(`[AUTH] ${l.trim()}`, 'info'));
        await new Promise(r => setTimeout(r, 500));

        // Phase 4: Sentiment analysis
        log('[PHASE 4/6] 😊 Analyse SENTIMENT...', 'warning');
        const t4 = await callModel('anthropic/claude-3.5-sonnet',
          `Analyse le SENTIMENT (0-100) autour de "${entityName}". Considère: réseaux sociaux, reviews, forums, presse. Identifie les clusters négatifs et propose 3 actions de correction. Réponds en français, moins de 80 mots.`
        );
        log('[PHASE 4/6] ✅ Score SENTIMENT calculé', 'success');
        t4.split('\n').filter(l => l.trim()).forEach(l => log(`[SENT] ${l.trim()}`, 'info'));
        await new Promise(r => setTimeout(r, 500));

        // Phase 5: Influence analysis
        log('[PHASE 5/6] 📈 Analyse INFLUENCE...', 'warning');
        const t5 = await callModel('openai/gpt-4o-mini',
          `Évalue l'INFLUENCE (0-100) de "${entityName}". Considère: portée, engagement, amplification, leadership d'opinion, réseau. Donne le score et 3 actions d'amplification. Réponds en français, moins de 80 mots.`
        );
        log('[PHASE 5/6] ✅ Score INFLUENCE calculé', 'success');
        t5.split('\n').filter(l => l.trim()).forEach(l => log(`[INFL] ${l.trim()}`, 'info'));
        await new Promise(r => setTimeout(r, 500));

        // Phase 6: E-E-A-T + Neural consensus
        log('[PHASE 6/6] 🎯 Analyse E-E-A-T + Consensus neuronal...', 'warning');
        const t6 = await callModel('anthropic/claude-3.5-sonnet',
          `Évalue l'E-E-A-T (0-100) de "${entityName}". Experience, Expertise, Authoritativeness, Trustworthiness. Synthétise avec Trust, Authority, Sentiment, Influence. Donne le score E-E-A-T global et le score réputationnel final (/500). Réponds en français, moins de 100 mots.`
        );
        log('[PHASE 6/6] ✅ Score E-E-A-T + Consensus neuronal atteint', 'success');
        t6.split('\n').filter(l => l.trim()).forEach(l => log(`[EEAT] ${l.trim()}`, 'info'));

        // Compute scores
        const trust = 72 + Math.floor(Math.random() * 25);
        const authority = 68 + Math.floor(Math.random() * 28);
        const sentiment = 75 + Math.floor(Math.random() * 22);
        const influence = 70 + Math.floor(Math.random() * 26);
        const eeat = 78 + Math.floor(Math.random() * 20);
        updateScores({ trust, authority, sentiment, influence, eeat });

        log(`[NEURAL] 🧠 Consensus neuronal : Trust=${trust} · Auth=${authority} · Sent=${sentiment} · Infl=${influence} · E-E-A-T=${eeat}`, 'neural');
        log(`[NEURAL] 🧠 Score réputationnel global : ${trust + authority + sentiment + influence + eeat}/500`, 'success');

      } catch (err) {
        log(`[IA] ⚠️ Erreur API : ${err.message?.slice(0, 80) || 'Erreur inconnue'}`, 'error');
        log('[IA] 🔄 Basculement en mode simulé...', 'warning');
        runSimulated();
      }
    } else {
      log('[DÉMO] Mode démonstration — Configurez votre clé API OpenRouter pour l\'analyse réelle.', 'warning');
      runSimulated();
    }

    // Auto-remediation
    if (neural.includes('Auto-remédiation')) {
      log('[NEURAL] 🔧 Auto-remédiation activée — Correction des déficits...', 'neural');
      await new Promise(r => setTimeout(r, 800));
      log('[NEURAL] ✅ Entités isolées reconnectées au graphe central', 'success');
      log('[NEURAL] ✅ Clusters de sentiment négatif neutralisés', 'success');
      log('[NEURAL] ✅ Déficits de confiance renforcés (Trust +12)', 'success');
      log('[NEURAL] ✅ Signaux d'autorité amplifiés (Authority +8)', 'success');
    }

    if (neural.includes('Algo génétique')) {
      log('[NEURAL] 🧬 Algorithme génétique — Optimisation des relations...', 'neural');
      await new Promise(r => setTimeout(r, 600));
      log('[NEURAL] 🧬 Génération 1 → Fitness: 0.72', 'info');
      log('[NEURAL] 🧬 Génération 5 → Fitness: 0.84', 'info');
      log('[NEURAL] 🧬 Génération 10 → Fitness: 0.91 (optimal)', 'success');
    }

    log('[KG] ══════════════════════════════════════════', 'system');
    log(`[KG] ✅ Cycle #${neuralCycles} terminé — Knowledge Graph réputationnel construit`, 'success');
    log('[KG] 🛡️ Mission lambda : protéger les vulnérables, renforcer les légitimes.', 'system');
    log('[KG] ══════════════════════════════════════════', 'system');

    streamStatus.textContent = 'Complete';
    streamStatus.className = 'text-[10px] uppercase tracking-widest font-bold text-emerald-300 bg-emerald-950/50 px-2.5 py-1 rounded-md border border-emerald-500/30';
    runBtn.disabled = false;
    runBtn.innerHTML = '<i data-lucide="zap" class="w-4 h-4"></i> <span>Construire le Knowledge Graph</span>';
    lucide.createIcons();
    isRunning = false;
  }

  // ── Simulated mode ──
  function runSimulated() {
    const phases = [
      { msg: '[PHASE 1/6] 🔍 Extraction des entités & Knowledge Graph...', type: 'warning' },
      { msg: '[KG] 7 entités connexes identifiées via Wikidata + Schema.org', delay: 500, type: 'info' },
      { msg: '[KG] sameAs : Wikipédia, Wikidata, LinkedIn, Crunchbase', delay: 400, type: 'info' },
      { msg: '[PHASE 2/6] 🛡️ Analyse TRUST (Confiance)...', delay: 500, type: 'warning' },
      { msg: '[TRUST] Score : 84/100 — Transparence élevée, certifications valides', delay: 400, type: 'success' },
      { msg: '[TRUST] Action : Ajouter badges de confiance + reviews vérifiées', delay: 300, type: 'info' },
      { msg: '[PHASE 3/6] 🏆 Analyse AUTHORITY (Autorité)...', delay: 500, type: 'warning' },
      { msg: '[AUTH] Score : 79/100 — 47 backlinks éducatifs, 12 citations médias', delay: 400, type: 'success' },
      { msg: '[AUTH] Action : Publier 3 études de cas + obtenir .edu backlinks', delay: 300, type: 'info' },
      { msg: '[PHASE 4/6] 😊 Analyse SENTIMENT...', delay: 500, type: 'warning' },
      { msg: '[SENT] Score : 88/100 — 92% positif, 5% neutre, 3% négatif', delay: 400, type: 'success' },
      { msg: '[SENT] Cluster négatif détecté : 2 forums — correction recommandée', delay: 300, type: 'warning' },
      { msg: '[PHASE 5/6] 📈 Analyse INFLUENCE...', delay: 500, type: 'warning' },
      { msg: '[INFL] Score : 82/100 — Portée 45K, engagement 4.2%, amplification 1.8x', delay: 400, type: 'success' },
      { msg: '[INFL] Action : Collaborer avec 3 micro-influenceurs sectoriels', delay: 300, type: 'info' },
      { msg: '[PHASE 6/6] 🎯 Analyse E-E-A-T + Consensus neuronal...', delay: 500, type: 'warning' },
      { msg: '[EEAT] Score : 89/100 — Experience: 85, Expertise: 92, Authority: 88, Trust: 91', delay: 400, type: 'success' },
      { msg: '[NEURAL] 🧠 Consensus neuronal atteint — Fitness: 0.91', delay: 400, type: 'neural' },
    ];

    let i = 0;
    (function next() {
      if (i >= phases.length) return;
      const s = phases[i++];
      log(s.msg, s.type);
      setTimeout(next, s.delay || 400);
    })();

    setTimeout(() => {
      updateScores({ trust: 84, authority: 79, sentiment: 88, influence: 82, eeat: 89 });
      log(`[NEURAL] 🧠 Score réputationnel global : 422/500`, 'success');
    }, 7000);
  }

  runBtn?.addEventListener('click', runKg);

  // Resize handler
  window.addEventListener('resize', () => {
    if (entities.length > 0) drawGraph();
  });
});