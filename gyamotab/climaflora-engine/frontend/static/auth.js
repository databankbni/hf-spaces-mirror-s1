(() => {
  'use strict';
  const config = window.CLIMAFLORA_CONFIG || {};
  if (!config.supabaseUrl || !config.supabasePublishableKey || !window.supabase?.createClient) return;

  const client = window.supabase.createClient(config.supabaseUrl, config.supabasePublishableKey, {
    auth: {persistSession: true, autoRefreshToken: true, detectSessionInUrl: true}
  });
  const state = {session: null, profile: null};
  const PLAN_COPY = {
    FREE: ['Recherche climatique et pédologique', 'Résultats scientifiques', '1 projet et 1 site sauvegardés'],
    PLUS: ['10 projets et 5 sites', 'Horizons 2070 et 2100', 'Palette et comparaison de 5 plantes', '10 exports par mois'],
    PRO: ['250 projets et 50 sites', 'Comparaison de 20 plantes', '100 exports avancés par mois', 'Usage dans les projets clients']
  };

  const shell = document.createElement('div');
  shell.innerHTML = `<div class="auth-backdrop" data-auth-close hidden></div>
    <section class="auth-dialog" role="dialog" aria-modal="true" aria-labelledby="auth-title" hidden>
      <button class="auth-close" data-auth-close aria-label="Fermer" type="button">×</button>
      <div data-auth-guest>
        <p class="auth-kicker">Compte ClimaFlora</p><h2 id="auth-title">Se connecter</h2>
        <p class="auth-copy">Retrouvez vos projets et choisissez une offre avec la même adresse e-mail.</p>
        <form data-auth-form>
          <label>Adresse e-mail<input name="email" type="email" autocomplete="email" required></label>
          <label>Mot de passe<input name="password" type="password" autocomplete="current-password" minlength="8" required></label>
          <div class="auth-actions"><button class="auth-primary" name="action" value="signin">Connexion</button><button name="action" value="signup">Créer mon compte</button></div>
        </form>
        <div class="auth-sostagora"><span>Déjà client Sostagora&nbsp;?</span><a class="auth-primary" data-sostagora-login href="#">Activer ClimaFlora Plus</a></div>
      </div>
      <div data-auth-user hidden>
        <p class="auth-kicker">Mon compte</p><h2>Bonjour</h2><p data-auth-email></p>
        <div class="auth-plan"><span>Accès actuel</span><strong data-auth-plan>Découverte</strong></div>
        <ul class="auth-benefits" data-auth-benefits></ul>
        <div class="auth-actions"><a class="auth-primary" data-auth-offers href="tarifs.html">Voir les offres</a><button data-auth-portal type="button" hidden>Gérer l’abonnement</button><button class="auth-admin-button" data-auth-admin-open type="button" hidden>Administration</button><button data-auth-signout type="button">Déconnexion</button></div>
      </div>
      <p class="auth-status" data-auth-status role="status" aria-live="polite" hidden></p>
    </section>`;
  document.body.append(...shell.children);

  const dialog = document.querySelector('.auth-dialog');
  const backdrop = document.querySelector('.auth-backdrop');
  const guest = dialog.querySelector('[data-auth-guest]');
  const userPanel = dialog.querySelector('[data-auth-user]');
  const status = dialog.querySelector('[data-auth-status]');
  const apiBase = () => (window.CLIMAFLORA_RUNTIME?.apiBase || config.apiBase || '').replace(/\/$/, '');
  dialog.querySelector('[data-sostagora-login]').href = config.sostagoraLoginUrl || 'https://shugoan.com/';

  function showStatus(text, isError = false) {
    status.textContent = text; status.hidden = !text; status.classList.toggle('error', isError);
  }
  function open() { dialog.hidden = false; backdrop.hidden = false; document.body.classList.add('auth-open'); dialog.querySelector('input')?.focus(); }
  function close() { dialog.hidden = true; backdrop.hidden = true; document.body.classList.remove('auth-open'); showStatus(''); }
  function normalizedRole() { return String(state.profile?.role || 'USER').toUpperCase(); }
  function normalizedPlan() { return String(state.profile?.plan || 'FREE').toUpperCase(); }
  function confirmationRedirect() { return new URL('./', location.href).href.split(/[?#]/)[0]; }
  async function loadOwnProfile() {
    if (!state.session?.user?.id) return null;
    const {data, error} = await client
      .from('climaflora_profiles')
      .select('id,role,plan,first_name,last_name,display_name,billing_status,billing_interval,current_period_end,cancel_at_period_end')
      .eq('id', state.session.user.id)
      .maybeSingle();
    if (error) throw error;
    return data || null;
  }
  async function loadBilling() {
    state.profile = null;
    if (!state.session?.access_token) return render();
    const [profileResult, billingResult, entitlementResult] = await Promise.allSettled([
      loadOwnProfile(),
      fetch(`${apiBase()}/billing/me`, {headers: {Authorization: `Bearer ${state.session.access_token}`}})
        .then(response => response.ok ? response.json() : null),
      client.rpc('climaflora_my_entitlements')
    ]);
    const ownProfile = profileResult.status === 'fulfilled' ? profileResult.value : null;
    const billing = billingResult.status === 'fulfilled' ? billingResult.value : null;
    const databaseEntitlements = entitlementResult.status === 'fulfilled' ? entitlementResult.value?.data : null;
    const role = String(ownProfile?.role || 'USER').toUpperCase();
    const plan = String(databaseEntitlements?.plan || (role === 'ADMIN' ? 'PRO' : '') || billing?.plan || ownProfile?.plan || 'FREE').toUpperCase();
    state.profile = ownProfile || billing ? {
      ...(ownProfile || {}), ...(billing || {}), role, plan,
      entitlements: databaseEntitlements || billing?.entitlements || null
    } : null;
    render();
  }
  function render() {
    const signedIn = Boolean(state.session?.user);
    guest.hidden = signedIn; userPanel.hidden = !signedIn;
    document.querySelectorAll('[data-auth-open]').forEach(button => {
      button.disabled = false;
      button.textContent = signedIn ? 'Mon compte' : 'Connexion';
    });
    if (!signedIn) {
      window.dispatchEvent(new CustomEvent('climaflora:auth-changed', {detail:{authenticated:false, profile:null, role:'USER', plan:'FREE'}}));
      return;
    }
    userPanel.querySelector('[data-auth-email]').textContent = state.session.user.email || '';
    const plan = normalizedPlan();
    userPanel.querySelector('[data-auth-plan]').textContent = normalizedRole() === 'ADMIN'
      ? `${{PLUS:'Plus', PRO:'Pro'}[plan] || 'Découverte'} · administrateur`
      : ({PLUS:'Plus', PRO:'Pro'}[plan] || 'Découverte');
    userPanel.querySelector('[data-auth-benefits]').innerHTML = (PLAN_COPY[plan] || PLAN_COPY.FREE).map(item => `<li>${adminEsc(item)}</li>`).join('');
    userPanel.querySelector('[data-auth-offers]').hidden = plan !== 'FREE';
    userPanel.querySelector('[data-auth-portal]').hidden = state.profile?.subscription_management !== 'stripe';
    userPanel.querySelector('[data-auth-admin-open]').hidden = normalizedRole() !== 'ADMIN';
    window.dispatchEvent(new CustomEvent('climaflora:auth-changed', {detail:{authenticated:true, profile:state.profile, role:normalizedRole(), plan:normalizedPlan()}}));
  }

  function adminDate(value) {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '—' : date.toLocaleDateString('fr-FR');
  }
  function adminEsc(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  }
  async function loadAdminUsers(overlay) {
    const body = overlay.querySelector('[data-auth-admin-body]');
    body.innerHTML = '<p>Chargement des comptes…</p>';
    const {data, error} = await client.rpc('climaflora_admin_users');
    if (error) throw error;
    const users = Array.isArray(data) ? data : [];
    body.innerHTML = users.length ? `<div class="auth-admin-count">${users.length} compte${users.length > 1 ? 's' : ''}</div><div class="auth-admin-table-wrap"><table class="auth-admin-table"><thead><tr><th>Utilisateur</th><th>Email</th><th>Rôle</th><th>Plan</th><th>Paiement</th><th>Créé</th></tr></thead><tbody>${users.map(user => `<tr><td>${adminEsc([user.first_name,user.last_name].filter(Boolean).join(' ') || '—')}</td><td>${adminEsc(user.email || '')}</td><td>${adminEsc(user.role || 'USER')}</td><td><select data-admin-user="${adminEsc(user.id)}" data-previous="${adminEsc(user.plan || 'FREE')}">${['FREE','PLUS','PRO'].map(plan => `<option value="${plan}" ${user.plan === plan ? 'selected' : ''}>${plan}</option>`).join('')}</select></td><td>${adminEsc(user.billing_status || '—')}</td><td>${adminEsc(adminDate(user.created_at))}</td></tr>`).join('')}</tbody></table></div>` : '<p>Aucun compte utilisateur.</p>';
    body.querySelectorAll('[data-admin-user]').forEach(select => select.addEventListener('change', async () => {
      const previous = select.dataset.previous || 'FREE';
      select.disabled = true;
      const {error: updateError} = await client.rpc('climaflora_admin_set_plan', {p_user_id:select.dataset.adminUser, p_plan:select.value});
      if (updateError) {
        select.value = previous;
        alert(`Modification refusée : ${updateError.message}`);
      } else {
        select.dataset.previous = select.value;
      }
      select.disabled = false;
    }));
  }
  function openAdmin() {
    if (normalizedRole() !== 'ADMIN') return;
    let overlay = document.querySelector('.auth-admin-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.className = 'auth-admin-overlay';
      overlay.innerHTML = `<section class="auth-admin-panel" role="dialog" aria-modal="true" aria-labelledby="auth-admin-title"><div class="auth-admin-head"><div><p class="auth-kicker">ClimaFlora</p><h2 id="auth-admin-title">Administration</h2></div><button data-auth-admin-close aria-label="Fermer" type="button">×</button></div><div data-auth-admin-body></div></section>`;
      document.body.appendChild(overlay);
      overlay.querySelector('[data-auth-admin-close]').addEventListener('click', () => { overlay.hidden = true; });
      overlay.addEventListener('click', event => { if (event.target === overlay) overlay.hidden = true; });
    }
    overlay.hidden = false;
    loadAdminUsers(overlay).catch(error => {
      overlay.querySelector('[data-auth-admin-body]').innerHTML = `<p class="auth-admin-error">${adminEsc(error.message || 'Accès refusé.')}</p>`;
    });
  }
  async function billingPost(path) {
    const response = await fetch(`${apiBase()}/billing/${path}`, {method:'POST', headers:{Authorization:`Bearer ${state.session.access_token}`}});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || 'Service momentanément indisponible.');
    return payload;
  }
  async function handleSostagoraLogin() {
    const url = new URL(location.href);
    const code = url.searchParams.get('sostagora_code');
    const result = url.searchParams.get('sostagora');
    if (code) {
      url.searchParams.delete('sostagora_code');
      history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
      open(); showStatus('Activation de votre accès Sostagora…');
      try {
        const response = await fetch(`${apiBase()}/auth/sostagora/exchange`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({code})
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.url) throw new Error(payload.detail || 'Connexion Sostagora impossible.');
        location.assign(payload.url);
      } catch (error) {
        showStatus(error.message, true);
      }
      return;
    }
    if (result === 'success') {
      url.searchParams.delete('sostagora');
      history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
      open(); showStatus('Votre accès ClimaFlora Plus est activé.');
    } else if (result === 'forbidden') {
      url.searchParams.delete('sostagora');
      history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
      open(); showStatus('Aucun accès client Sostagora actif n’a été trouvé.', true);
    }
  }

  document.addEventListener('click', event => { if (event.target.closest('[data-auth-open]')) open(); });
  document.querySelectorAll('[data-auth-close]').forEach(node => node.addEventListener('click', close));
  dialog.querySelector('[data-auth-signout]').addEventListener('click', async () => { await client.auth.signOut(); close(); });
  dialog.querySelector('[data-auth-admin-open]').addEventListener('click', openAdmin);
  dialog.querySelector('[data-auth-portal]').addEventListener('click', async () => {
    showStatus('Ouverture du portail sécurisé…');
    try { location.assign((await billingPost('portal')).url); } catch (error) { showStatus(error.message, true); }
  });
  dialog.querySelector('[data-auth-form]').addEventListener('submit', async event => {
    event.preventDefault();
    const submitter = event.submitter?.value || 'signin';
    const data = new FormData(event.currentTarget);
    const credentials = {email: String(data.get('email')).trim(), password: String(data.get('password'))};
    showStatus(submitter === 'signup' ? 'Création du compte…' : 'Connexion…');
    const result = submitter === 'signup'
      ? await client.auth.signUp({...credentials, options:{emailRedirectTo:confirmationRedirect()}})
      : await client.auth.signInWithPassword(credentials);
    if (result.error) return showStatus(result.error.message, true);
    if (submitter === 'signup' && !result.data.session) showStatus('Compte créé. Consultez votre e-mail pour confirmer votre adresse.');
    else { showStatus('Connexion réussie.'); await loadBilling(); }
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !dialog.hidden) close(); });

  window.CLIMAFLORA_AUTH = {
    client,
    get accessToken() { return state.session?.access_token || ''; },
    get session() { return state.session; },
    get authenticated() { return Boolean(state.session?.user); },
    get profile() { return state.profile; },
    get plan() { return normalizedPlan(); },
    get role() { return normalizedRole(); },
    get isAdmin() { return normalizedRole() === 'ADMIN'; },
    get entitlements() { return state.profile?.entitlements || null; },
    reloadProfile: loadBilling,
    open
  };
  client.auth.onAuthStateChange((_event, session) => {
    state.session = session;
    setTimeout(loadBilling, 0);
  });
  client.auth.getSession().then(({data}) => { state.session = data.session; loadBilling(); });
  handleSostagoraLogin();
})();
