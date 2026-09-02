(() => {
  'use strict';
  const root = document.querySelector('[data-billing-root]');
  if (!root) return;
  const api = (window.CLIMAFLORA_RUNTIME?.apiBase || window.CLIMAFLORA_CONFIG?.apiBase || '').replace(/\/$/, '');
  const status = document.getElementById('billing-status');
  const buttons = [...document.querySelectorAll('[data-checkout-plan]')];
  const interval = document.getElementById('billing-annual');
  const legalTerms = document.getElementById('legal-terms');
  const legalStart = document.getElementById('legal-start');

  function token() {
    return window.CLIMAFLORA_AUTH?.accessToken || '';
  }
  function message(text, error = false) {
    status.textContent = text;
    status.classList.toggle('error', error);
    status.hidden = false;
  }
  async function post(path, body) {
    const accessToken = token();
    if (!accessToken) throw new Error('Connectez-vous à ClimaFlora avant de choisir une offre.');
    const response = await fetch(`${api}/billing/${path}`, {
      method: 'POST',
      headers: {'Authorization': `Bearer ${accessToken}`, 'Content-Type': 'application/json'},
      body: body ? JSON.stringify(body) : undefined
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || 'Le service de paiement est momentanément indisponible.');
    return payload;
  }
  buttons.forEach(button => button.addEventListener('click', async () => {
    if (!legalTerms?.checked || !legalStart?.checked) {
      message('Veuillez accepter les CGV et confirmer la demande d’accès immédiat avant de poursuivre.', true);
      document.querySelector('.legal-consent-box')?.scrollIntoView({behavior:'smooth', block:'center'});
      return;
    }
    buttons.forEach(item => item.disabled = true);
    message('Ouverture du paiement sécurisé…');
    try {
      const result = await post('checkout', {
        plan: button.dataset.checkoutPlan,
        interval: interval.checked ? 'yearly' : 'monthly',
        legal_version: '2026-08-24',
        terms_accepted: true,
        immediate_service_requested: true
      });
      window.location.assign(result.url);
    } catch (error) {
      message(error.message, true);
      buttons.forEach(item => item.disabled = false);
    }
  }));
  interval.addEventListener('change', () => {
    document.querySelectorAll('[data-price-monthly]').forEach(node => node.hidden = interval.checked);
    document.querySelectorAll('[data-price-yearly]').forEach(node => node.hidden = !interval.checked);
  });
  const query = new URLSearchParams(location.search).get('checkout');
  if (query === 'success') message('Abonnement confirmé. Vos droits seront actualisés dans quelques secondes.');
  if (query === 'cancel') message('Paiement annulé : aucun changement n’a été appliqué.');
  document.getElementById('subscription-cancel')?.addEventListener('click', async () => {
    try {
      message('Ouverture du portail sécurisé…');
      window.location.assign((await post('portal')).url);
    } catch (error) { message(error.message, true); }
  });
})();
