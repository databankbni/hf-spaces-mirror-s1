// Toggle Between Login and Register Forms (Yeh waisa hi rahega)
function toggleAuth() {
    const loginForm = document.getElementById('login-form');
    const regForm = document.getElementById('register-form');
    const title = document.getElementById('auth-title');
    const status = document.getElementById('auth-status');
    status.textContent = "";

    if (loginForm.style.display === 'none') {
        loginForm.style.display = 'block';
        regForm.style.display = 'none';
        title.textContent = 'System Login';
    } else {
        loginForm.style.display = 'none';
        regForm.style.display = 'block';
        title.textContent = 'New Profile Registration';
    }
}

// Unified Auth Function (Yeh bhi waisa hi rahega)
async function attemptAuth(action) {
    const isLogin = action === 'login';
    const usernameInput = document.getElementById(isLogin ? 'login-username' : 'reg-username');
    const pinInput = document.getElementById(isLogin ? 'login-pin' : 'reg-pin');
    const status = document.getElementById('auth-status');
    
    const username = usernameInput.value.trim();
    const pin = pinInput.value.trim();

    if (!username || !pin) {
        status.textContent = "ERROR: PLEASE FILL ALL FIELDS.";
        status.style.color = "#ff3366";
        return;
    }

    status.textContent = isLogin ? "Authenticating Neural Link..." : "Registering New Subject...";
    status.style.color = "var(--neon-blue)";
    
    const endpoint = isLogin ? '/login' : '/register';
    
    try {
        const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, pin })
        });
        const data = await res.json();
        
        if (data.success) {
            status.textContent = data.msg;
            status.style.color = "var(--neon-green)";
            if (isLogin) {
                setTimeout(() => window.location.href = '/dashboard', 800);
            } else {
                usernameInput.value = '';
                pinInput.value = '';
                setTimeout(() => toggleAuth(), 1500);
            }
        } else {
            status.textContent = data.msg;
            status.style.color = "#ff3366";
        }
    } catch (e) {
        status.textContent = "SYSTEM CONNECTION ERROR.";
        status.style.color = "#ff3366";
    }
}

// --- NAYA DATABASE PRACTICE ENGINE ---
let currentQIndex = 0;

// Agar questions variable (Practice Page par) maujood hai
if (typeof questions !== 'undefined' && questions.length > 0) {
    updateCounters();
    renderQuestion();
}

function updateCounters() {
    document.getElementById('attempted-count').innerText = currentQIndex;
    document.getElementById('remaining-count').innerText = questions.length - currentQIndex;
}

function renderQuestion() {
    if(currentQIndex >= questions.length) {
        document.getElementById('q-container').innerHTML = `
            <div style="text-align:center; padding: 3rem 0;">
                <div class="ai-orb" style="background:radial-gradient(circle, var(--neon-green), transparent); box-shadow:0 0 30px var(--neon-green);"></div>
                <h3 style="color: var(--neon-green); margin-bottom: 15px; font-size: 2rem;">Module Complete</h3>
                <p style="color: #aaa; margin-bottom: 2rem; font-family:'Rajdhani'; font-size:1.2rem;">XP and Accuracy have been securely saved to the Database.</p>
                <a href="/dashboard" class="btn-primary" style="width: auto;">Return to Dashboard</a>
            </div>
        `;
        return;
    }

    const q = questions[currentQIndex];
    const html = `
        <div style="display:flex; justify-content:space-between; margin-bottom:20px; border-bottom: 1px solid var(--glass-border); padding-bottom: 15px;">
            <span style="font-family:'Orbitron'; color:var(--neon-purple); letter-spacing: 2px;">QUERY 0${currentQIndex+1} / 0${questions.length}</span>
            <span style="color:#888; font-family:'Rajdhani'; font-size:1.1rem;">Complexity: <span style="color:var(--neon-blue); font-weight:bold;">${q.difficulty}</span></span>
        </div>
        <h3 style="font-size:1.6rem; margin-bottom: 2rem; line-height: 1.5; color: #fff;">${q.question_text}</h3>
        <div class="options-grid">
            <button class="option-btn" onclick="submitAns(${q.id}, 'A', this)"><span class="lbl">A</span> ${q.opt_a}</button>
            <button class="option-btn" onclick="submitAns(${q.id}, 'B', this)"><span class="lbl">B</span> ${q.opt_b}</button>
            <button class="option-btn" onclick="submitAns(${q.id}, 'C', this)"><span class="lbl">C</span> ${q.opt_c}</button>
            <button class="option-btn" onclick="submitAns(${q.id}, 'D', this)"><span class="lbl">D</span> ${q.opt_d}</button>
        </div>
    `;
    document.getElementById('q-container').innerHTML = html;
}

async function submitAns(qId, selectedOpt, btnElement) {
    const btns = document.querySelectorAll('.option-btn');
    btns.forEach(b => b.disabled = true); 

    const res = await fetch('/api/answer', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ question_id: qId, selected_option: selectedOpt })
    });
    const data = await res.json();

    if(data.correct) {
        btnElement.classList.add('correct');
        showToast(`Correct calculation! +${data.xp_earned} XP`);
    } else {
        btnElement.classList.add('wrong');
        btns.forEach(b => {
            if(b.innerHTML.includes(`<span class="lbl">${data.correct_option}</span>`)) {
                b.classList.add('correct'); 
            }
        });
        showToast(`Incorrect formulation. +${data.xp_earned} XP for effort.`);
    }

    if(data.new_badges && data.new_badges.length > 0) {
        data.new_badges.forEach(b => {
            setTimeout(() => showToast(`🏆 Achievement Unlocked: ${b}`), 500);
        });
    }

    setTimeout(() => {
        currentQIndex++;
        updateCounters(); 
        renderQuestion();
    }, 2500);
}

function showToast(msg) {
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = msg;
    document.getElementById('toast-container').appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 400);
    }, 3000);
}