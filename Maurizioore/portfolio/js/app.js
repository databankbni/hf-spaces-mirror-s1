// ========== TYPING EFFECT ==========
class TypeWriter {
  constructor(element, words, waitTime = 2000) {
    this.element = element;
    this.words = words;
    this.waitTime = waitTime;
    this.wordIndex = 0;
    this.text = '';
    this.isDeleting = false;
    this.type();
  }
  type() {
    const current = this.wordIndex % this.words.length;
    const fullText = this.words[current];
    this.text = this.isDeleting
      ? fullText.substring(0, this.text.length - 1)
      : fullText.substring(0, this.text.length + 1);
    this.element.innerHTML = `${this.text}<span class="cursor"></span>`;
    let speed = this.isDeleting ? 40 : 80;
    if (!this.isDeleting && this.text === fullText) {
      speed = this.waitTime;
      this.isDeleting = true;
    } else if (this.isDeleting && this.text === '') {
      this.isDeleting = false;
      this.wordIndex++;
      speed = 400;
    }
    setTimeout(() => this.type(), speed);
  }
}

// ========== NAVBAR HIDE/SHOW ON SCROLL ==========
function initNavbar() {
  const navbar = document.querySelector('.navbar');
  let lastScroll = 0;
  window.addEventListener('scroll', () => {
    const current = window.scrollY;
    if (current > lastScroll && current > 100) {
      navbar.classList.add('hidden');
    } else {
      navbar.classList.remove('hidden');
    }
    lastScroll = current;
  });
}

// ========== MOBILE MENU ==========
function initMobileMenu() {
  const toggle = document.querySelector('.navbar__toggle');
  const links = document.querySelector('.navbar__links');
  if (!toggle) return;
  toggle.addEventListener('click', () => {
    toggle.classList.toggle('active');
    links.classList.toggle('open');
  });
  links.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', () => {
      toggle.classList.remove('active');
      links.classList.remove('open');
    });
  });
}

// ========== ACTIVE NAV LINK ==========
function initActiveLink() {
  const sections = document.querySelectorAll('.section[id]');
  const navLinks = document.querySelectorAll('.navbar__links a');
  window.addEventListener('scroll', () => {
    let current = '';
    sections.forEach(section => {
      const top = section.offsetTop - 120;
      if (window.scrollY >= top) current = section.getAttribute('id');
    });
    navLinks.forEach(link => {
      link.classList.remove('active');
      if (link.getAttribute('href') === `#${current}`) link.classList.add('active');
    });
  });
}

// ========== SCROLL REVEAL ==========
function initScrollReveal() {
  const reveals = document.querySelectorAll('.reveal');
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -50px 0px' });
  reveals.forEach(el => observer.observe(el));
}

// ========== SMOOTH SCROLL FOR ANCHORS ==========
function initSmoothScroll() {
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', (e) => {
      e.preventDefault();
      const target = document.querySelector(anchor.getAttribute('href'));
      if (target) target.scrollIntoView({ behavior: 'smooth' });
    });
  });
}

// ========== CONTACT FORM (Removed — LinkedIn only) ==========

// ========== PROJECT IMAGE FALLBACK ==========
function initImageFallback() {
  document.querySelectorAll('.project-card__image').forEach(img => {
    img.addEventListener('error', function() {
      const placeholder = document.createElement('div');
      placeholder.className = 'project-card__placeholder';
      placeholder.innerHTML = this.dataset.icon || '💻';
      this.parentNode.replaceChild(placeholder, this);
    });
  });
}

// ========== MASCOT ==========
// 3D Chopper is handled by js/chopper.js (ES module)

// ========== INIT ==========
document.addEventListener('DOMContentLoaded', () => {
  // Typing effect
  const typingEl = document.getElementById('heroTyping');
  if (typingEl) {
    new TypeWriter(typingEl, [
      'Computer Engineer',
      'Cybersecurity Specialist',
      'Software Developer',
      'ML Enthusiast'
    ], 2200);
  }
  initNavbar();
  initMobileMenu();
  initActiveLink();
  initScrollReveal();
  initSmoothScroll();
  initImageFallback();
});
