/**
 * iFreight Jamaica - Interactive Frontend Logic & Systems
 */

const IFJ_APP = {
  activeCurrency: 'JMD', // 'JMD' or 'USD'
  fxRate: 156.00, // 1 USD = 156 JMD

  init() {
    this.renderSteps();
    this.renderServices();
    this.renderRatesTable();
    this.renderFAQ();
    this.initTestimonials();
    this.initCalculator();
    this.initTracking();
    this.initAddressGenerator();
    this.initNavScroll();
    this.initStatsObserver();
    this.bindEvents();
  },

  bindEvents() {
    // Mobile menu triggers
    const burger = document.getElementById('ifjBurgerBtn');
    const closeBtn = document.getElementById('mobileMenuCloseBtn');
    if (burger) burger.addEventListener('click', () => this.toggleMobileMenu(true));
    if (closeBtn) closeBtn.addEventListener('click', () => this.toggleMobileMenu(false));

    // Currency selector toggles in calculator
    document.querySelectorAll('[data-currency-btn]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const cur = e.target.getAttribute('data-currency-btn');
        this.setCurrency(cur);
      });
    });
  },

  setCurrency(cur) {
    this.activeCurrency = cur;
    document.querySelectorAll('[data-currency-btn]').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-currency-btn') === cur);
    });
    this.calculateFreight();
  },

  /* ================= CALCULATOR SYSTEM ================= */
  initCalculator() {
    const calcForm = document.getElementById('freightCalcForm');
    if (!calcForm) return;

    ['calcWeight', 'calcLength', 'calcWidth', 'calcHeight', 'calcItemValue', 'calcFreightType'].forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener('input', () => this.calculateFreight());
        el.addEventListener('change', () => this.calculateFreight());
      }
    });

    this.calculateFreight();
  },

  calculateFreight() {
    const type = document.getElementById('calcFreightType')?.value || 'air';
    const actualWeightLbs = parseFloat(document.getElementById('calcWeight')?.value || '1');
    const length = parseFloat(document.getElementById('calcLength')?.value || '0');
    const width = parseFloat(document.getElementById('calcWidth')?.value || '0');
    const height = parseFloat(document.getElementById('calcHeight')?.value || '0');
    const itemValueUSD = parseFloat(document.getElementById('calcItemValue')?.value || '50');

    // Dimensional Volumetric Weight = (L * W * H) / 166 (Industry standard for Air Cargo)
    let dimensionalWeightLbs = 0;
    if (length > 0 && width > 0 && height > 0) {
      dimensionalWeightLbs = Math.round(((length * width * height) / 166) * 10) / 10;
    }

    const chargeableWeight = Math.max(actualWeightLbs, dimensionalWeightLbs);

    let baseFreightUSD = 0;
    let baseFreightJMD = 0;
    let transitTime = "2–5 Business Days";

    if (type === 'air') {
      transitTime = "2–5 Business Days";
      // Lookup rate or calculate bracketed rate
      if (chargeableWeight <= 1) {
        baseFreightUSD = 6.25;
        baseFreightJMD = 974.58;
      } else if (chargeableWeight <= 2) {
        baseFreightUSD = 8.90;
        baseFreightJMD = 1389.69;
      } else if (chargeableWeight <= 5) {
        baseFreightUSD = 8.90 + ((chargeableWeight - 2) * 2.30);
        baseFreightJMD = baseFreightUSD * this.fxRate;
      } else if (chargeableWeight <= 10) {
        baseFreightUSD = 15.80 + ((chargeableWeight - 5) * 2.51);
        baseFreightJMD = baseFreightUSD * this.fxRate;
      } else {
        baseFreightUSD = 28.35 + ((chargeableWeight - 10) * 2.15);
        baseFreightJMD = baseFreightUSD * this.fxRate;
      }
    } else if (type === 'ocean_barrel') {
      transitTime = "10–14 Days";
      baseFreightUSD = 85.00;
      baseFreightJMD = 13260.00;
    } else if (type === 'ocean_cft') {
      transitTime = "10–14 Days";
      const cft = Math.max(1, (length * width * height) / 1728);
      baseFreightUSD = Math.max(45.00, cft * 6.50);
      baseFreightJMD = baseFreightUSD * this.fxRate;
    }

    // Customs calculations (Jamaica $100 USD duty free threshold)
    let dutyEstimateUSD = 0;
    let dutyStatusText = "";
    if (itemValueUSD <= 100) {
      dutyEstimateUSD = 0;
      dutyStatusText = "DUTY-FREE ($0.00) • Value under $100 USD threshold";
    } else {
      // Average 20% tariff + 15% GCT on CIF for items over $100
      const taxableValue = itemValueUSD + baseFreightUSD;
      dutyEstimateUSD = Math.round(taxableValue * 0.28 * 100) / 100;
      dutyStatusText = `Estimated JCA Duties & GCT (15%): ~$${dutyEstimateUSD.toFixed(2)} USD`;
    }

    const totalUSD = baseFreightUSD + dutyEstimateUSD;
    const totalJMD = Math.round(totalUSD * this.fxRate);

    // Update DOM elements
    const resFreight = document.getElementById('calcResFreight');
    const resDuty = document.getElementById('calcResDuty');
    const resTotal = document.getElementById('calcResTotal');
    const resWeight = document.getElementById('calcResChargeableWeight');
    const resTransit = document.getElementById('calcResTransit');

    if (this.activeCurrency === 'JMD') {
      if (resFreight) resFreight.textContent = `J$${Math.round(baseFreightJMD).toLocaleString('en-US')}`;
      if (resDuty) resDuty.textContent = dutyEstimateUSD === 0 ? 'J$0 (Free)' : `J$${Math.round(dutyEstimateUSD * this.fxRate).toLocaleString('en-US')}`;
      if (resTotal) resTotal.textContent = `J$${totalJMD.toLocaleString('en-US')}`;
    } else {
      if (resFreight) resFreight.textContent = `$${baseFreightUSD.toFixed(2)} USD`;
      if (resDuty) resDuty.textContent = dutyEstimateUSD === 0 ? '$0.00 (Free)' : `$${dutyEstimateUSD.toFixed(2)} USD`;
      if (resTotal) resTotal.textContent = `$${totalUSD.toFixed(2)} USD`;
    }

    if (resWeight) resWeight.textContent = `${chargeableWeight} lbs ${dimensionalWeightLbs > actualWeightLbs ? '(Dimensional)' : '(Actual)'}`;
    if (resTransit) resTransit.textContent = transitTime;

    const dutyBadge = document.getElementById('calcDutyBadge');
    if (dutyBadge) {
      dutyBadge.textContent = dutyStatusText;
      dutyBadge.className = itemValueUSD <= 100 ? 'duty-badge free' : 'duty-badge taxable';
    }
  },

  /* ================= TRACKING SYSTEM ================= */
  initTracking() {
    const btn = document.getElementById('btnLookupTracking');
    const input = document.getElementById('trackingInput');

    if (btn && input) {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        this.trackPackage(input.value.trim());
      });

      input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          this.trackPackage(input.value.trim());
        }
      });
    }

    // Quick demo buttons
    document.querySelectorAll('[data-demo-track]').forEach(pill => {
      pill.addEventListener('click', () => {
        const num = pill.getAttribute('data-demo-track');
        if (input) input.value = num;
        this.trackPackage(num);
      });
    });
  },

  trackPackage(trackingNumber) {
    const cleanNum = (trackingNumber || '').toUpperCase();
    const resultBox = document.getElementById('trackingResultBox');
    if (!resultBox) return;

    if (!cleanNum) {
      this.showToast('Please enter a tracking number (e.g. IFJ-84920-AIR)');
      return;
    }

    // Check mock database or create live simulated tracking entry
    let data = IFREIGHT_DATA.mockTracking[cleanNum];
    if (!data) {
      data = {
        trackingNumber: cleanNum,
        status: "IN_TRANSIT",
        statusLabel: "In Transit to Jamaica",
        type: "Air Freight",
        weight: "2.8 lbs",
        shipper: "Verified US Merchant",
        destination: "Kingston Sort Hub",
        estimatedDelivery: "In 2 Days",
        timeline: [
          { time: "Today, 11:00 AM", title: "Customs Manifest Processed", location: "Miami Airport Hub (MIA)", completed: true },
          { time: "Yesterday, 03:30 PM", title: "Intake & X-Ray Scanning Verified", location: "Doral Warehouse, FL", completed: true },
          { time: "Pending", title: "Flight Arrival & Jamaica Customs Clearance", location: "Norman Manley KIN", completed: false },
          { time: "Pending", title: "Final Sorting / Ready for Pickup", location: "Kingston Hub", completed: false }
        ]
      };
    }

    resultBox.style.display = 'block';
    resultBox.innerHTML = `
      <div class="tracking-card-main">
        <div class="tracking-card-header">
          <div>
            <div class="tracking-ref-title">Tracking #${data.trackingNumber}</div>
            <div class="tracking-sub-meta">${data.type} • Weight: ${data.weight} • Shipper: ${data.shipper}</div>
          </div>
          <div class="tracking-status-pill ${data.status.toLowerCase()}">
            <span class="pulse-dot"></span>
            <span>${data.statusLabel}</span>
          </div>
        </div>

        <div class="tracking-timeline-grid">
          ${data.timeline.map((step, idx) => `
            <div class="timeline-node ${step.completed ? 'completed' : 'pending'}">
              <div class="timeline-bullet">${step.completed ? '✓' : (idx + 1)}</div>
              <div class="timeline-details">
                <div class="timeline-title">${step.title}</div>
                <div class="timeline-location">${step.location}</div>
                <div class="timeline-time">${step.time}</div>
              </div>
            </div>
          `).join('')}
        </div>

        <div class="tracking-card-footer">
          <div>
            <span class="footer-label">Destination Depot:</span>
            <strong>${data.destination}</strong>
          </div>
          <div>
            <span class="footer-label">Estimated Delivery:</span>
            <strong class="highlight-date">${data.estimatedDelivery}</strong>
          </div>
        </div>
      </div>
    `;

    resultBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  },

  /* ================= US ADDRESS GENERATOR ================= */
  initAddressGenerator() {
    let memberCode = localStorage.getItem('ifj_member_code');
    if (!memberCode) {
      memberCode = 'IFJ-' + Math.floor(1000 + Math.random() * 9000);
      localStorage.setItem('ifj_member_code', memberCode);
    }

    const codeEl = document.getElementById('userMemberCodeDisplay');
    const suiteEl = document.getElementById('addressSuiteDisplay');
    if (codeEl) codeEl.textContent = memberCode;
    if (suiteEl) suiteEl.textContent = `Suite 100 / ${memberCode}`;

    // Bind copy buttons
    document.querySelectorAll('[data-copy-text]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const textToCopy = btn.getAttribute('data-copy-text');
        navigator.clipboard.writeText(textToCopy).then(() => {
          const original = btn.innerHTML;
          btn.innerHTML = `<span>✓ Copied!</span>`;
          btn.classList.add('copied');
          setTimeout(() => {
            btn.innerHTML = original;
            btn.classList.remove('copied');
          }, 1800);
        });
      });
    });
  },

  /* ================= RENDERING DATA ================= */
  renderSteps() {
    const container = document.getElementById('stepsGrid');
    if (!container) return;
    container.innerHTML = IFREIGHT_DATA.steps.map(s => `
      <div class="ifj-step-col">
        <div class="ifj-step-num">${s.n}</div>
        <h4 class="ifj-step-title">${s.title}</h4>
        <p class="ifj-step-desc">${s.desc}</p>
      </div>
    `).join('');
  },

  renderServices() {
    const container = document.getElementById('servicesGrid');
    if (!container) return;
    container.innerHTML = IFREIGHT_DATA.services.map(s => `
      <div class="ifj-card service-card">
        <div class="service-icon-wrap">${s.icon}</div>
        <span class="service-tag-pill">${s.tag}</span>
        <h3 class="service-title">${s.title}</h3>
        <p class="service-desc">${s.desc}</p>
        <div class="service-footer-row">
          <a href="#calculator" class="service-calc-link">Calculate Rate →</a>
          <span class="service-arrow-circle">→</span>
        </div>
      </div>
    `).join('');
  },

  renderRatesTable() {
    const container = document.getElementById('ratesTable');
    if (!container) return;
    container.innerHTML = IFREIGHT_DATA.rates.map(r => `
      <div class="ifj-rate-row">
        <div class="rate-weight-group">
          <span class="rate-weight-badge">${r.weight}</span>
          <span class="rate-weight-unit">${r.unit}</span>
        </div>
        <div class="rate-prices-group">
          <span class="rate-price-jmd">J$${r.priceJMD.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
          <span class="rate-price-usd">≈ $${r.priceUSD.toFixed(2)} USD</span>
        </div>
      </div>
    `).join('');
  },

  renderFAQ() {
    const container = document.getElementById('faqContainer');
    if (!container) return;

    container.innerHTML = IFREIGHT_DATA.faqs.map((f, i) => `
      <div class="ifj-faq-item ${i === 0 ? 'active' : ''}">
        <button class="faq-toggle-btn" onclick="IFJ_APP.toggleFaq(${i})">
          <span class="faq-question">${f.q}</span>
          <span class="faq-icon-circle">${i === 0 ? '−' : '+'}</span>
        </button>
        <div class="faq-answer-panel" style="${i === 0 ? 'max-height: 260px; opacity: 1;' : 'max-height: 0; opacity: 0;'}">
          <p>${f.a}</p>
        </div>
      </div>
    `).join('');
  },

  toggleFaq(index) {
    const items = document.querySelectorAll('.ifj-faq-item');
    items.forEach((item, i) => {
      const panel = item.querySelector('.faq-answer-panel');
      const icon = item.querySelector('.faq-icon-circle');
      if (i === index) {
        const isActive = item.classList.contains('active');
        item.classList.toggle('active', !isActive);
        if (panel) {
          panel.style.maxHeight = !isActive ? '280px' : '0';
          panel.style.opacity = !isActive ? '1' : '0';
        }
        if (icon) icon.textContent = !isActive ? '−' : '+';
      } else {
        item.classList.remove('active');
        if (panel) {
          panel.style.maxHeight = '0';
          panel.style.opacity = '0';
        }
        if (icon) icon.textContent = '+';
      }
    });
  },

  /* ================= TESTIMONIALS ================= */
  initTestimonials() {
    this.activeTestimonialIdx = 0;
    this.renderTestimonialSlide();
    this.startTestimonialTimer();
  },

  renderTestimonialSlide() {
    const t = IFREIGHT_DATA.testimonials[this.activeTestimonialIdx];
    const quoteEl = document.getElementById('testimonialQuote');
    const initEl = document.getElementById('testimonialInitials');
    const nameEl = document.getElementById('testimonialName');
    const locEl = document.getElementById('testimonialLocation');
    const dotsEl = document.getElementById('testimonialDots');

    if (quoteEl) quoteEl.textContent = `“${t.quote}”`;
    if (initEl) initEl.textContent = t.initials;
    if (nameEl) nameEl.textContent = t.name;
    if (locEl) locEl.textContent = `${t.role} • ${t.location}`;

    if (dotsEl) {
      dotsEl.innerHTML = IFREIGHT_DATA.testimonials.map((_, i) => `
        <button class="test-dot ${i === this.activeTestimonialIdx ? 'active' : ''}" onclick="IFJ_APP.setTestimonial(${i})"></button>
      `).join('');
    }
  },

  setTestimonial(idx) {
    this.activeTestimonialIdx = idx;
    this.renderTestimonialSlide();
    this.startTestimonialTimer();
  },

  nextTestimonial() {
    this.activeTestimonialIdx = (this.activeTestimonialIdx + 1) % IFREIGHT_DATA.testimonials.length;
    this.renderTestimonialSlide();
    this.startTestimonialTimer();
  },

  prevTestimonial() {
    this.activeTestimonialIdx = (this.activeTestimonialIdx - 1 + IFREIGHT_DATA.testimonials.length) % IFREIGHT_DATA.testimonials.length;
    this.renderTestimonialSlide();
    this.startTestimonialTimer();
  },

  startTestimonialTimer() {
    clearInterval(this.testTimer);
    this.testTimer = setInterval(() => this.nextTestimonial(), 6000);
  },

  /* ================= NAV SCROLL & MOBILE ================= */
  initNavScroll() {
    const nav = document.getElementById('mainNav');
    if (!nav) return;
    window.addEventListener('scroll', () => {
      nav.classList.toggle('scrolled', window.scrollY > 40);
    }, { passive: true });
  },

  toggleMobileMenu(open) {
    const m = document.getElementById('mobileMenu');
    if (!m) return;
    m.classList.toggle('active', open);
    document.body.style.overflow = open ? 'hidden' : '';
  },

  /* ================= STATS ANIMATION ================= */
  initStatsObserver() {
    const statsSection = document.getElementById('statsSection');
    if (!statsSection) return;

    let started = false;
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting && !started) {
          started = true;
          this.animateCounters();
        }
      });
    }, { threshold: 0.25 });

    observer.observe(statsSection);
  },

  animateCounters() {
    const targets = [
      { id: 'stat0', target: 25000, suffix: '+', format: true },
      { id: 'stat1', target: 99.4, suffix: '%', decimals: 1 },
      { id: 'stat2', target: 12, suffix: ' Years' }
    ];

    const dur = 1800;
    const start = performance.now();

    const step = (now) => {
      const p = Math.min(1, (now - start) / dur);
      const ease = 1 - Math.pow(1 - p, 3);

      targets.forEach(t => {
        const el = document.getElementById(t.id);
        if (!el) return;
        if (t.decimals) {
          const val = (t.target * ease).toFixed(t.decimals);
          el.textContent = `${val}${t.suffix}`;
        } else {
          const val = Math.round(t.target * ease);
          el.textContent = `${t.format ? val.toLocaleString('en-US') : val}${t.suffix}`;
        }
      });

      if (p < 1) requestAnimationFrame(step);
    };

    requestAnimationFrame(step);
  },

  showToast(msg) {
    let container = document.getElementById('ifjToast');
    if (!container) {
      container = document.createElement('div');
      container.id = 'ifjToast';
      container.className = 'ifj-toast';
      document.body.appendChild(container);
    }
    container.textContent = msg;
    container.classList.add('show');
    setTimeout(() => container.classList.remove('show'), 3200);
  }
};

document.addEventListener('DOMContentLoaded', () => {
  IFJ_APP.init();
});
