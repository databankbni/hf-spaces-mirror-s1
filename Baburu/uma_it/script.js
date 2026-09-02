const LANE_COLORS = {
  Speed:   'var(--lane-speed)',
  Stamina: 'var(--lane-stamina)',
  Power:   'var(--lane-power)',
  Guts:    'var(--lane-guts)',
  Wit:     'var(--lane-wit)',
  Friend:  'var(--lane-friend)',
  Group:   'var(--lane-group)'
};

// Master Skill Database fallback built directly into script.js
const MASTER_CARD_SKILLS = {
  "Riko Kashimoto SSR": { hints: [], events: ["Steel Will", "First Step"] },
  "Light Hello SSR": { hints: ["Pace Up", "Slipstream"], events: ["First Step", "Corner Recovery"] },
  "Tazuna Hayakawa SSR": { hints: [], events: ["Position Sense", "Play Maker"] },
  "Aoi Kiryuin SR": { hints: [], events: ["Position Sense", "Play Maker"] },
  "Sasami Anshinzawa SSR": { hints: [], events: ["Corner Recovery", "A Small Breather"] },
  "Heirs to the Throne SSR": { hints: [], events: ["Non-Stop Girl", "Slipstream"] },
  "Haru Urara SSR": { hints: [], events: ["Steel Will", "Effort Up"] },
  "Admire Vega SR": { hints: ["Upward Step", "Climax", "Late Surger Corner", "Late Surger Straight"], events: ["Sharp Arc", "Rapid Burst"] },
  "Admire Vega SSR": { hints: ["Upward Step", "Climax", "Late Surger Corner", "Late Surger Straight"], events: ["Sharp Arc", "Total Eclipse"] },
  "Yukino Bijin SSR": { hints: ["Medium Straight", "Medium Corner", "Pace Up", "Slipstream"], events: ["Total Eclipse", "Medium Recovery"] },
  "Yukino Bijin SR": { hints: ["Medium Straight", "Medium Corner", "Pace Up"], events: ["Medium Recovery", "Rapid Burst"] },
  "Mejiro Ryan SSR": { hints: ["Medium Straight", "Medium Corner", "Late Surger Corner", "Late Surger Straight"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Mejiro Ryan SR": { hints: ["Medium Straight", "Medium Corner", "Late Surger Corner", "Late Surger Straight"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Air Groove SR": { hints: ["Medium Straight", "Medium Corner", "Pace Up", "Slipstream"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Seeking the Pearl SR": { hints: ["Mile Corner", "Mile Straight", "Rapid Burst", "Front Runner Straight"], events: ["Sharp Arc", "Mile Recovery"] },
  "Seeking the Pearl SSR": { hints: ["Mile Corner", "Mile Straight", "Rapid Burst"], events: ["Sharp Arc", "Top Gear"] },
  "Matikanetannhauser SSR": { hints: ["Long Straight", "Long Corner", "Corner Recovery"], events: ["Arc Maestro", "Effort Up"] },
  "Special Week SSR": { hints: ["Pace Up", "Slipstream", "Upward Step", "Position Sense"], events: ["Total Eclipse", "Mile Recovery"] },
  "Special Week SR": { hints: ["Pace Up", "Slipstream", "Upward Step"], events: ["Mile Recovery", "Rapid Burst"] },
  "Syrius Symboli SR": { hints: ["Medium Straight", "Medium Corner", "Position Sense", "Slipstream"], events: ["Sharp Arc", "Medium Recovery"] },
  "Syrius Symboli SSR": { hints: ["Medium Straight", "Medium Corner", "Position Sense", "Slipstream"], events: ["Sharp Arc", "Total Eclipse"] },
  "Nice Nature SR": { hints: ["Position Sense", "Slipstream", "Late Surger Corner", "Late Surger Straight"], events: ["Rapid Burst", "A Small Breather"] },
  "Nice Nature SSR": { hints: ["Position Sense", "Slipstream", "Late Surger Corner", "Late Surger Straight"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Meisho Doto SR": { hints: ["Medium Straight", "Medium Corner", "Late Surger Corner"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Meisho Doto SSR": { hints: ["Medium Straight", "Medium Corner", "Late Surger Straight", "Late Surger Corner"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Smart Falcon SR": { hints: ["Dirt Straight", "Dirt Corner", "Front Runner Straight", "Front Runner Corner"], events: ["Chart Topper", "Rapid Burst"] },
  "Smart Falcon SSR": { hints: ["Dirt Straight", "Dirt Corner", "Front Runner Straight", "Front Runner Corner"], events: ["Chart Topper", "Dirt Recovery"] },
  "Tamamo Cross SR": { hints: ["Long Straight", "Long Corner", "Late Surger Straight"], events: ["Total Eclipse", "Rapid Burst"] },
  "Tamamo Cross SSR": { hints: ["Long Straight", "Long Corner", "Late Surger Straight", "Late Surger Corner"], events: ["Total Eclipse", "Rapid Burst"] },
  "Sakura Chiyono O SSR": { hints: ["Medium Straight", "Medium Corner", "Pace Up", "Slipstream"], events: ["Total Eclipse", "Medium Recovery"] },
  "Sakura Bakushin O SSR": { hints: ["Short Straight", "Short Corner", "Front Runner Straight", "Front Runner Corner"], events: ["Chart Topper", "Rapid Burst"] },
  "Sakura Bakushin O SR": { hints: ["Short Straight", "Short Corner", "Front Runner Straight"], events: ["Chart Topper", "Rapid Burst"] },
  "Marvelous Sunday SSR": { hints: ["Pace Up", "Slipstream", "Position Sense", "Upward Step"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Marvelous Sunday SR": { hints: ["Pace Up", "Slipstream", "Position Sense"], events: ["Rapid Burst", "A Small Breather"] },
  "Daitaku Helios SSR": { hints: ["Mile Corner", "Mile Straight", "Pace Up", "Slipstream"], events: ["Chart Topper", "Rapid Burst"] },
  "Daitaku Helios SR": { hints: ["Mile Corner", "Mile Straight", "Pace Up"], events: ["Rapid Burst", "Mile Recovery"] },
  "Nishino Flower SR": { hints: ["Mile Corner", "Mile Straight", "Upward Step", "Slipstream"], events: ["Sharp Arc", "Mile Recovery"] },
  "Agnes Digital SR": { hints: ["Dirt Straight", "Dirt Corner", "Late Surger Corner", "Late Surger Straight"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Hishi Amazon SR": { hints: ["Late Surger Straight", "Late Surger Corner", "Slipstream", "Upward Step"], events: ["Total Eclipse", "Rapid Burst"] },
  "El Condor Pasa SSR": { hints: ["Pace Up", "Slipstream", "Position Sense", "Dirt Straight"], events: ["Total Eclipse", "Dirt Recovery"] },
  "Yaeno Muteki SSR": { hints: ["Medium Straight", "Medium Corner", "Pace Up", "Slipstream"], events: ["Total Eclipse", "Medium Recovery"] },
  "Mihono Bourbon SR": { hints: ["Front Runner Straight", "Front Runner Corner", "Position Sense", "Pace Up"], events: ["Chart Topper", "Rapid Burst"] },
  "Mihono Bourbon SSR": { hints: ["Front Runner Straight", "Front Runner Corner", "Position Sense", "Pace Up"], events: ["Chart Topper", "Escape Artist"] },
  "Biwa Hayahide SR": { hints: ["Long Straight", "Long Corner", "Position Sense"], events: ["Total Eclipse", "Long Recovery"] },
  "Biwa Hayahide SSR": { hints: ["Long Straight", "Long Corner", "Position Sense", "Pace Up"], events: ["Total Eclipse", "Long Recovery"] },
  "Rice Shower SSR": { hints: ["Long Straight", "Long Corner", "Corner Recovery", "Position Sense"], events: ["Arc Maestro", "Rapid Burst"] },
  "Fine Motion SR": { hints: ["Corner Recovery", "Position Sense", "Pace Up"], events: ["Speed Star", "Rapid Burst"] },
  "Fine Motion SSR": { hints: ["Corner Recovery", "Position Sense", "Pace Up", "Slipstream"], events: ["Speed Star", "Rapid Burst"] },
  "Kawakami Princess SSR": { hints: ["Medium Straight", "Medium Corner", "Late Surger Straight", "Late Surger Corner"], events: ["All-Out Spirit", "Rapid Burst"] },
  "King Halo SSR": { hints: ["Short Straight", "Short Corner", "Late Surger Straight", "Late Surger Corner"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Winning Ticket SSR": { hints: ["Medium Straight", "Medium Corner", "Late Surger Straight"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Inari One SR": { hints: ["Dirt Straight", "Dirt Corner", "Late Surger Straight"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Sweep Tosho SSR": { hints: ["Slipstream", "Position Sense", "Pace Up", "Upward Step"], events: ["Total Eclipse", "Rapid Burst"] },
  "Sweep Tosho SR": { hints: ["Slipstream", "Position Sense", "Pace Up"], events: ["Rapid Burst", "A Small Breather"] },
  "Biko Pegasus SSR": { hints: ["Short Straight", "Short Corner", "Pace Up", "Slipstream"], events: ["Chart Topper", "Rapid Burst"] },
  "Shinko Windy SR": { hints: ["Dirt Straight", "Dirt Corner", "Slipstream", "Pace Up"], events: ["Chart Topper", "Rapid Burst"] },
  "Silence Suzuka SSR": { hints: ["Front Runner Straight", "Front Runner Corner", "Pace Up", "Slipstream"], events: ["Escape Artist", "Rapid Burst"] },
  "Maruzensky SSR": { hints: ["Mile Straight", "Mile Corner", "Front Runner Straight", "Front Runner Corner"], events: ["Top Gear", "Rapid Burst"] },
  "Agnes Tachyon SSR": { hints: ["Medium Straight", "Medium Corner", "Pace Up", "Slipstream"], events: ["Total Eclipse", "Medium Recovery"] },
  "Agnes Tachyon SR": { hints: ["Medium Straight", "Medium Corner", "Pace Up"], events: ["Medium Recovery", "Rapid Burst"] },
  "Kitasan Black SSR": { hints: ["Corner Recovery", "Pace Up", "Slipstream", "Position Sense"], events: ["Arc Maestro", "Rapid Burst"] },
  "Tosen Jordan SSR": { hints: ["Medium Straight", "Medium Corner", "Late Surger Corner", "Late Surger Straight"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Tosen Jordan SR": { hints: ["Medium Straight", "Medium Corner", "Late Surger Corner"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Mayano Top Gun SSR": { hints: ["Long Straight", "Long Corner", "Front Runner Straight", "Front Runner Corner"], events: ["Chart Topper", "Rapid Burst"] },
  "Mayano Top Gun SR": { hints: ["Long Straight", "Long Corner", "Front Runner Straight"], events: ["Chart Topper", "Rapid Burst"] },
  "Eishin Flash SR": { hints: ["Medium Straight", "Medium Corner", "Late Surger Straight"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Narita Top Road SSR": { hints: ["Long Straight", "Long Corner", "Pace Up", "Slipstream"], events: ["Total Eclipse", "Long Recovery"] },
  "Vodka SR": { hints: ["Mile Straight", "Mile Corner", "Slipstream", "Position Sense"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Narita Brian SSR": { hints: ["Medium Straight", "Medium Corner", "Pace Up", "Slipstream"], events: ["Total Eclipse", "Medium Recovery"] },
  "Taiki Shuttle SSR": { hints: ["Mile Straight", "Mile Corner", "Front Runner Straight"], events: ["Top Gear", "Rapid Burst"] },
  "Air Shakur SSR": { hints: ["Medium Straight", "Medium Corner", "Position Sense"], events: ["Total Eclipse", "Medium Recovery"] },
  "Gold City SSR": { hints: ["Mile Straight", "Mile Corner", "Position Sense"], events: ["Sharp Arc", "Mile Recovery"] },
  "Super Creek SSR": { hints: ["Long Straight", "Long Corner", "Corner Recovery", "Pace Up"], events: ["Arc Maestro", "Rapid Burst"] },
  "Satono Diamond SSR": { hints: ["Long Straight", "Long Corner", "Slipstream", "Position Sense"], events: ["Total Eclipse", "Long Recovery"] },
  "Manhattan Cafe SSR": { hints: ["Long Straight", "Long Corner", "Position Sense", "Slipstream"], events: ["Total Eclipse", "Long Recovery"] },
  "Manhattan Cafe SR": { hints: ["Long Straight", "Long Corner", "Position Sense"], events: ["Long Recovery", "Rapid Burst"] },
  "Seiun Sky SSR": { hints: ["Long Straight", "Long Corner", "Front Runner Straight", "Front Runner Corner"], events: ["Chart Topper", "Rapid Burst"] },
  "Seiun Sky SR": { hints: ["Long Straight", "Long Corner", "Front Runner Straight"], events: ["Chart Topper", "Rapid Burst"] },
  "Mejiro McQueen SSR": { hints: ["Long Straight", "Long Corner", "Front Runner Straight", "Front Runner Corner"], events: ["Chart Topper", "Long Recovery"] },
  "Mejiro Bright SSR": { hints: ["Long Straight", "Long Corner", "Position Sense", "Slipstream"], events: ["Total Eclipse", "Long Recovery"] },
  "Gold Ship SSR": { hints: ["Long Straight", "Long Corner", "Late Surger Straight", "Late Surger Corner"], events: ["Total Eclipse", "Rapid Burst"] },
  "Zenno Rob Roy SR": { hints: ["Medium Straight", "Medium Corner", "Position Sense"], events: ["Total Eclipse", "Medium Recovery"] },
  "Zenno Rob Roy SSR": { hints: ["Medium Straight", "Medium Corner", "Position Sense", "Slipstream"], events: ["Total Eclipse", "Medium Recovery"] },
  "Mejiro Dober SR": { hints: ["Medium Straight", "Medium Corner", "Late Surger Straight"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Mr. CB SSR": { hints: ["Late Surger Straight", "Late Surger Corner", "Position Sense", "Slipstream"], events: ["Total Eclipse", "Rapid Burst"] },
  "Ikuno Dictus SR": { hints: ["Medium Straight", "Medium Corner", "Position Sense"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Tokai Teio SSR": { hints: ["Medium Straight", "Medium Corner", "Position Sense", "Slipstream"], events: ["Total Eclipse", "Medium Recovery"] },
  "Tokai Teio SR": { hints: ["Medium Straight", "Medium Corner", "Position Sense"], events: ["Medium Recovery", "Rapid Burst"] },
  "Fuji Kiseki SR": { hints: ["Mile Straight", "Mile Corner", "Slipstream", "Position Sense"], events: ["All-Out Spirit", "Rapid Burst"] },
  "Daiwa Scarlet SR": { hints: ["Medium Straight", "Medium Corner", "Front Runner Straight"], events: ["Chart Topper", "Rapid Burst"] },
  "Ines Fujin SR": { hints: ["Front Runner Straight", "Front Runner Corner", "Pace Up", "Slipstream"], events: ["Chart Topper", "Rapid Burst"] },
  "Matikanefukukitaru SR": { hints: ["Lucky Seven", "A Small Breather", "Triple 7s", "First Step"], events: ["Sharp Arc", "Position Sense"]}
};

let deck = []; // Stores selected cards (max 6)
let sortKey = 'score';
let sortDir = -1; // -1 desc, 1 asc
let activeType = '';
let searchQuery = '';

let tierTypeFilterVal = '';
let tierSearchVal = '';

let skillSearchVal = '';
let skillCategoryFilterVal = '';

const tbody = document.getElementById('tbody');
const typeFilter = document.getElementById('typeFilter');
const searchInput = document.getElementById('searchInput');

// Preloads all images into browser memory cache
function preloadImages(cards) {
  const urls = [...new Set(cards.map(c => c.img))];
  urls.forEach(url => {
    const img = new Image();
    img.src = url;
  });
}

async function init() {
  try {
    const res = await fetch('cards.json');
    CARDS = await res.json();

    // Assign unique IDs and ensure skills object is attached from Master Database
    CARDS.forEach((c, i) => {
      c.id = i;
      if (!c.skills || (!c.skills.hints && !c.skills.events)) {
        c.skills = MASTER_CARD_SKILLS[c.name] || { hints: ["Pace Up", "Slipstream"], events: ["Rapid Burst", "A Small Breather"] };
      }
    });

    // Preload all card images
    preloadImages(CARDS);

    // Set meta data
    document.getElementById('metaCount').textContent = CARDS.length;
    document.getElementById('metaTop').textContent = Math.max(...CARDS.map(c => c.score)).toFixed(2);

    // Populate type filter dropdowns
    const types = [...new Set(CARDS.map(c => c.type))].sort();
    types.forEach(t => {
      const opt1 = document.createElement('option');
      opt1.value = t; opt1.textContent = t;
      typeFilter.appendChild(opt1);

      const opt2 = document.createElement('option');
      opt2.value = t; opt2.textContent = t;
      document.getElementById('tierTypeFilter').appendChild(opt2);
    });

    // Tab Navigation
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(btn.dataset.tab).classList.add('active');
      });
    });

    // Filters for Tab 1
    typeFilter.addEventListener('change', () => {
      activeType = typeFilter.value;
      renderTable();
    });

    if (searchInput) {
      searchInput.addEventListener('input', () => {
        searchQuery = searchInput.value.toLowerCase().trim();
        renderTable();
      });
    }

    // Filters for Tab 2 (Tier List)
    document.getElementById('tierTypeFilter').addEventListener('change', (e) => {
      tierTypeFilterVal = e.target.value;
      renderTierList();
    });

    document.getElementById('tierSearch').addEventListener('input', (e) => {
      tierSearchVal = e.target.value.toLowerCase().trim();
      renderTierList();
    });

    // Filters for Tab 3 (Skill Finder)
    document.getElementById('skillSearch').addEventListener('input', (e) => {
      skillSearchVal = e.target.value.toLowerCase().trim();
      renderSkillFinder();
    });

    document.getElementById('skillCategoryFilter').addEventListener('change', (e) => {
      skillCategoryFilterVal = e.target.value;
      renderSkillFinder();
    });

    // Clear Deck Button
    document.getElementById('btnClearDeck').addEventListener('click', () => {
      deck = [];
      updateDeckUI();
      syncTierListDeckState();
    });

    // Table Header Sorting
    document.querySelectorAll('thead th').forEach(th => {
      th.addEventListener('click', () => {
        const key = th.dataset.key;
        if (key === 'rank') return;
        if (sortKey === key) {
          sortDir *= -1;
        } else {
          sortKey = key;
          sortDir = (key === 'name' || key === 'lb' || key === 'type') ? 1 : -1;
        }
        renderTable();
      });
    });

    renderTable();
    updateDeckUI();
    renderTierList();
    renderSkillFinder();
  } catch (err) {
    console.error('Failed to load cards.json:', err);
  }
}

/* ========================================= */
/* TAB 1: RANKING TABLE RENDER               */
/* ========================================= */
function renderTable() {
  let rows = CARDS.filter(c => {
    const matchesType = !activeType || c.type === activeType;
    const matchesSearch = !searchQuery || c.name.toLowerCase().includes(searchQuery);
    return matchesType && matchesSearch;
  });

  rows.sort((a, b) => {
    let av = a[sortKey], bv = b[sortKey];
    if (typeof av === 'string') {
      return av.localeCompare(bv) * sortDir;
    }
    return (av - bv) * sortDir;
  });

  // Update header arrows
  document.querySelectorAll('thead th').forEach(th => {
    const key = th.dataset.key;
    const isSortKey = (key === sortKey);
    th.classList.toggle('active', isSortKey);

    const arrowSpan = th.querySelector('.arrow');
    if (arrowSpan) {
      arrowSpan.textContent = isSortKey ? (sortDir === 1 ? '▲' : '▼') : '';
    }
  });

  tbody.innerHTML = '';
  rows.forEach((c, i) => {
    const tr = document.createElement('tr');
    const rankClass = i === 0 ? 'top1' : i === 1 ? 'top2' : i === 2 ? 'top3' : '';
    const laneColor = LANE_COLORS[c.type] || 'var(--gold)';
    tr.innerHTML = `
      <td class="rank ${rankClass}">${i + 1}</td>
      <td class="name-cell" style="--lane-color:${laneColor}">
        <div class="card-info">
          <img src="${c.img}" alt="" class="card-thumb">
          <span>${c.name}</span>
        </div>
      </td>
      <td class="lb-tag">${c.lb}</td>
      <td><span class="type-tag" style="--lane-color:${laneColor}">${c.type}</span></td>
      <td class="num score-cell">${c.score.toFixed(2)}</td>
      <td class="num">${fmt(c.speed)}</td>
      <td class="num">${fmt(c.stamina)}</td>
      <td class="num">${fmt(c.power)}</td>
      <td class="num">${fmt(c.guts)}</td>
      <td class="num">${fmt(c.wit)}</td>
      <td class="num">${fmt(c.total)}</td>
      <td class="num">${fmt(c.sp)}</td>
      <td class="num">${fmt(c.rb)}</td>
    `;
    tbody.appendChild(tr);
  });
}

/* ========================================= */
/* TAB 2: DECK BUILDER & TIER LIST LOGIC     */
/* ========================================= */

function addToDeck(card) {
  if (deck.length >= 6) return;
  if (deck.some(d => d.id === card.id)) return;
  deck.push(card);
  updateDeckUI();
  syncTierListDeckState();
}

function removeFromDeckIndex(index) {
  deck.splice(index, 1);
  updateDeckUI();
  syncTierListDeckState();
}

function removeFromDeckById(id) {
  deck = deck.filter(d => d.id !== id);
  updateDeckUI();
  syncTierListDeckState();
}

function syncTierListDeckState() {
  document.querySelectorAll('.tier-card').forEach(cardEl => {
    const cardId = parseInt(cardEl.dataset.id, 10);
    const inDeck = deck.some(d => d.id === cardId);
    
    cardEl.classList.toggle('in-deck', inDeck);
    
    let overlay = cardEl.querySelector('.in-deck-overlay');
    if (inDeck) {
      if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'in-deck-overlay';
        overlay.textContent = '✓ DECK';
        cardEl.querySelector('.card-thumb-wrapper').appendChild(overlay);
      }
    } else {
      if (overlay) {
        overlay.remove();
      }
    }
  });
}

function updateDeckUI() {
  const slotsEl = document.getElementById('deckSlots');
  const countEl = document.getElementById('deckCount');
  if (!slotsEl) return;

  countEl.textContent = `${deck.length} / 6 Cards`;
  slotsEl.innerHTML = '';

  for (let i = 0; i < 6; i++) {
    const slot = document.createElement('div');
    if (i < deck.length) {
      const c = deck[i];
      const laneColor = LANE_COLORS[c.type] || 'var(--gold)';
      slot.className = 'deck-slot filled';
      slot.style.setProperty('--lane-color', laneColor);
      slot.innerHTML = `
        <img src="${c.img}" alt="" class="slot-img">
        <div class="slot-info">
          <span class="slot-name">${c.name}</span>
          <div class="slot-tags">
            <span class="slot-type" style="color:${laneColor}">${c.type}</span>
            <span class="slot-lb">${c.lb}</span>
          </div>
        </div>
        <button class="btn-remove-slot" title="Remove Card">&times;</button>
      `;
      slot.querySelector('.btn-remove-slot').addEventListener('click', (e) => {
        e.stopPropagation();
        removeFromDeckIndex(i);
      });
    } else {
      slot.className = 'deck-slot empty';
      slot.innerHTML = `<span style="font-size:18px; margin-right:6px;">+</span> <span>Add Card</span>`;
    }
    slotsEl.appendChild(slot);
  }

  // Calculate sum of stats
  const totSpeed = deck.reduce((a, c) => a + (c.speed || 0), 0);
  const totStamina = deck.reduce((a, c) => a + (c.stamina || 0), 0);
  const totPower = deck.reduce((a, c) => a + (c.power || 0), 0);
  const totGuts = deck.reduce((a, c) => a + (c.guts || 0), 0);
  const totWit = deck.reduce((a, c) => a + (c.wit || 0), 0);
  const totTotal = deck.reduce((a, c) => a + (c.total || 0), 0);
  const totSP = deck.reduce((a, c) => a + (c.sp || 0), 0);
  const totRB = deck.reduce((a, c) => a + (c.rb || 0), 0);

  document.getElementById('totSpeed').textContent = Math.round(totSpeed);
  document.getElementById('totStamina').textContent = Math.round(totStamina);
  document.getElementById('totPower').textContent = Math.round(totPower);
  document.getElementById('totGuts').textContent = Math.round(totGuts);
  document.getElementById('totWit').textContent = Math.round(totWit);
  document.getElementById('totTotal').textContent = Math.round(totTotal);
  document.getElementById('totSP').textContent = Math.round(totSP);
  document.getElementById('totRB').textContent = Math.round(totRB) + '%';
}

function renderTierList() {
  const tierListEl = document.getElementById('tierList');
  if (!tierListEl) return;

  const filtered = CARDS.filter(c => {
    const matchesType = !tierTypeFilterVal || c.type === tierTypeFilterVal;
    const matchesSearch = !tierSearchVal || c.name.toLowerCase().includes(tierSearchVal);
    return matchesType && matchesSearch;
  });

  const tiers = [
    { name: 'S', color: '#ef4444', cards: filtered.filter(c => c.score >= 3.0) },
    { name: 'A', color: '#f97316', cards: filtered.filter(c => c.score >= 2.6 && c.score < 3.0) },
    { name: 'B', color: '#eab308', cards: filtered.filter(c => c.score >= 2.2 && c.score < 2.6) },
    { name: 'C', color: '#22c55e', cards: filtered.filter(c => c.score < 2.2) }
  ];

  tierListEl.innerHTML = '';

  tiers.forEach(t => {
    const row = document.createElement('div');
    row.className = 'tier-row';
    row.innerHTML = `
      <div class="tier-badge" style="background:${t.color}">
        <span>${t.name}</span>
      </div>
      <div class="tier-cards"></div>
    `;

    const cardsContainer = row.querySelector('.tier-cards');
    if (t.cards.length === 0) {
      cardsContainer.innerHTML = `<span class="empty-tier">No cards in this tier</span>`;
    } else {
      t.cards.forEach(c => {
        const inDeck = deck.some(d => d.id === c.id);
        const cardEl = document.createElement('div');
        cardEl.className = `tier-card ${inDeck ? 'in-deck' : ''}`;
        cardEl.dataset.id = c.id;
        cardEl.style.setProperty('--card-lane', LANE_COLORS[c.type] || 'var(--gold)');
        
        cardEl.innerHTML = `
          <div class="card-thumb-wrapper">
            <img src="${c.img}" alt="" class="tier-card-img">
            <span class="badge-score">${c.score.toFixed(2)}</span>
            <span class="badge-rb">${c.rb}RB</span>
            <span class="badge-type" style="color:${LANE_COLORS[c.type] || 'var(--gold)'}">${c.type}</span>
            ${inDeck ? '<div class="in-deck-overlay">✓ DECK</div>' : ''}
          </div>
          <div class="tier-card-info">
            <span class="tier-card-name">${c.name}</span>
            <span class="tier-card-lb">${c.lb}</span>
          </div>
        `;

        cardEl.addEventListener('click', () => {
          const isAlreadyInDeck = deck.some(d => d.id === c.id);
          if (isAlreadyInDeck) {
            removeFromDeckById(c.id);
          } else {
            addToDeck(c);
          }
        });

        cardsContainer.appendChild(cardEl);
      });
    }

    tierListEl.appendChild(row);
  });
}

/* ========================================= */
/* TAB 3: GAMETORA-STYLE SKILL FINDER        */
/* ========================================= */

function renderSkillFinder() {
  const galleryEl = document.getElementById('skillList');
  if (!galleryEl) return;

  // Deduplicate cards by (Name + Type) for the GameTora gallery grid
  const uniqueCardsMap = {};
  CARDS.forEach(c => {
    const key = `${c.name}_${c.type}`;
    if (!uniqueCardsMap[key] || c.lb === 'MLB') {
      uniqueCardsMap[key] = c;
    }
  });

  const uniqueCards = Object.values(uniqueCardsMap);

  // Filter cards based on matched skill search or card name
  let matchedCards = uniqueCards.filter(c => {
    if (!c.skills) return !skillSearchVal;

    let hintsList = c.skills.hints || [];
    let eventsList = c.skills.events || [];

    if (skillCategoryFilterVal === 'Hint') eventsList = [];
    if (skillCategoryFilterVal === 'Event') hintsList = [];

    const allSkills = [...hintsList, ...eventsList];

    if (!skillSearchVal) return true; // Show all cards if search is empty

    // Match either Skill Name OR Card Name!
    const matchesSkill = allSkills.some(s => s.toLowerCase().includes(skillSearchVal));
    const matchesCardName = c.name.toLowerCase().includes(skillSearchVal);

    return matchesSkill || matchesCardName;
  });

  galleryEl.innerHTML = '';

  if (matchedCards.length === 0) {
    galleryEl.innerHTML = `<div class="empty-tier">No support cards found with matching skills or card names.</div>`;
    return;
  }

  matchedCards.forEach(c => {
    const laneColor = LANE_COLORS[c.type] || 'var(--gold)';
    const inDeck = deck.some(d => d.name === c.name && d.type === c.type);

    // Find which skill matched the search
    let matchedSkillText = '';
    if (c.skills && skillSearchVal) {
      let hintsList = (c.skills.hints || []).filter(s => s.toLowerCase().includes(skillSearchVal));
      let eventsList = (c.skills.events || []).filter(s => s.toLowerCase().includes(skillSearchVal));

      if (skillCategoryFilterVal === 'Hint') eventsList = [];
      if (skillCategoryFilterVal === 'Event') hintsList = [];

      if (hintsList.length > 0) {
        matchedSkillText = `${hintsList[0]} (Hint)`;
      } else if (eventsList.length > 0) {
        matchedSkillText = `${eventsList[0]} (Event)`;
      }
    }

    const tile = document.createElement('div');
    tile.className = `gt-card-tile ${inDeck ? 'in-deck' : ''}`;
    tile.style.setProperty('--card-lane', laneColor);

    tile.innerHTML = `
      <div class="gt-card-img-wrap">
        <img src="${c.img}" alt="" class="gt-card-img">
        <span class="gt-badge-type">${c.type}</span>
      </div>
      <span class="gt-card-name">${c.name}</span>
      ${matchedSkillText ? `<span class="gt-matched-skill" title="${matchedSkillText}">${matchedSkillText}</span>` : ''}
    `;

    tile.addEventListener('click', () => {
      const matchInDeck = deck.find(d => d.name === c.name && d.type === c.type);
      if (matchInDeck) {
        removeFromDeckById(matchInDeck.id);
      } else {
        addToDeck(c);
      }
    });

    galleryEl.appendChild(tile);
  });
}

function fmt(v) {
  if (v === null || v === undefined) return '—';
  return Number.isInteger(v) ? v : v.toFixed(0);
}

document.addEventListener('DOMContentLoaded', init);