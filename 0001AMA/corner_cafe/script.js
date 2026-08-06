(() => {
  const THEME_KEY = "corner-cafe-theme";

  const applyChrome = (theme) => {
    const meta = document.getElementById("meta-theme-color");
    if (meta) {
      meta.setAttribute("content", theme === "light" ? "#f6f3ee" : "#070707");
    }
  };

  const syncToggle = () => {
    const th = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
    const toggle = document.querySelector("[data-theme-toggle]");
    if (!toggle) return;
    const goLight = th === "dark";
    toggle.setAttribute("aria-label", goLight ? "Switch to light theme" : "Switch to dark theme");
    toggle.setAttribute("title", goLight ? "Light theme" : "Dark theme");
  };

  const setTheme = (theme) => {
    const th = theme === "light" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", th);
    try {
      localStorage.setItem(THEME_KEY, th);
    } catch (_) {}
    applyChrome(th);
    syncToggle();
  };

  let stored = null;
  try {
    stored = localStorage.getItem(THEME_KEY);
  } catch (_) {}

  if (stored === "light" || stored === "dark") {
    setTheme(stored);
  } else {
    applyChrome(document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark");
    syncToggle();
  }

  document.querySelector("[data-theme-toggle]")?.addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
    setTheme(cur === "dark" ? "light" : "dark");
  });

  const navToggle = document.querySelector("[data-nav-toggle]");
  const navPanel = document.querySelector("[data-nav-panel]");
  if (navToggle && navPanel) {
    navToggle.addEventListener("click", () => {
      const open = navPanel.classList.toggle("is-open");
      navToggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    navPanel.querySelectorAll("a").forEach((el) => {
      el.addEventListener("click", () => {
        navPanel.classList.remove("is-open");
        navToggle.setAttribute("aria-expanded", "false");
      });
    });
  }

  document.querySelectorAll("[data-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      const root = btn.closest("[data-tabs]");
      if (!root || !tab) return;
      root.querySelectorAll("[data-tab]").forEach((b) =>
        b.classList.toggle("is-active", b.dataset.tab === tab)
      );
      root.querySelectorAll("[data-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.panel !== tab;
      });
    });
  });

  const y = document.querySelector("#year");
  if (y) y.textContent = String(new Date().getFullYear());

  const openNowEls = Array.from(document.querySelectorAll("[data-open-now]"));
  if (openNowEls.length) {
    const toMinutes = (hh, mm) => hh * 60 + mm;
    const DAY_ABBR = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const fmtTime = (mins) => {
      const h = Math.floor(mins / 60);
      const m = mins % 60;
      return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
    };
    const daySlots = (day) => {
      // Every day Mon–Sun 09:00–17:00
      void day;
      return [toMinutes(9, 0)];
    };
    const isOpenNow = (d) => {
      const mins = toMinutes(d.getHours(), d.getMinutes());
      // Monday–Sunday: 09:00–17:00
      return mins >= toMinutes(9, 0) && mins < toMinutes(17, 0);
    };

    const nextOpenText = (d) => {
      const today = d.getDay();
      const nowMins = toMinutes(d.getHours(), d.getMinutes());
      for (let offset = 0; offset < 7; offset += 1) {
        const day = (today + offset) % 7;
        const starts = daySlots(day);
        if (!starts.length) continue;
        const candidate = offset === 0 ? starts.find((m) => m > nowMins) : starts[0];
        if (candidate == null) continue;
        if (offset === 0) return fmtTime(candidate);
        return `${DAY_ABBR[day]} ${fmtTime(candidate)}`;
      }
      return "";
    };

    const syncOpenNow = () => {
      const open = isOpenNow(new Date());
      const opensAt = nextOpenText(new Date());
      openNowEls.forEach((el) => {
        el.textContent = open ? "We are open" : `Opens at ${opensAt}`;
        el.classList.toggle("is-open", open);
        el.classList.toggle("is-closed", !open);
      });
    };

    syncOpenNow();
    const openNowTimer = window.setInterval(syncOpenNow, 30000);
    window.addEventListener(
      "pagehide",
      () => {
        window.clearInterval(openNowTimer);
      },
      { once: true }
    );
  }

  const hoursQuote = document.querySelector("[data-hours-quote]");
  if (hoursQuote) {
    const quotes = [
      "“A cracking wee cafe—proper Scottish breakfast and tea that tastes like home.”",
      "“Cullen skink, warm scones and a pot of tea—exactly what you want at Eskdail Court.”",
      "“Haggis, neeps and tatties done right; the cream tea is not to be missed.”",
    ];
    let quoteIndex = 0;
    let cycleTimer = 0;
    const QUOTE_MS = 5200;
    if (quotes.length > 1) {
      const playQuote = (idx) => {
        hoursQuote.classList.remove("is-typing");
        hoursQuote.textContent = quotes[idx];
        void hoursQuote.offsetWidth;
        hoursQuote.classList.add("is-typing");
      };

      playQuote(quoteIndex);
      cycleTimer = window.setInterval(() => {
        if (document.hidden) return;
        quoteIndex = (quoteIndex + 1) % quotes.length;
        playQuote(quoteIndex);
      }, QUOTE_MS);
      window.addEventListener(
        "pagehide",
        () => {
          window.clearInterval(cycleTimer);
        },
        { once: true }
      );
    }
  }

  /* Metered / slow connections still affect spotlight density; the hero always cycles
     the full set and only downloads one clip ahead. */
  const connection =
    navigator.connection || navigator.mozConnection || navigator.webkitConnection || null;
  const lightMediaMode = !!(
    connection &&
    (connection.saveData || /^(slow-2g|2g|3g)$/.test(connection.effectiveType || ""))
  );

  /**
   * Give a lazily declared video its real source the first time that clip is needed.
   * Returns true when it attached (and therefore already started loading).
   */
  const attachVideoSource = (vid) => {
    if (!vid || vid.tagName !== "VIDEO" || vid.dataset.srcAttached === "1") return false;
    const url = vid.dataset.src;
    if (!url) return false;
    const source = document.createElement("source");
    source.src = url;
    source.type = "video/mp4";
    vid.appendChild(source);
    vid.dataset.srcAttached = "1";
    vid.load();
    return true;
  };

  const whenIdle = (fn) =>
    "requestIdleCallback" in window
      ? window.requestIdleCallback(fn, { timeout: 2000 })
      : window.setTimeout(fn, 600);

  /**
   * Run `fn` once `el` comes within about a screen of the viewport. IntersectionObserver does
   * the work where it reports normally, but a scroll/resize position check runs alongside it
   * so deferred media still appears in embedded or non-compositing views where it does not.
   */
  const whenNear = (el, fn) => {
    if (!el) return;
    let fired = false;
    const check = () => {
      if (fired) return;
      const rect = el.getBoundingClientRect();
      const margin = window.innerHeight + 200;
      if (rect.top > window.innerHeight + margin || rect.bottom < -margin) return;
      fired = true;
      window.removeEventListener("scroll", check);
      window.removeEventListener("resize", check);
      fn();
    };
    window.addEventListener("scroll", check, { passive: true });
    window.addEventListener("resize", check, { passive: true });
    if ("IntersectionObserver" in window) {
      const io = new IntersectionObserver(
        (entries, observer) => {
          if (!entries.some((entry) => entry.isIntersecting)) return;
          observer.disconnect();
          check();
        },
        { rootMargin: "200px 0px" }
      );
      io.observe(el);
    }
    check();
  };

  const heroRoot = document.querySelector("[data-hero-slideshow]");
  const heroSlides = heroRoot ? Array.from(heroRoot.querySelectorAll(".hero-slide")) : [];
  if (heroRoot && heroSlides.length > 0) {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const isMobileHero = () =>
      window.matchMedia("(max-width: 767px)").matches ||
      window.matchMedia("(pointer: coarse)").matches;
    let cur = heroSlides.findIndex((el) => el.classList.contains("is-active"));
    if (cur < 0) cur = 0;
    let heroTimer = 0;
    let heroEndedHandler = null;

    const clearHeroAdvance = () => {
      window.clearTimeout(heroTimer);
      heroTimer = 0;
      if (heroEndedHandler) {
        heroSlides.forEach((el) => {
          if (el.tagName === "VIDEO") el.removeEventListener("ended", heroEndedHandler);
        });
        heroEndedHandler = null;
      }
    };

    const warmNext = () => {
      if (heroSlides.length < 2) return;
      const next = heroSlides[(cur + 1) % heroSlides.length];
      whenIdle(() => attachVideoSource(next));
    };

    const goHero = (index) => {
      cur = ((index % heroSlides.length) + heroSlides.length) % heroSlides.length;
      syncHeroMedia();
    };

    const scheduleAdvance = (vid) => {
      clearHeroAdvance();
      if (reduceMotion || heroSlides.length < 2) return;

      heroEndedHandler = () => {
        goHero(cur + 1);
      };
      vid.addEventListener("ended", heroEndedHandler);

      // Cap dwell so a long clip (or a stalled load) cannot freeze the rotation.
      // Mobile gets a slightly longer max so radios can finish the next fetch.
      const maxMs = isMobileHero() ? 10000 : 8000;
      heroTimer = window.setTimeout(() => {
        goHero(cur + 1);
      }, maxMs);
    };

    const syncHeroMedia = () => {
      heroSlides.forEach((el, i) => {
        const active = i === cur;
        el.classList.toggle("is-active", active);
        if (el.tagName !== "VIDEO") return;
        const vid = /** @type {HTMLVideoElement} */ (el);
        vid.muted = true;
        vid.playsInline = true;
        vid.loop = false;
        vid.defaultPlaybackRate = 1;
        vid.playbackRate = 1;
        if (active) {
          const justAttached = attachVideoSource(vid);
          const playActive = () => {
            const p = vid.play();
            if (p && typeof p.catch === "function") p.catch(() => {});
            scheduleAdvance(vid);
            warmNext();
          };
          if (vid.readyState >= 1) {
            try {
              vid.currentTime = 0;
            } catch (_) {}
            playActive();
          } else {
            vid.addEventListener(
              "loadedmetadata",
              () => {
                try {
                  vid.currentTime = 0;
                } catch (_) {}
                playActive();
              },
              { once: true }
            );
            if (!justAttached) vid.load();
          }
        } else {
          vid.pause();
        }
      });
    };

    // Always rotate the full set — including on Save-Data / 2G–3G. Lazy attach keeps
    // the phone downloading one clip at a time; only reduced-motion freezes on the first.
    syncHeroMedia();
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        clearHeroAdvance();
        const active = heroSlides[cur];
        if (active && active.tagName === "VIDEO") active.pause();
      } else {
        syncHeroMedia();
      }
    });
    window.addEventListener(
      "pagehide",
      () => {
        clearHeroAdvance();
      },
      { once: true }
    );
  }

  const spotlightRoot = document.querySelector("[data-spotlight-carousel]");
  if (spotlightRoot) {
    const track = spotlightRoot.querySelector("[data-spotlight-viewport]");
    const allSlides = Array.from(spotlightRoot.querySelectorAll("[data-spotlight-slide]"));
    const prevBtn = spotlightRoot.querySelector("[data-spotlight-prev]");
    const nextBtn = spotlightRoot.querySelector("[data-spotlight-next]");

    /**
     * Menu-side gallery: phones and tablets only rotate a short clip set and never
     * prefetch the next MP4, so the first frame arrives sooner on slower radios.
     */
    const compactMq = window.matchMedia("(max-width: 1023px)");
    const isCompactSpotlight = () => compactMq.matches || lightMediaMode;
    const activeSlides = () => {
      if (!isCompactSpotlight()) return allSlides;
      return allSlides.slice(0, Math.min(3, allSlides.length));
    };

    if (track && allSlides.length > 0) {
      let current = 0;
      let autoplayTimer = 0;
      let exitCleanupTimer = 0;
      let spotlightStarted = false;

      const applyCompactVisibility = () => {
        const keep = isCompactSpotlight() ? 3 : allSlides.length;
        allSlides.forEach((sl, j) => {
          const on = j < keep;
          sl.hidden = !on;
          if (!on) {
            sl.classList.remove("is-active", "is-exiting");
            const vid = sl.querySelector("video");
            if (vid) {
              vid.pause();
              /* Drop unused sources so they cannot keep buffering in the background. */
              if (vid.dataset.srcAttached === "1" && j >= keep) {
                vid.removeAttribute("src");
                vid.querySelectorAll("source").forEach((s) => s.remove());
                vid.removeAttribute("data-src-attached");
                vid.dataset.srcAttached = "0";
                try {
                  vid.load();
                } catch (_) {}
              }
            }
          }
        });
        if (current >= keep) current = 0;
      };

      const sync = () => {
        const slides = activeSlides();
        const n = slides.length;
        if (current >= n) current = 0;
        allSlides.forEach((sl) => {
          if (sl.hidden) return;
          const idx = slides.indexOf(sl);
          const isActive = idx === current;
          sl.classList.toggle("is-active", isActive);
          if (isActive) sl.classList.remove("is-exiting");
          const vid = sl.querySelector("video");
          if (!vid) return;
          vid.muted = true;
          vid.playsInline = true;
          if (isActive) {
            const justAttached = attachVideoSource(vid);
            const play = () => {
              const p = vid.play();
              if (p && typeof p.catch === "function") p.catch(() => {});
            };
            if (vid.readyState >= 1) {
              play();
            } else {
              vid.addEventListener("loadedmetadata", play, { once: true });
              if (!justAttached) vid.load();
            }
          } else {
            vid.pause();
            try {
              vid.currentTime = 0;
            } catch (_) {}
          }
        });
      };

      const goTo = (index) => {
        const slides = activeSlides();
        const n = slides.length;
        if (n <= 0) return;
        const prev = current;
        current = ((index % n) + n) % n;
        if (prev !== current) {
          const prevSlide = slides[prev];
          if (prevSlide) {
            prevSlide.classList.add("is-exiting");
            window.clearTimeout(exitCleanupTimer);
            exitCleanupTimer = window.setTimeout(() => {
              prevSlide.classList.remove("is-exiting");
            }, isCompactSpotlight() ? 700 : 1900);
          }
        }
        sync();
      };

      const goDelta = (delta) => {
        goTo(current + delta);
      };

      const scheduleAutoplay = () => {
        window.clearTimeout(autoplayTimer);
        const slides = activeSlides();
        if (slides.length <= 1) return;
        if (lightMediaMode) return;
        /* Longer dwell on phones/tablets = fewer sequential downloads. */
        const cadence = isCompactSpotlight() ? 9000 : 5200;
        const tick = () => {
          if (document.hidden) {
            autoplayTimer = window.setTimeout(tick, cadence);
            return;
          }
          goDelta(1);
          autoplayTimer = window.setTimeout(tick, cadence);
        };
        autoplayTimer = window.setTimeout(tick, cadence);
      };

      prevBtn?.addEventListener("click", () => {
        goDelta(-1);
        if (spotlightStarted) scheduleAutoplay();
      });
      nextBtn?.addEventListener("click", () => {
        goDelta(1);
        if (spotlightStarted) scheduleAutoplay();
      });

      track.addEventListener("keydown", (e) => {
        if (e.key === "ArrowLeft") {
          e.preventDefault();
          goDelta(-1);
        } else if (e.key === "ArrowRight") {
          e.preventDefault();
          goDelta(1);
        } else if (e.key === "Home") {
          e.preventDefault();
          goTo(0);
        } else if (e.key === "End") {
          e.preventDefault();
          goTo(activeSlides().length - 1);
        }
      });

      document.addEventListener("visibilitychange", () => {
        if (!document.hidden && spotlightStarted) scheduleAutoplay();
      });

      let resizeTimer = 0;
      window.addEventListener("resize", () => {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(() => {
          applyCompactVisibility();
          sync();
          if (spotlightStarted) scheduleAutoplay();
        }, 120);
      });

      window.addEventListener(
        "pagehide",
        () => {
          window.clearTimeout(autoplayTimer);
          window.clearTimeout(exitCleanupTimer);
        },
        { once: true }
      );

      const startSpotlight = () => {
        if (spotlightStarted) return;
        spotlightStarted = true;
        applyCompactVisibility();
        sync();
        scheduleAutoplay();
      };

      /* Start closer to the fold on phones so we do not kick off an MP4 while still above. */
      const nearEl = spotlightRoot;
      const whenNearSpotlight = (fn) => {
        if (!nearEl) return;
        let fired = false;
        const marginPx = isCompactSpotlight() ? 80 : 200;
        const check = () => {
          if (fired) return;
          const rect = nearEl.getBoundingClientRect();
          if (rect.top > window.innerHeight + marginPx || rect.bottom < -marginPx) return;
          fired = true;
          window.removeEventListener("scroll", check);
          window.removeEventListener("resize", check);
          fn();
        };
        window.addEventListener("scroll", check, { passive: true });
        window.addEventListener("resize", check, { passive: true });
        if ("IntersectionObserver" in window) {
          const io = new IntersectionObserver(
            (entries, observer) => {
              if (!entries.some((entry) => entry.isIntersecting)) return;
              observer.disconnect();
              check();
            },
            { rootMargin: `${marginPx}px 0px` }
          );
          io.observe(nearEl);
        }
        check();
      };

      applyCompactVisibility();
      whenNearSpotlight(startSpotlight);
    }
  }

  const aboutGlide = document.querySelector("[data-about-glide]");
  if (aboutGlide) {
    const aboutSlidesEl = aboutGlide.querySelector(".glide__slides");
    const aboutSlides = Array.from(aboutGlide.querySelectorAll(".glide__slide"));
    if (aboutSlidesEl && aboutSlides.length > 0) {
      let current = 0;
      let startX = null;
      let startY = null;
      let wasSwipe = false;
      const ABOUT_MS = 3000;
      const captionWords = [
        "Corner cafe Moment",
        "Chef's Detail",
        "Counter Light",
        "Breakfast Mood",
        "Afternoon Plate",
        "Tea Study",
      ];

      const makeMeta = (imgSrc, idx) => {
        const title = `${captionWords[idx % captionWords.length]}`;
        const desc = "Curated cafe frame from the Corner cafe gallery.";
        return { title, desc };
      };

      const lightbox = document.createElement("div");
      lightbox.className = "about-lightbox";
      lightbox.setAttribute("aria-hidden", "true");
      lightbox.innerHTML = `
        <button type="button" class="about-lightbox__close" aria-label="Close image">×</button>
        <figure class="about-lightbox__figure">
          <img class="about-lightbox__img" alt="">
          <figcaption class="about-lightbox__meta">
            <strong class="about-lightbox__title"></strong>
            <span class="about-lightbox__desc"></span>
          </figcaption>
        </figure>
      `;
      document.body.appendChild(lightbox);
      const lightboxImg = lightbox.querySelector(".about-lightbox__img");
      const lightboxTitle = lightbox.querySelector(".about-lightbox__title");
      const lightboxDesc = lightbox.querySelector(".about-lightbox__desc");

      /* Thumbnails are served at w=800; only the opened image asks for a larger render. */
      const fullSizeSrc = (src) => String(src || "").replace(/([?&]w=)\d+/, "$11600");

      const openLightbox = (slide) => {
        const img = slide.querySelector("img");
        if (!img || !lightboxImg || !lightboxTitle || !lightboxDesc) return;
        lightboxImg.src = fullSizeSrc(img.currentSrc || img.src);
        lightboxImg.alt = img.alt || "";
        lightboxTitle.textContent = slide.dataset.aboutTitle || "";
        lightboxDesc.textContent = slide.dataset.aboutDesc || "";
        lightbox.classList.add("is-open");
        lightbox.setAttribute("aria-hidden", "false");
      };

      const closeLightbox = () => {
        lightbox.classList.remove("is-open");
        lightbox.setAttribute("aria-hidden", "true");
      };
      lightbox.addEventListener("click", (e) => {
        if (e.target === lightbox || e.target.closest(".about-lightbox__close")) {
          closeLightbox();
        }
      });
      window.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && lightbox.classList.contains("is-open")) closeLightbox();
      });

      aboutSlides.forEach((slide, idx) => {
        const img = slide.querySelector("img");
        if (!img) return;
        const meta = makeMeta(img.getAttribute("src") || "", idx);
        slide.dataset.aboutTitle = meta.title;
        slide.dataset.aboutDesc = meta.desc;
        slide.setAttribute("role", "button");
        slide.setAttribute("tabindex", "0");
        slide.setAttribute("aria-label", `${meta.title}. Open expanded image.`);

        const cap = document.createElement("span");
        cap.className = "about-glide__caption";
        cap.textContent = meta.title;
        slide.appendChild(cap);

        slide.addEventListener("click", () => {
          if (wasSwipe) {
            wasSwipe = false;
            return;
          }
          openLightbox(slide);
        });
        slide.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            openLightbox(slide);
          }
        });
      });
      const gap = () => {
        const st = window.getComputedStyle(aboutSlidesEl);
        return parseFloat(st.columnGap || st.gap || "0") || 0;
      };
      const visible = () => {
        if (window.matchMedia("(max-width: 640px)").matches) return 1;
        if (window.matchMedia("(max-width: 900px)").matches) return 2;
        return 3;
      };
      const maxIndex = () => Math.max(0, aboutSlides.length - visible());
      const step = () => {
        const v = visible();
        const g = gap();
        return v <= 1 ? aboutGlide.clientWidth : (aboutGlide.clientWidth - g * (v - 1)) / v + g;
      };
      /* Photos are attached for the slides on screen plus a few ahead of the loop. */
      let galleryActive = false;
      const loadSlideWindow = () => {
        if (!galleryActive) return;
        const last = current + visible() + 3;
        for (let i = current; i <= last; i += 1) {
          const img = aboutSlides[i % aboutSlides.length].querySelector("img[data-src]");
          if (!img) continue;
          img.src = img.dataset.src;
          img.removeAttribute("data-src");
        }
      };

      const syncAbout = (animate = true) => {
        const clamped = Math.max(0, Math.min(maxIndex(), current));
        if (clamped !== current) current = clamped;
        loadSlideWindow();
        aboutSlidesEl.style.transition = animate
          ? "transform 0.55s cubic-bezier(0.22, 1, 0.36, 1)"
          : "none";
        aboutSlidesEl.style.transform = `translate3d(-${current * step()}px, 0, 0)`;
      };
      const goAbout = (index, animate = true) => {
        const max = maxIndex();
        if (max <= 0) {
          current = 0;
        } else if (index > max) {
          current = 0;
        } else if (index < 0) {
          current = max;
        } else {
          current = index;
        }
        syncAbout(animate);
      };
      let aboutTimer = 0;
      const startAboutLoop = () => {
        window.clearInterval(aboutTimer);
        if (aboutSlides.length <= visible()) return;
        aboutTimer = window.setInterval(() => {
          if (document.hidden) return;
          goAbout(current + 1, true);
        }, ABOUT_MS);
      };

      const onTouchStart = (e) => {
        const touch = e.touches && e.touches[0];
        if (!touch) return;
        startX = touch.clientX;
        startY = touch.clientY;
        wasSwipe = false;
      };

      const onTouchEnd = (e) => {
        if (startX === null || startY === null) return;
        const touch = e.changedTouches && e.changedTouches[0];
        if (!touch) return;
        const dx = touch.clientX - startX;
        const dy = touch.clientY - startY;
        startX = null;
        startY = null;
        if (Math.abs(dx) < 44 || Math.abs(dx) <= Math.abs(dy)) return;
        wasSwipe = true;
        goAbout(current + (dx < 0 ? 1 : -1), true);
      };

      aboutGlide.addEventListener("touchstart", onTouchStart, { passive: true });
      aboutGlide.addEventListener("touchend", onTouchEnd, { passive: true });
      aboutGlide.addEventListener("pointerdown", (e) => {
        startX = e.clientX;
        startY = e.clientY;
        wasSwipe = false;
      });
      aboutGlide.addEventListener("pointerup", (e) => {
        if (startX === null || startY === null) return;
        const dx = e.clientX - startX;
        const dy = e.clientY - startY;
        startX = null;
        startY = null;
        if (Math.abs(dx) < 44 || Math.abs(dx) <= Math.abs(dy)) return;
        wasSwipe = true;
        goAbout(current + (dx < 0 ? 1 : -1), true);
      });
      aboutGlide.addEventListener("keydown", (e) => {
        if (e.key === "ArrowLeft") {
          e.preventDefault();
          goAbout(current - 1, true);
        } else if (e.key === "ArrowRight") {
          e.preventDefault();
          goAbout(current + 1, true);
        }
      });

      syncAbout(false);
      let aboutResizeTimer = 0;
      window.addEventListener("resize", () => {
        window.clearTimeout(aboutResizeTimer);
        aboutResizeTimer = window.setTimeout(() => syncAbout(false), 120);
      });

      /* The gallery only starts cycling once it is on screen, so it never pulls images early. */
      const startGallery = () => {
        galleryActive = true;
        loadSlideWindow();
        startAboutLoop();
      };

      whenNear(aboutGlide, startGallery);
      window.addEventListener(
        "pagehide",
        () => {
          window.clearInterval(aboutTimer);
        },
        { once: true }
      );
    }
  }

  const pressSection = document.querySelector("section#press.press-section");
  const pressCarousel = document.querySelector(".press-grid--single");
  if (pressCarousel) {
    const cards = Array.from(pressCarousel.querySelectorAll(".press-card"));
    if (cards.length > 0) {
      let current = 0;
      const sync = () => {
        cards.forEach((card, idx) => {
          card.classList.toggle("is-active", idx === current);
          card.setAttribute("aria-hidden", idx === current ? "false" : "true");
        });
      };
      sync();
      if (cards.length > 1) {
        const PRESS_MS = 4800;
        const timer = window.setInterval(() => {
          if (document.hidden) return;
          current = (current + 1) % cards.length;
          sync();
        }, PRESS_MS);
        window.addEventListener(
          "pagehide",
          () => {
            window.clearInterval(timer);
          },
          { once: true }
        );
      }
    }
  }

  if (pressSection && "IntersectionObserver" in window) {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      pressSection.classList.add("press-section--visible");
    } else {
      const pressIo = new IntersectionObserver(
        (entries, observer) => {
          entries.forEach((entry) => {
            if (!entry.isIntersecting) return;
            entry.target.classList.add("press-section--visible");
            observer.unobserve(entry.target);
          });
        },
        { threshold: 0.12, rootMargin: "0px 0px -5% 0px" }
      );
      pressIo.observe(pressSection);
    }
  } else if (pressSection) {
    pressSection.classList.add("press-section--visible");
  }

  /* Floating contact form → POST /api/contact (SMTP mail server) */
  const contactModal = document.querySelector("[data-contact-modal]");
  const contactForm = document.querySelector("[data-contact-form]");
  const contactStatus = document.querySelector("[data-contact-status]");
  const contactSubmit = document.querySelector("[data-contact-submit]");
  let contactLastFocus = null;

  const setContactStatus = (text, kind) => {
    if (!contactStatus) return;
    contactStatus.textContent = text || "";
    contactStatus.classList.remove("is-error", "is-ok");
    if (kind) contactStatus.classList.add(kind);
  };

  const setContactFieldsActive = (active) => {
    if (!contactForm) return;
    contactForm.querySelectorAll("input, textarea, button").forEach((el) => {
      if (el.name === "website") {
        el.tabIndex = -1;
        return;
      }
      el.disabled = !active;
    });
  };

  const openContact = (prefill) => {
    if (!contactModal) return;
    contactLastFocus = document.activeElement;
    contactModal.hidden = false;
    contactModal.removeAttribute("inert");
    document.body.style.overflow = "hidden";
    setContactStatus("", null);
    setContactFieldsActive(true);
    if (contactForm && prefill) {
      if (prefill.subject) contactForm.elements.subject.value = prefill.subject;
      if (prefill.message) contactForm.elements.message.value = prefill.message;
    }
    const first = contactForm && contactForm.querySelector('input[name="email"]');
    window.setTimeout(() => {
      if (first) first.focus();
    }, 30);
  };

  const closeContact = () => {
    if (!contactModal) return;
    contactModal.hidden = true;
    contactModal.setAttribute("inert", "");
    document.body.style.overflow = "";
    setContactFieldsActive(false);
    if (contactLastFocus && typeof contactLastFocus.focus === "function") {
      contactLastFocus.focus();
    }
  };

  /* Start closed: form must not show or accept input until Contact us */
  if (contactModal) {
    contactModal.hidden = true;
    contactModal.setAttribute("inert", "");
    setContactFieldsActive(false);
  }

  document.addEventListener("click", (e) => {
    const openEl = e.target.closest("[data-contact-open]");
    if (openEl) {
      e.preventDefault();
      openContact();
      return;
    }
    if (e.target.closest("[data-contact-close]")) {
      e.preventDefault();
      closeContact();
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && contactModal && !contactModal.hidden) {
      closeContact();
    }
  });

  if (contactForm) {
    contactForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(contactForm);
      const body = {
        email: String(fd.get("email") || "").trim(),
        subject: String(fd.get("subject") || "").trim(),
        message: String(fd.get("message") || "").trim(),
        website: String(fd.get("website") || ""),
      };
      if (!body.email || !body.subject || !body.message) {
        setContactStatus("Please fill in email, subject and message.", "is-error");
        return;
      }
      if (contactSubmit) contactSubmit.disabled = true;
      setContactStatus("Sending…", null);
      try {
        // Prefer on-server SMTP API when the Space/host runs app.py (Docker / local).
        let usedApi = false;
        try {
          const health = await fetch("/api/health", { headers: { Accept: "application/json" } });
          if (health.ok) {
            const res = await fetch("/api/contact", {
              method: "POST",
              headers: { "Content-Type": "application/json", Accept: "application/json" },
              body: JSON.stringify(body),
            });
            usedApi = true;
            let detail = "";
            try {
              const data = await res.json();
              detail = data.detail || data.message || "";
              if (Array.isArray(detail)) {
                detail = detail.map((d) => d.msg || JSON.stringify(d)).join(" ");
              }
            } catch (_) {}
            if (!res.ok) {
              setContactStatus(detail || `Could not send (${res.status}).`, "is-error");
              return;
            }
            setContactStatus("Sent — thank you. We’ll reply by email.", "is-ok");
            contactForm.reset();
            window.setTimeout(() => closeContact(), 1400);
            return;
          }
        } catch (_) {
          /* fall through to FormSubmit when API is not hosted (static HF Space) */
        }

        // Static hosting fallback: FormSubmit AJAX → pd3rvr@icloud.com (no local mail app).
        const fsRes = await fetch("https://formsubmit.co/ajax/pd3rvr@icloud.com", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({
            email: body.email,
            subject: body.subject,
            message: body.message,
            _subject: `[Corner cafe] ${body.subject}`,
            _template: "table",
            _captcha: "false",
          }),
        });
        const fsData = await fsRes.json().catch(() => ({}));
        if (!fsRes.ok || fsData.success === "false" || fsData.success === false) {
          setContactStatus(
            (fsData && (fsData.message || fsData.error)) || "Could not send. Please try again.",
            "is-error"
          );
          return;
        }
        setContactStatus("Sent — thank you. We’ll reply by email.", "is-ok");
        contactForm.reset();
        window.setTimeout(() => closeContact(), 1400);
      } catch (_) {
        setContactStatus("Network error — please try again.", "is-error");
      } finally {
        if (contactSubmit) contactSubmit.disabled = false;
      }
    });
  }
})();
