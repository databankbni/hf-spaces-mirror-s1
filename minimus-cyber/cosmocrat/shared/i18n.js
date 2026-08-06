// Weltkrieg i18n engine — minimal, no dependencies
// Usage:
//   <span data-i18n="key"></span>
//   const text = L('key', 'fallback');

window.L = {};
window.WELT_LANG = 'en';

async function loadLocale(lang) {
  const supported = ['it', 'en'];
  const target = supported.includes(lang) ? lang : 'en';
  try {
    const res = await fetch(`../locales/${target}.json`);
    if (!res.ok) throw new Error('locale fetch failed');
    window.L = await res.json();
    window.WELT_LANG = target;
    document.documentElement.lang = target;
    applyTranslations();
  } catch(e) {
    console.warn('Locale load failed, using fallback:', e);
  }
}

function applyTranslations(root) {
  (root || document).querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    if (window.L[key]) {
      if (el.tagName === 'INPUT' && el.type !== 'submit') el.placeholder = window.L[key];
      else el.textContent = window.L[key];
    }
  });
  (root || document).querySelectorAll('[data-i18n-attr]').forEach(el => {
    const spec = el.dataset.i18nAttr; // "title:keyName,placeholder:keyName2"
    spec.split(',').forEach(pair => {
      const [attr, key] = pair.split(':').map(s => s.trim());
      if (window.L[key]) el.setAttribute(attr, window.L[key]);
    });
  });
}

function t(key, fallback) {
  return window.L[key] || fallback || key;
}

function detectBrowserLang() {
  let saved = null;
  try { saved = localStorage.getItem('weltkrieg.lang'); } catch(e) {}
  if (saved) return saved;
  return (navigator.language || 'en').split('-')[0];
}

window.weltkriegI18n = { loadLocale, applyTranslations, t, detectBrowserLang };
