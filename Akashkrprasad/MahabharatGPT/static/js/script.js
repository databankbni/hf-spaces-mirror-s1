document.addEventListener('DOMContentLoaded', () => {
    /* ---------------- Static lore: factions, epithets, prashnas ---------------- */
    const FACTIONS = {
        pandava:  { label: 'Pandavas',          c1: '#ff9f1c', c2: '#cc5803', icon: 'fa-sun' },
        kaurava:  { label: 'Kauravas',          c1: '#c0392b', c2: '#5e1410', icon: 'fa-chess-rook' },
        warrior:  { label: 'Warriors & Gurus',  c1: '#c9a14a', c2: '#5c4326', icon: 'fa-shield-halved' },
        divine:   { label: 'Divine & Wise',     c1: '#1d9a8f', c2: '#0b3d91', icon: 'fa-om' },
        ancestor: { label: 'Elders & Ancestors', c1: '#9b59b6', c2: '#3a1c5c', icon: 'fa-crown' }
    };

    const CHARACTER_FACTION = {
        Yudhisthira: 'pandava', Bhima: 'pandava', Arjuna: 'pandava', Nakula: 'pandava',
        Sahadeva: 'pandava', Draupadi: 'pandava', Kunti: 'pandava', Pandu: 'pandava',
        Abhimanyu: 'pandava', Subhadra: 'pandava', Uttara: 'pandava',
        Duryodhana: 'kaurava', Shakuni: 'kaurava', Dhritarashtra: 'kaurava', Gandhari: 'kaurava',
        Karna: 'warrior', Drona: 'warrior', Ashwatthama: 'warrior', Bhishma: 'warrior',
        Ekalavya: 'warrior', Drupada: 'warrior',
        Krishna: 'divine', Vidura: 'divine', Sanjaya: 'divine',
        Shantanu: 'ancestor', Satyavati: 'ancestor', Amba: 'ancestor'
    };

    const EPITHETS = {
        Krishna: 'Yogeshwara · The Blue God',
        Yudhisthira: 'Dharmaraja · The Just King',
        Bhima: 'Vrikodara · The Storm Wind',
        Arjuna: 'Partha · Wielder of Gandiva',
        Nakula: 'Master of Steeds',
        Sahadeva: 'The Silent Seer',
        Duryodhana: 'Suyodhana · The Hundredth Crown',
        Karna: 'Daanveer · Son of the Sun',
        Dhritarashtra: 'The Blind King',
        Shakuni: 'Master of the Dice',
        Draupadi: 'Panchaali · Born of Fire',
        Kunti: 'Pritha · Mother of Heroes',
        Gandhari: 'The Blindfolded Queen',
        Satyavati: 'The Fisher Queen',
        Subhadra: 'Sister of Krishna',
        Uttara: 'Princess of Matsya',
        Amba: 'The Vow of Vengeance',
        Bhishma: 'Devavrata · The Terrible Vow',
        Drona: 'The Guru of Arms',
        Vidura: 'The Voice of Wisdom',
        Shantanu: 'King of Hastinapura',
        Pandu: 'The Pale King',
        Ashwatthama: 'The Immortal Wound',
        Abhimanyu: 'Breaker of the Chakravyuha',
        Ekalavya: 'The Self-Taught Archer',
        Sanjaya: 'The Divine Witness',
        Drupada: 'King of Panchala'
    };

    const PRASHNAS = [
        'What does dharma mean to you?',
        'Tell me of your greatest regret.',
        'What do you remember of Kurukshetra?',
        'Who did you love most in this life?'
    ];

    const SHLOKAS = [
        ['You have the right to action alone, never to its fruits.', 'Bhagavad Gita · 2.47'],
        ['Whenever dharma declines, I take form, age after age.', 'Bhagavad Gita · 4.7'],
        ['The soul is never born, and it never dies.', 'Bhagavad Gita · 2.20'],
        ['Set thy heart upon thy work, but never on its reward.', 'Bhagavad Gita · 2.47'],
        ['What is here is found elsewhere. What is not here, is nowhere.', 'The Mahabharata · 1.56']
    ];

    /* ---------------- Elements ---------------- */
    const contactsList = document.getElementById('contacts-list');
    const messagesContainer = document.getElementById('messages-container');
    const messageInput = document.getElementById('message-input');
    const sendBtn = document.getElementById('send-btn');
    const inputArea = document.getElementById('input-area');
    const prashnaBar = document.getElementById('prashna-bar');
    const headerName = document.getElementById('header-name');
    const headerStatus = document.getElementById('header-status');
    const headerAvatar = document.getElementById('header-avatar');
    const headerAvatarWrap = document.getElementById('header-avatar-wrap');
    const searchInput = document.getElementById('search-input');
    const factionFilters = document.getElementById('faction-filters');
    const soulCount = document.getElementById('soul-count');
    const sidebar = document.getElementById('sidebar');
    const backBtn = document.getElementById('back-to-list');
    const themeToggle = document.getElementById('theme-toggle');
    const infoBtn = document.getElementById('info-btn');
    const clearBtn = document.getElementById('clear-history-btn');
    const bioOverlay = document.getElementById('bio-overlay');
    const bioClose = document.getElementById('bio-close');

    /* ---------------- State ---------------- */
    let currentCharacter = null;
    let allCharacters = [];
    let activeFaction = 'all';
    let searchTerm = '';
    let userId = localStorage.getItem('mahabharata_user_id');
    if (!userId) {
        userId = 'user_' + Math.random().toString(36).substr(2, 9);
        localStorage.setItem('mahabharata_user_id', userId);
    }

    /* ---------------- Theme ---------------- */
    const savedTheme = localStorage.getItem('mahabharata_theme') || 'night';
    document.documentElement.setAttribute('data-theme', savedTheme);
    updateThemeIcon(savedTheme);

    themeToggle.addEventListener('click', () => {
        const next = document.documentElement.getAttribute('data-theme') === 'night' ? 'parchment' : 'night';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('mahabharata_theme', next);
        updateThemeIcon(next);
    });

    function updateThemeIcon(theme) {
        themeToggle.innerHTML = theme === 'night'
            ? '<i class="fas fa-moon"></i>'
            : '<i class="fas fa-sun"></i>';
    }

    /* ---------------- Avatar generation (themed monogram DP) ---------------- */
    function factionOf(name) {
        return CHARACTER_FACTION[name] || 'divine';
    }

    function makeAvatar(name) {
        const f = FACTIONS[factionOf(name)];
        const initial = (name[0] || '?').toUpperCase();
        const svg =
            `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>` +
            `<defs><radialGradient id='g' cx='35%' cy='30%' r='80%'>` +
            `<stop offset='0%' stop-color='${f.c1}'/>` +
            `<stop offset='100%' stop-color='${f.c2}'/></radialGradient></defs>` +
            `<rect width='100' height='100' rx='50' fill='url(#g)'/>` +
            `<circle cx='50' cy='50' r='46' fill='none' stroke='rgba(255,245,220,0.5)' stroke-width='1.5'/>` +
            `<text x='50' y='52' font-family='Georgia, serif' font-size='46' fill='#fff5e1' ` +
            `text-anchor='middle' dominant-baseline='central'>${initial}</text></svg>`;
        return 'data:image/svg+xml,' + encodeURIComponent(svg);
    }

    /* ---------------- Load characters ---------------- */
    fetch('/api/characters')
        .then(r => r.json())
        .then(characters => {
            allCharacters = characters;
            soulCount.textContent = characters.length;
            renderContacts();
        })
        .catch(() => {
            contactsList.innerHTML = '<div class="no-results">The court is silent. Could not reach the souls.</div>';
        });

    function renderContacts() {
        const term = searchTerm.toLowerCase();
        let list = allCharacters.filter(c => {
            const matchFaction = activeFaction === 'all' || factionOf(c.name) === activeFaction;
            const matchSearch = c.name.toLowerCase().includes(term);
            return matchFaction && matchSearch;
        });

        contactsList.innerHTML = '';
        if (list.length === 0) {
            contactsList.innerHTML = '<div class="no-results">No soul answers to that name.</div>';
            return;
        }

        // Group by faction when showing all
        if (activeFaction === 'all' && term === '') {
            Object.keys(FACTIONS).forEach(fk => {
                const group = list.filter(c => factionOf(c.name) === fk);
                if (group.length === 0) return;
                const label = document.createElement('div');
                label.className = 'section-label';
                label.textContent = FACTIONS[fk].label;
                contactsList.appendChild(label);
                group.forEach(c => contactsList.appendChild(buildContact(c)));
            });
        } else {
            list.forEach(c => contactsList.appendChild(buildContact(c)));
        }
    }

    function buildContact(char) {
        const f = FACTIONS[factionOf(char.name)];
        const item = document.createElement('div');
        item.className = 'contact-item';
        item.dataset.name = char.name;
        if (currentCharacter && currentCharacter.name === char.name) item.classList.add('active');
        item.innerHTML = `
            <div class="avatar-wrap">
                <img src="${makeAvatar(char.name)}" alt="${char.name}" class="avatar">
                <span class="faction-badge" style="background:${f.c2}">
                    <i class="fas ${f.icon}"></i>
                </span>
            </div>
            <div class="contact-details">
                <div class="contact-name">${char.name}</div>
                <div class="contact-epithet">${EPITHETS[char.name] || char.traits.split(',')[0]}</div>
            </div>`;
        item.addEventListener('click', () => selectCharacter(char, item));
        return item;
    }

    /* ---------------- Filters & search ---------------- */
    factionFilters.addEventListener('click', e => {
        const chip = e.target.closest('.faction-chip');
        if (!chip) return;
        document.querySelectorAll('.faction-chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        activeFaction = chip.dataset.faction;
        renderContacts();
    });

    searchInput.addEventListener('input', e => {
        searchTerm = e.target.value.trim();
        renderContacts();
    });

    /* ---------------- Select a character ---------------- */
    function selectCharacter(char, element) {
        document.querySelectorAll('.contact-item').forEach(el => el.classList.remove('active'));
        if (element) element.classList.add('active');

        currentCharacter = char;
        headerName.textContent = char.name;
        headerStatus.textContent = EPITHETS[char.name] || char.traits.split(',')[0];
        headerAvatar.src = makeAvatar(char.name);
        headerAvatarWrap.classList.remove('hidden');

        inputArea.classList.remove('hidden');
        infoBtn.classList.remove('hidden');
        clearBtn.classList.remove('hidden');

        if (window.innerWidth <= 820) sidebar.classList.add('mobile-hidden');

        loadHistory(char.name);
        messageInput.focus();
    }

    backBtn.addEventListener('click', () => sidebar.classList.remove('mobile-hidden'));

    /* ---------------- History ---------------- */
    function loadHistory(charName) {
        messagesContainer.innerHTML = '';
        fetch(`/api/history?character=${encodeURIComponent(charName)}&user_id=${userId}`)
            .then(res => res.json())
            .then(history => {
                if (!history || history.length === 0) {
                    showGreeting(charName);
                    showPrashnas();
                } else {
                    hidePrashnas();
                    history.forEach(msg =>
                        appendMessage(msg.role === 'user' ? 'sent' : 'received', msg.content));
                }
                scrollToBottom();
            });
    }

    function showGreeting(charName) {
        const f = FACTIONS[factionOf(charName)];
        messagesContainer.innerHTML = `
            <div class="empty-state">
                <div class="chakra"><i class="fas ${f.icon}"></i></div>
                <h2>${charName}</h2>
                <p class="empty-tagline">${EPITHETS[charName] || ''}<br>
                The ${f.label.toLowerCase()} stir. Ask, and ${charName} shall answer in the first person.</p>
            </div>`;
    }

    /* ---------------- Suggested questions ---------------- */
    function showPrashnas() {
        prashnaBar.innerHTML = '';
        PRASHNAS.forEach(q => {
            const chip = document.createElement('button');
            chip.className = 'prashna-chip';
            chip.textContent = q;
            chip.addEventListener('click', () => { messageInput.value = q; sendMessage(); });
            prashnaBar.appendChild(chip);
        });
        prashnaBar.classList.remove('hidden');
    }

    function hidePrashnas() { prashnaBar.classList.add('hidden'); }

    /* ---------------- Send message ---------------- */
    function sendMessage() {
        const text = messageInput.value.trim();
        if (!text || !currentCharacter) return;
        messageInput.value = '';
        hidePrashnas();

        appendMessage('sent', text);
        scrollToBottom();

        const typingEl = showTyping(currentCharacter.name);
        scrollToBottom();

        fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ character: currentCharacter.name, message: text, user_id: userId })
        })
            .then(res => res.json())
            .then(data => {
                removeTyping(typingEl);
                if (data.error) {
                    appendMessage('received', 'A silence falls... (' + data.error + ')');
                } else {
                    appendMessage('received', data.response, data.sources);
                }
                scrollToBottom();
            })
            .catch(() => {
                removeTyping(typingEl);
                appendMessage('received', 'The connection across time was lost. Speak again.');
                scrollToBottom();
            });
    }

    /* ---------------- Append / typing ---------------- */
    function appendMessage(type, text, sources) {
        const empty = messagesContainer.querySelector('.empty-state');
        if (empty) empty.remove();

        const div = document.createElement('div');
        div.className = `message ${type}`;
        const p = document.createElement('p');
        p.textContent = text;
        div.appendChild(p);

        if (sources && sources.length) {
            const src = document.createElement('div');
            src.className = 'message-sources';
            src.innerHTML = `<i class="fas fa-book-open"></i> Drawn from: ` +
                sources.map(s => `<span>${s}</span>`).join('');
            div.appendChild(src);
        }

        const time = document.createElement('span');
        time.className = 'message-time';
        time.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        div.appendChild(time);
        messagesContainer.appendChild(div);
    }

    function showTyping(name) {
        const div = document.createElement('div');
        div.className = 'message received typing';
        div.innerHTML = `<span>${name} is contemplating</span>
            <span class="contemplating-dots"><span></span><span></span><span></span></span>`;
        messagesContainer.appendChild(div);
        return div;
    }

    function removeTyping(el) { if (el && el.parentNode) el.remove(); }

    function scrollToBottom() { messagesContainer.scrollTop = messagesContainer.scrollHeight; }

    /* ---------------- Bio panel ---------------- */
    infoBtn.addEventListener('click', () => {
        if (!currentCharacter) return;
        const c = currentCharacter;
        const f = FACTIONS[factionOf(c.name)];
        document.getElementById('bio-avatar').src = makeAvatar(c.name);
        document.getElementById('bio-name').textContent = c.name;
        document.getElementById('bio-epithet').textContent = EPITHETS[c.name] || '';
        const factionEl = document.getElementById('bio-faction');
        factionEl.textContent = f.label;
        factionEl.style.background = f.c2;
        document.getElementById('bio-traits').textContent = c.traits || '—';
        document.getElementById('bio-style').textContent = c.style || '—';
        document.getElementById('bio-values').textContent = c.values || '—';
        bioOverlay.classList.remove('hidden');
    });

    bioClose.addEventListener('click', () => bioOverlay.classList.add('hidden'));
    bioOverlay.addEventListener('click', e => {
        if (e.target === bioOverlay) bioOverlay.classList.add('hidden');
    });

    /* ---------------- Clear history ---------------- */
    clearBtn.addEventListener('click', () => {
        if (!currentCharacter) return;
        if (!confirm(`Let ${currentCharacter.name} forget all that has passed between you?`)) return;
        fetch('/api/clear_history', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ character: currentCharacter.name, user_id: userId })
        })
            .then(res => res.json())
            .then(data => {
                if (data.message) loadHistory(currentCharacter.name);
                else alert('Could not clear the memory: ' + (data.error || 'unknown'));
            })
            .catch(() => alert('A silence falls while clearing memory.'));
    });

    /* ---------------- Input events ---------------- */
    sendBtn.addEventListener('click', sendMessage);
    messageInput.addEventListener('keypress', e => { if (e.key === 'Enter') sendMessage(); });

    /* ---------------- Rotating shloka on landing ---------------- */
    const shlokaBox = document.getElementById('shloka');
    if (shlokaBox) {
        const textEl = shlokaBox.querySelector('.shloka-text');
        const citeEl = shlokaBox.querySelector('.shloka-cite');
        let i = 0;
        function showShloka() {
            textEl.style.opacity = 0;
            setTimeout(() => {
                textEl.textContent = '"' + SHLOKAS[i][0] + '"';
                citeEl.textContent = '— ' + SHLOKAS[i][1];
                textEl.style.opacity = 1;
                i = (i + 1) % SHLOKAS.length;
            }, 600);
        }
        showShloka();
        setInterval(showShloka, 6000);
    }
});
