const NOT_OBSERVED = "لم يتم الرصد";
const NOT_APPLICABLE = "غير منطبق";

function formatNumber(value) {
  if (value === undefined || value === null || value === "") return "";
  if (value === NOT_OBSERVED || value === NOT_APPLICABLE) return value;
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  return new Intl.NumberFormat("ar-SA", { maximumFractionDigits: 0 }).format(Math.round(num));
}

function numericValue(value) {
  const num = Number(value);
  return Number.isNaN(num) ? 0 : num;
}

function hasValue(value) {
  return value !== undefined && value !== null && value !== "" && value !== NOT_OBSERVED && value !== NOT_APPLICABLE;
}

function isManagementPlaceholder(value) {
  return !value || value === NOT_OBSERVED || value === NOT_APPLICABLE || String(value).includes("لم يتم التحديث") || String(value).includes("بانتظار");
}

function createEl(tag, options = {}, children = []) {
  const el = document.createElement(tag);
  Object.entries(options).forEach(([key, value]) => {
    if (value === undefined || value === null || value === false) return;
    if (key === "className") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key === "attrs") Object.entries(value).forEach(([name, attrValue]) => el.setAttribute(name, attrValue));
    else el[key] = value;
  });
  children.filter(Boolean).forEach((child) => el.append(child));
  return el;
}

function clear(el) {
  if (el) el.replaceChildren();
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value || "";
}

function safeUrl(value) {
  if (!value || value === NOT_OBSERVED) return null;
  try {
    const url = new URL(String(value), window.location.href);
    if (url.protocol !== "https:") return null;
    return url.toString();
  } catch {
    return null;
  }
}

function normalizeGoogleDriveImageUrl(url) {
  if (!url) return { ok: false, message: "رابط Google Drive فارغ" };

  let parsed;
  try {
    parsed = new URL(String(url));
  } catch {
    return { ok: false, message: "رابط Google Drive غير صالح" };
  }

  if (parsed.protocol !== "https:") {
    return { ok: false, message: "يجب أن يبدأ رابط Google Drive بـ https" };
  }

  const host = parsed.hostname.toLowerCase();
  if (host !== "drive.google.com" && host !== "docs.google.com") {
    return { ok: false, message: "الرابط ليس من Google Drive" };
  }

  if (parsed.pathname.includes("/folders/")) {
    return { ok: false, message: "رابط Google Drive يشير إلى مجلد وليس صورة" };
  }

  const blockedDocPaths = ["/document/d/", "/spreadsheets/d/", "/presentation/d/", "/forms/d/"];
  if (host === "docs.google.com" || blockedDocPaths.some((part) => parsed.pathname.includes(part))) {
    return { ok: false, message: "رابط Google Drive يشير إلى مستند وليس صورة" };
  }

  const patterns = [
    /\/file\/d\/([^/]+)/,
    /\/uc\/?$/,
    /\/open\/?$/
  ];
  let fileId = parsed.searchParams.get("id");
  if (!fileId) {
    for (const pattern of patterns) {
      const match = parsed.pathname.match(pattern);
      if (match?.[1]) {
        fileId = match[1];
        break;
      }
    }
  }

  if (!fileId || !/^[a-zA-Z0-9_-]{10,}$/.test(fileId)) {
    return { ok: false, message: "تعذر استخراج معرف ملف Google Drive" };
  }

  return {
    ok: true,
    provider: "google-drive",
    fileId,
    sourceUrl: parsed.toString(),
    displayUrl: `https://drive.google.com/thumbnail?id=${encodeURIComponent(fileId)}&sz=w1600`
  };
}

function getCurrentMonthParam() {
  return window.DASHBOARD_NAV?.selectedMonth || new URLSearchParams(window.location.search).get("month") || "5";
}

function getCurrentWeekParam() {
  return window.DASHBOARD_NAV?.selectedWeek || new URLSearchParams(window.location.search).get("week") || "week6";
}

function getCurrentMonthTitle() {
  const month = getCurrentMonthParam();
  const week = getCurrentWeekParam();
  const nav = window.DASHBOARD_NAV;

  if (month === "summary") return "الإحصائية التراكمية";
  if (nav?.monthMeta?.key === "summer-productivity") {
    return nav.weekLabel ? nav.weekLabel(week) : week;
  }
  if (nav?.monthMeta?.weeks?.length) {
    return `إنتاجية شهر ${month} - ${nav.weekLabel ? nav.weekLabel(week) : week}`;
  }
  return `إنتاجية شهر ${month}`;
}

function appendMetric(parent, label, value, className = "metric") {
  if (!hasValue(value)) return;
  if (label === "عدد المشرفين" && numericValue(value) === 0) return;
  const isNumeric = !Number.isNaN(Number(value));
  const card = createEl("div", { className });
  card.append(
    createEl("span", { className: className === "quick-metric" ? "q-label" : "m-label", text: label }),
    createEl("span", {
      className: `${className === "quick-metric" ? "q-value" : "m-value"} ${isNumeric ? "js-animate-number" : ""}`.trim(),
      text: formatNumber(value),
      dataset: { target: isNumeric ? numericValue(value) : 0 }
    })
  );
  parent.append(card);
}

function createInvalidLinkNotice() {
  return createEl("div", { className: "evidence-invalid", text: "رابط غير صالح أو غير آمن" });
}

function appendEvidence(parent, link) {
  const links = Array.isArray(link) ? link : [link];
  const validLinks = links.map(safeUrl).filter(Boolean);
  if (!validLinks.length) return;

  const card = createEl("div", { className: "metric evidence-metric evidence-list" });
  card.append(createEl("span", { className: "m-label", text: "توثيق البرنامج" }));
  const linksWrap = createEl("div", { className: "evidence-links" });
  validLinks.forEach((url, index) => {
    linksWrap.append(
      createEl("a", {
        className: "evidence-link",
        href: url,
        target: "_blank",
        rel: "noopener",
        text: `مشاهدة الشاهد${validLinks.length > 1 ? ` ${index + 1}` : ""}`,
        attrs: { "aria-label": `فتح رابط الشاهد ${index + 1}` }
      })
    );
  });

  card.append(linksWrap);
  parent.append(card);
}

function normalizeImages(item) {
  const images = [];
  const source = item.images || item.photos || [];
  if (item.mainImage || item.image) {
    images.push(typeof (item.mainImage || item.image) === "string" ? { src: item.mainImage || item.image } : item.mainImage || item.image);
  }
  if (Array.isArray(source)) images.push(...source);
  return images
    .map((image, index) => {
      const normalized = typeof image === "string" ? { src: image } : { ...image };
      const driveSource = normalized.driveUrl || normalized.sourceUrl || normalized.src;
      const drive = normalizeGoogleDriveImageUrl(driveSource);
      if (drive.ok && (!normalized.provider || normalized.provider === "google-drive")) {
        return { ...normalized, ...drive, src: drive.displayUrl, order: normalized.order ?? normalized.sortOrder ?? index + 1 };
      }
      return { ...normalized, src: normalized.displayUrl || normalized.src, order: normalized.order ?? normalized.sortOrder ?? index + 1 };
    })
    .filter((image) => safeUrl(image.src) || image.src?.startsWith("assets/") || image.src?.startsWith("./assets/") || image.src?.startsWith("../assets/"))
    .sort((a, b) => Number(a.order || 0) - Number(b.order || 0));
}

function imageSrc(value) {
  if (!value) return "";
  if (safeUrl(value)) return safeUrl(value);
  return new URL(value, window.location.href).toString();
}

function getImageDisplaySrc(image) {
  if (image.displayUrl) return image.displayUrl;
  if (image.provider === "google-drive" || image.sourceUrl || image.driveUrl) {
    const drive = normalizeGoogleDriveImageUrl(image.sourceUrl || image.driveUrl || image.src);
    if (drive.ok) return drive.displayUrl;
    console.warn("تعذر تحويل رابط Google Drive للصورة:", drive.message);
  }
  return imageSrc(image.src);
}

function appendImageGallery(parent, item) {
  const images = normalizeImages(item);
  if (!images.length) return;

  const gallery = createEl("div", { className: `image-gallery image-gallery--${images.length === 1 ? "single" : "grid"}` });
  images.forEach((image, index) => {
    const button = createEl("button", {
      className: "image-thumb",
      type: "button",
      attrs: { "aria-label": image.alt || `تكبير الصورة ${index + 1}` }
    });
    const img = createEl("img", {
      src: getImageDisplaySrc(image),
      alt: image.alt || item.name || "صورة توثيقية",
      loading: "lazy",
      decoding: "async"
    });
    img.addEventListener("error", () => {
      console.warn("تعذر تحميل الصورة. تحقق من أن رابط Google Drive متاح لمن لديه الرابط وأنه ملف صورة.");
      button.classList.add("image-thumb--missing");
      button.replaceChildren(createEl("span", { text: "تعذر تحميل الصورة" }));
    });
    button.append(img);
    if (image.caption) button.append(createEl("span", { className: "image-caption", text: image.caption }));
    button.addEventListener("click", () => openLightbox(images, index, item.name));
    gallery.append(button);
  });
  parent.append(gallery);
}

function openLightbox(images, startIndex, title) {
  let current = startIndex;
  const overlay = createEl("div", { className: "lightbox", attrs: { role: "dialog", "aria-modal": "true", "aria-label": "معرض الصور" } });
  const img = createEl("img", { className: "lightbox-img", alt: "" });
  const caption = createEl("div", { className: "lightbox-caption" });
  const close = createEl("button", { className: "lightbox-close", type: "button", text: "إغلاق", attrs: { "aria-label": "إغلاق معرض الصور" } });
  const prev = createEl("button", { className: "lightbox-nav lightbox-prev", type: "button", text: "السابق" });
  const next = createEl("button", { className: "lightbox-nav lightbox-next", type: "button", text: "التالي" });

  function render() {
    const image = images[current];
    img.src = getImageDisplaySrc(image);
    img.alt = image.alt || title || "صورة توثيقية";
    caption.textContent = image.caption || title || "";
    prev.hidden = images.length < 2;
    next.hidden = images.length < 2;
  }

  close.addEventListener("click", () => overlay.remove());
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) overlay.remove();
  });
  prev.addEventListener("click", () => {
    current = (current - 1 + images.length) % images.length;
    render();
  });
  next.addEventListener("click", () => {
    current = (current + 1) % images.length;
    render();
  });
  document.addEventListener("keydown", function onKey(event) {
    if (!document.body.contains(overlay)) {
      document.removeEventListener("keydown", onKey);
      return;
    }
    if (event.key === "Escape") overlay.remove();
  });

  overlay.append(createEl("div", { className: "lightbox-panel" }, [close, img, caption, prev, next]));
  document.body.append(overlay);
  render();
  close.focus();
}

function createMonthsNav() {
  const nav = document.querySelector(".months-nav");
  const months = window.DASHBOARD_NAV?.months || [];
  if (!nav || !months.length) return;
  clear(nav);
  const current = getCurrentMonthParam();
  const summerMonth = months.find((month) => month.key === "summer-productivity");
  if (summerMonth) {
    const activeWeek = getCurrentWeekParam();
    (summerMonth.weeks || []).forEach((week) => {
      nav.append(
        createEl("a", {
          href: `index.html?month=${summerMonth.month}&week=${week.key}`,
          text: week.title || week.key,
          className: activeWeek === week.key ? "is-current-month" : "",
          attrs: { "aria-label": week.title || week.key }
        })
      );
    });
    nav.append(
      createEl("a", {
        href: `index.html?month=${summerMonth.month}&week=summary`,
        text: "تراكمي",
        className: activeWeek === "summary" ? "is-current-month" : "",
        attrs: { "aria-label": "تراكمي" }
      })
    );
    return;
  }
  months.forEach((month) => {
    const link = createEl("a", {
      href: `./months/month${month.month}.html`,
      text: String(month.month),
      className: String(month.month) === String(current) ? "is-current-month" : "",
      attrs: { "aria-label": month.title || `شهر ${month.month}` }
    });
    nav.append(link);
  });
  nav.append(
    createEl("a", {
      href: "./summary.html",
      text: "تراكمي",
      className: current === "summary" ? "is-current-month" : "",
      attrs: { "aria-label": "الإحصائية التراكمية" }
    })
  );
}

function createWeekTabs() {
  const oldTabs = document.querySelector(".week-tabs");
  if (oldTabs) oldTabs.remove();
  const monthMeta = window.DASHBOARD_NAV?.monthMeta;
  if (monthMeta?.key === "summer-productivity") return;
  if (!monthMeta?.weeks?.length) return;

  const activeWeek = getCurrentWeekParam();
  const tabs = createEl("nav", { className: "week-tabs", attrs: { "aria-label": "أسابيع الشهر" } });
  monthMeta.weeks.forEach((week) => {
    tabs.append(
      createEl("a", {
        href: `index.html?month=${monthMeta.month}&week=${week.key}`,
        text: week.title || week.key,
        className: activeWeek === week.key ? "active" : "",
        attrs: { "aria-current": activeWeek === week.key ? "page" : "false" }
      })
    );
  });
  tabs.append(
    createEl("a", {
      href: `index.html?month=${monthMeta.month}&week=summary`,
      text: "التجميع",
      className: activeWeek === "summary" ? "active" : "",
      attrs: { "aria-current": activeWeek === "summary" ? "page" : "false" }
    })
  );
  document.querySelector(".months-nav")?.insertAdjacentElement("afterend", tabs);
}

function showStatus() {
  const status = document.getElementById("data-status");
  if (!status) return;
  if (window.DASHBOARD_ERROR) {
    status.hidden = false;
    status.textContent = window.DASHBOARD_ERROR;
    status.className = "data-status data-status--error";
  } else {
    status.hidden = true;
  }
}

function createHeader() {
  const data = window.DASHBOARD_DATA;
  const isSummary = getCurrentWeekParam() === "summary";
  document.body.classList.toggle("is-summary-view", isSummary);
  setText("page-subtitle", data.subtitle || "");
  setText("month-title", getCurrentMonthTitle());
  const heroCopy = document.querySelector(".hero-copy");
  if (heroCopy) {
    heroCopy.querySelector(".period-badge")?.remove();
    if (isSummary) {
      heroCopy.append(createEl("div", { className: "period-badge", text: window.DASHBOARD_DATA.subtitle || "تراكمي" }));
    }
  }
  const note = document.getElementById("month-note");
  const lastUpdate = document.getElementById("last-update");
  if (note) {
    note.textContent = isManagementPlaceholder(data.note) ? "" : data.note;
    note.hidden = !note.textContent;
  }
  if (lastUpdate) {
    lastUpdate.textContent = isManagementPlaceholder(data.lastUpdate) ? "" : data.lastUpdate;
    lastUpdate.hidden = !lastUpdate.textContent;
  }
  setText("footer-text", data.footerText || "© التعليم الإلكتروني");
}

function createTopStats() {
  const wrap = document.getElementById("top-stats");
  clear(wrap);
  if (!wrap || !Array.isArray(window.DASHBOARD_DATA.topStats)) return;

  window.DASHBOARD_DATA.topStats.forEach((item) => {
    const isNumeric = !Number.isNaN(Number(item.value));
    const card = createEl("article", { className: "stat-card" });
    card.append(
      createEl("div", { className: "stat-label", text: item.label }),
      createEl("div", {
        className: `stat-value ${isNumeric ? "js-animate-number" : ""}`.trim(),
        text: formatNumber(item.value),
        dataset: { target: isNumeric ? numericValue(item.value) : 0 }
      })
    );
    wrap.append(card);
  });
}

function createProgramsSummary() {
  const wrap = document.getElementById("programs-summary");
  clear(wrap);
  if (!wrap) return;

  const programs = Array.isArray(window.DASHBOARD_DATA.programs) ? window.DASHBOARD_DATA.programs : [];
  const halaqat = Array.isArray(window.DASHBOARD_DATA.halaqat) ? window.DASHBOARD_DATA.halaqat : [];
  const programCount = programs.reduce((sum, item) => sum + (numericValue(item.occurrences) || 1), 0);
  const volunteerTotal = programs.reduce((sum, item) => sum + numericValue(item.volunteers), 0);
  const cards = [
    ["عدد البرامج النوعية", programCount, "إجمالي البرامج والفعاليات"],
    ["إجمالي المستفيدين", programs.reduce((sum, item) => sum + numericValue(item.beneficiaries), 0), "من البرامج النوعية وبث منصة إكس"],
    [
      "إجمالي ساعات البث",
      programs.reduce((sum, item) => sum + numericValue(item.broadcastHours), 0) + halaqat.reduce((sum, item) => sum + numericValue(item.broadcastHours), 0),
      "ساعات الحلق والبرامج النوعية"
    ]
  ];
  if (volunteerTotal > 0) cards.splice(2, 0, ["إجمالي المتطوعين", volunteerTotal, "إجمالي المشاركين في التطوع"]);
  cards.forEach(([label, value, note]) => {
    const card = createEl("article", { className: "executive-card" });
    card.append(
      createEl("div", { className: "executive-label", text: label }),
      createEl("div", { className: "executive-value js-animate-number", text: formatNumber(value), dataset: { target: value } }),
      createEl("div", { className: "executive-note", text: note })
    );
    wrap.append(card);
  });
}

function createEmptyState(title, text) {
  const box = createEl("div", { className: "empty-state" });
  box.append(createEl("div", { className: "empty-state__title", text: title }));
  if (text) box.append(createEl("div", { className: "empty-state__text", text }));
  return box;
}

function createHalaqat() {
  const wrap = document.getElementById("halaqat-grid");
  clear(wrap);
  const halaqat = window.DASHBOARD_DATA.halaqat || [];
  if (!wrap) return;
  if (!halaqat.length) {
    wrap.append(createEmptyState("لا توجد بيانات للحلق في هذه الفترة", "سيتم عرض تفاصيل الحلق هنا عند إضافة البيانات."));
    return;
  }
  halaqat.forEach((item) => {
    const card = createEl("article", { className: "halaqa-card" });
    card.append(
      createEl("div", { className: "halaqa-top" }, [
        createEl("h4", { className: "halaqa-title", text: item.name || "" }),
        createEl("span", { className: "chip", text: item.badge || "حلقة" })
      ])
    );
    const quick = createEl("div", { className: "quick-metrics" });
    appendMetric(quick, "الطلاب", item.students, "quick-metric");
    appendMetric(quick, "المعلمين", item.teachers, "quick-metric");
    appendMetric(quick, "الأجزاء", item.memorizedParts, "quick-metric");
    card.append(quick);
    const details = createEl("details", { className: "more-details" });
    details.append(createEl("summary", { text: "عرض الملخص" }));
    const metrics = createEl("div", { className: "metrics" });
    [
      ["عدد الحلق", item.halaqCount],
      ["عدد المعلمين", item.teachers],
      ["عدد المشرفين", item.supervisors],
      ["عدد الطلاب", item.students],
      ["الأوجه المحفوظة", item.memorizedFaces],
      ["الأجزاء المحفوظة", item.memorizedParts],
      ["الأوجه المراجعة", item.reviewFaces],
      ["الأجزاء المراجعة", item.reviewParts],
      ["ساعات البث", item.broadcastHours],
      ["أصغر طالب", item.minAge],
      ["أكبر طالب", item.maxAge],
      ["عدد المختبرين", item.tested],
      ["عدد المجتازين", item.passed],
      ["كامل القرآن", item.fullQuran]
    ].forEach(([label, value]) => appendMetric(metrics, label, value));
    appendEvidence(metrics, item.evidenceLink);
    details.append(metrics);
    card.append(details);
    appendImageGallery(card, item);
    wrap.append(card);
  });
}

function createStudentsBars() {
  const wrap = document.getElementById("students-bars");
  clear(wrap);
  const halaqat = window.DASHBOARD_DATA.halaqat || [];
  if (!wrap) return;
  if (!halaqat.length) {
    wrap.append(createEmptyState("لا توجد مقارنة طلاب لهذه الفترة"));
    return;
  }
  const max = Math.max(...halaqat.map((item) => numericValue(item.students)), 0);
  halaqat.forEach((item) => {
    const students = numericValue(item.students);
    const percent = max ? (students / max) * 100 : 0;
    const row = createEl("div", { className: "bar-item" });
    row.append(
      createEl("div", { className: "bar-head" }, [createEl("span", { text: item.name || "" }), createEl("span", { text: formatNumber(item.students) })]),
      createEl("div", { className: "bar-track" }, [createEl("div", { className: "bar-fill js-bar-fill", dataset: { width: percent } })])
    );
    wrap.append(row);
  });
}

function createStudentsDonut() {
  const chart = document.getElementById("students-donut");
  const legend = document.getElementById("students-donut-legend");
  if (!chart || !legend) return;
  clear(legend);
  const halaqat = window.DASHBOARD_DATA.halaqat || [];
  if (!halaqat.length) {
    chart.style.background = "#FFFFFF";
    legend.append(createEmptyState("لا توجد بيانات طلاب لهذه الفترة"));
    return;
  }
  const colors = ["#60C4E4", "#544F7D", "#323366", "rgba(96,196,228,.45)", "rgba(84,79,125,.38)", "rgba(50,51,102,.28)"];
  const total = halaqat.reduce((sum, item) => sum + numericValue(item.students), 0);
  let current = 0;
  const parts = [];
  halaqat.forEach((item, index) => {
    const angle = total ? (numericValue(item.students) / total) * 100 : 0;
    parts.push(`${colors[index % colors.length]} ${current}% ${current + angle}%`);
    current += angle;
  });
  chart.style.background = total ? `conic-gradient(${parts.join(", ")})` : "#FFFFFF";
  halaqat.forEach((item, index) => {
    legend.append(
      createEl("div", { className: "legend-item" }, [
        createEl("div", { className: "legend-info" }, [
          createEl("span", { className: "legend-dot", attrs: { style: `background:${colors[index % colors.length]}` } }),
          createEl("span", { className: "legend-name", text: item.name || "" })
        ]),
        createEl("span", { className: "legend-value", text: formatNumber(item.students) })
      ])
    );
  });
}

function createQuickSummary() {
  const wrap = document.getElementById("quick-summary");
  clear(wrap);
  const list = window.DASHBOARD_DATA.quickSummary || [];
  if (!wrap) return;
  if (!list.length) {
    wrap.append(createEmptyState("لا يوجد ملخص متاح لهذه الفترة"));
    return;
  }
  list.forEach((item) => wrap.append(createEl("div", { className: "summary-item", text: item })));
  if (window.DASHBOARD_DATA.aggregationNote) {
    wrap.append(createEl("div", { className: "summary-item summary-item--note", text: window.DASHBOARD_DATA.aggregationNote }));
  }
}

function getProgramSortValue(item) {
  return numericValue(item.visitors) || numericValue(item.beneficiaries) || numericValue(item.participants) || numericValue(item.students) || 0;
}

function createPrograms() {
  const wrap = document.getElementById("programs-grid");
  clear(wrap);
  const programs = window.DASHBOARD_DATA.programs || [];
  if (!wrap) return;
  if (!programs.length) {
    wrap.append(createEmptyState("لا توجد برامج نوعية مضافة لهذه الفترة", "ستظهر البرامج النوعية هنا تلقائيًا عند تعبئة البيانات."));
    return;
  }
  [...programs].sort((a, b) => getProgramSortValue(b) - getProgramSortValue(a)).forEach((item) => {
    const card = createEl("article", { className: "program-card" });
    card.append(createEl("div", { className: "program-top" }, [createEl("h4", { text: item.name || "" })]));
    const quick = createEl("div", { className: "program-quick" });
    appendMetric(quick, "عدد المستفيدين", item.beneficiaries, "quick-metric");
    appendMetric(quick, "عدد الدارسين", item.students ?? item.participants, "quick-metric");
    appendMetric(quick, "ساعات البث", item.broadcastHours, "quick-metric");
    card.append(quick);
    const details = createEl("details", { className: "more-details" });
    details.append(createEl("summary", { text: "عرض التفاصيل" }));
    const metrics = createEl("div", { className: "program-metrics" });
    [
      ["عدد الزوار", item.visitors],
      ["عدد المستفيدين", item.beneficiaries],
      ["عدد الدارسين", item.students ?? item.participants],
      ["عدد المتطوعين", item.volunteers],
      ["عدد المعلمين", item.teachers],
      ["عدد المشرفين", item.supervisors],
      ["عدد الحلقات", item.halaqat],
      ["عدد ساعات البث", item.broadcastHours],
      ["عدد ساعات التطوع", item.volunteerHours],
      ["أصغر عمر", item.minAge],
      ["أكبر عمر", item.maxAge]
    ].forEach(([label, value]) => appendMetric(metrics, label, value));
    appendEvidence(metrics, item.evidenceLink);
    details.append(metrics);
    card.append(details);
    appendImageGallery(card, item);
    wrap.append(card);
  });
}

function createTests() {
  const wrap = document.getElementById("tests-box");
  clear(wrap);
  if (!wrap) return;
  const tests = window.DASHBOARD_DATA.tests || {};
  const hasTests = ["tested", "passed", "fullQuran"].some((field) => numericValue(tests[field]) > 0);
  const panel = wrap.closest(".panel");
  if (!hasTests) {
    if (panel) panel.hidden = true;
    return;
  }
  if (panel) panel.hidden = false;
  const grid = createEl("div", { className: "test-grid" });
  appendMetric(grid, "عدد المختبرين", tests.tested, "quick-metric");
  appendMetric(grid, "عدد المجتازين", tests.passed, "quick-metric");
  appendMetric(grid, "كامل القرآن", tests.fullQuran, "quick-metric");
  wrap.append(grid);
}

function setupMobileTabs() {
  const tabs = document.querySelectorAll(".mobile-tab");
  const sections = document.querySelectorAll(".mobile-section");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.tabTarget;
      tabs.forEach((item) => item.classList.remove("active"));
      tab.classList.add("active");
      sections.forEach((section) => section.classList.toggle("active-section", section.dataset.mobileTab === target));
    });
  });
}

function animateNumbers() {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  document.querySelectorAll(".js-animate-number").forEach((el) => {
    const target = Number(el.dataset.target || 0);
    if (!Number.isFinite(target)) return;
    const duration = 650;
    const startTime = performance.now();
    function update(now) {
      const progress = Math.min((now - startTime) / duration, 1);
      const value = target * progress;
      el.textContent = formatNumber(Math.round(value));
      if (progress < 1) requestAnimationFrame(update);
      else el.textContent = formatNumber(Math.round(target));
    }
    requestAnimationFrame(update);
  });
}

function animateBars() {
  document.querySelectorAll(".js-bar-fill").forEach((bar) => {
    const width = bar.dataset.width || 0;
    requestAnimationFrame(() => {
      bar.style.width = `${width}%`;
    });
  });
}

async function initDashboard() {
  document.body.classList.add("is-loading");
  if (window.DASHBOARD_READY) await window.DASHBOARD_READY;
  document.body.classList.remove("is-loading");
  createMonthsNav();
  createWeekTabs();
  showStatus();
  createHeader();
  createTopStats();
  createProgramsSummary();
  createHalaqat();
  createStudentsBars();
  createStudentsDonut();
  createQuickSummary();
  createPrograms();
  createTests();
  setupMobileTabs();
  animateNumbers();
  animateBars();
}

document.addEventListener("DOMContentLoaded", initDashboard);

