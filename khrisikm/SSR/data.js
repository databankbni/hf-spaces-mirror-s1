(function () {
  const NOT_OBSERVED = "لم يتم الرصد";
  const NOT_APPLICABLE = "غير منطبق";
  const DEFAULT_INDEX = {
    schemaVersion: 1,
    defaultYear: 2026,
    defaultMonth: 1,
    defaultWeek: "week6",
    years: [],
    aggregationRules: {}
  };

  const params = new URLSearchParams(window.location.search);
  const selectedMonth = params.get("month") || String(DEFAULT_INDEX.defaultMonth);
  const selectedWeek = params.get("week") || DEFAULT_INDEX.defaultWeek;

  function dataUrl(path) {
    return new URL(path, window.location.href).toString();
  }

  async function fetchJson(path) {
    const response = await fetch(dataUrl(path), { cache: "no-cache" });
    if (!response.ok) {
      throw new Error(`تعذر تحميل الملف: ${path}`);
    }
    return response.json();
  }

  function toNumber(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : 0;
  }

  function isObserved(value) {
    return value !== undefined && value !== null && value !== "" && value !== NOT_OBSERVED && value !== NOT_APPLICABLE;
  }

  function hasRealData(data) {
    if (!data) return false;
    if ((data.halaqat || []).length > 0) return true;
    if ((data.programs || []).length > 0) return true;
    if ((data.images || []).length > 0) return true;
    return false;
  }

  function monthLabel(month) {
    return `شهر ${month}`;
  }

  function weekLabel(week) {
    const labels = {
      week1: "الأسبوع الأول",
      week2: "الأسبوع الثاني",
      week3: "الأسبوع الثالث",
      week4: "الأسبوع الرابع",
      week5: "الأسبوع الخامس",
      week6: "الأسبوع السادس",
      summary: "تراكمي"
    };
    return labels[week] || week;
  }

  function getYearIndex(index) {
    return (index.years || []).find((item) => item.year === index.defaultYear) || (index.years || [])[0] || { months: [] };
  }

  function getMonthMeta(index, month) {
    const year = getYearIndex(index);
    return (year.months || []).find((item) => String(item.month) === String(month));
  }

  function getWeekMeta(monthMeta, week) {
    return (monthMeta?.weeks || []).find((item) => item.key === week || String(item.week) === String(week));
  }

  function mergeEvidenceLinks(oldLink, newLink) {
    const links = [];

    function add(value) {
      if (!isObserved(value)) return;
      if (Array.isArray(value)) {
        value.forEach(add);
        return;
      }
      links.push(String(value));
    }

    add(oldLink);
    add(newLink);
    const unique = [...new Set(links)];
    return unique.length ? unique : NOT_OBSERVED;
  }

  function aggregateValue(oldValue, newValue, rule) {
    if (rule === "noAggregation") return isObserved(oldValue) ? oldValue : newValue;
    if (rule === "latest") return isObserved(newValue) ? newValue : oldValue;
    if (rule === "min") {
      if (!isObserved(oldValue)) return newValue;
      if (!isObserved(newValue)) return oldValue;
      return Math.min(toNumber(oldValue), toNumber(newValue));
    }
    if (rule === "max") {
      if (!isObserved(oldValue)) return newValue;
      if (!isObserved(newValue)) return oldValue;
      return Math.max(toNumber(oldValue), toNumber(newValue));
    }
    if (rule === "average") {
      return toNumber(oldValue) + toNumber(newValue);
    }
    if (rule === "sum" || !rule) {
      return toNumber(oldValue) + toNumber(newValue);
    }
    return isObserved(oldValue) ? oldValue : newValue;
  }

  function mergeByName(items, rules) {
    const map = new Map();

    items.forEach((item) => {
      const key = item.name || item.id || "بدون اسم";

      if (!map.has(key)) {
        map.set(key, {
          ...item,
          evidenceLink: mergeEvidenceLinks(null, item.evidenceLink)
        });
        return;
      }

      const row = map.get(key);
      Object.keys(item).forEach((field) => {
        if (field === "evidenceLink") {
          row.evidenceLink = mergeEvidenceLinks(row.evidenceLink, item.evidenceLink);
          return;
        }
        if (["name", "id", "badge", "images", "image", "mainImage", "notes", "description"].includes(field)) {
          if (!isObserved(row[field]) && isObserved(item[field])) row[field] = item[field];
          return;
        }
        row[field] = aggregateValue(row[field], item[field], rules[field]);
      });
      map.set(key, row);
    });

    return Array.from(map.values());
  }

  function buildSummary(dataList, title, note, rules) {
    const halaqat = mergeByName(dataList.flatMap((item) => item.halaqat || []), rules);
    const programs = mergeByName(dataList.flatMap((item) => item.programs || []), rules);
    const tests = dataList.reduce(
      (acc, item) => {
        acc.tested += toNumber(item.tests?.tested);
        acc.passed += toNumber(item.tests?.passed);
        acc.fullQuran += toNumber(item.tests?.fullQuran);
        return acc;
      },
      { tested: 0, passed: 0, fullQuran: 0 }
    );

    const totalHalaq = halaqat.reduce((sum, item) => sum + toNumber(item.halaqCount), 0);
    const totalTeachers = halaqat.reduce((sum, item) => sum + toNumber(item.teachers), 0);
    const totalStudents = halaqat.reduce((sum, item) => sum + toNumber(item.students), 0);
    const totalFaces = halaqat.reduce((sum, item) => sum + toNumber(item.memorizedFaces), 0);
    const totalReview = halaqat.reduce((sum, item) => sum + toNumber(item.reviewFaces), 0);
    const totalParts = halaqat.reduce((sum, item) => sum + toNumber(item.memorizedParts), 0);

    return {
      title: "إنتاجية التعليم الإلكتروني",
      subtitle: "مؤشرات وبرامج التعليم الإلكتروني",
      note,
      lastUpdate: title,
      footerText: "© التعليم الإلكتروني",
      topStats: [
        { label: "إجمالي الحلق", value: totalHalaq },
        { label: "إجمالي المعلمين", value: totalTeachers },
        { label: "إجمالي الطلاب", value: totalStudents },
        { label: "الأجزاء المحفوظة", value: totalParts }
      ],
      quickSummary: [
        `إجمالي الطلاب في جميع الحلق: ${totalStudents.toLocaleString("ar-SA")} طالبًا`,
        `إجمالي الأوجه المحفوظة: ${totalFaces.toLocaleString("ar-SA")} وجهًا`,
        `إجمالي أوجه المراجعة: ${totalReview.toLocaleString("ar-SA")} وجهًا`,
        `إجمالي الأجزاء المحفوظة: ${totalParts.toLocaleString("ar-SA")} جزءًا`
      ],
      halaqat,
      programs,
      tests,
      aggregationNote: ""
    };
  }

  function emptyData(note) {
    return {
      title: "إنتاجية التعليم الإلكتروني",
      subtitle: "مؤشرات وبرامج التعليم الإلكتروني",
      note,
      lastUpdate: NOT_OBSERVED,
      footerText: "© التعليم الإلكتروني",
      topStats: [],
      quickSummary: [],
      halaqat: [],
      programs: [],
      tests: { tested: 0, passed: 0, fullQuran: 0 }
    };
  }

  async function loadSelectedData(index) {
    const rules = index.aggregationRules || {};

    if (selectedMonth === "summary") {
      const year = getYearIndex(index);
      const dataList = [];
      for (const month of year.months || []) {
        if (!month.dataFile) continue;
        const data = await fetchJson(month.dataFile);
        if (hasRealData(data)) dataList.push(data);
      }
      return buildSummary(dataList, "الإحصائية التراكمية", "الإحصائية التراكمية لجميع الأشهر المسجلة", rules);
    }

    const monthMeta = getMonthMeta(index, selectedMonth);
    if (!monthMeta) return emptyData("لا توجد بيانات منشورة لهذه الفترة");

    if ((monthMeta.weeks || []).length) {
      if (selectedWeek === "summary") {
        if (monthMeta.key === "summer-productivity" && monthMeta.summaryDataFile) {
          return fetchJson(monthMeta.summaryDataFile);
        }
        const dataList = [];
        for (const week of monthMeta.weeks) {
          if (!week.dataFile) continue;
          const data = await fetchJson(week.dataFile);
          if (hasRealData(data)) dataList.push(data);
        }
        if (dataList.length) {
          if (monthMeta.key === "summer-productivity") {
            return buildSummary(dataList, "تراكمي", "تراكمي للأسبوع الأول والثاني", rules);
          }
          return buildSummary(dataList, `تجميع ${monthLabel(selectedMonth)}`, `تجميع ${monthLabel(selectedMonth)} لجميع الأسابيع المسجلة`, rules);
        }
        if (monthMeta.summaryDataFile) return fetchJson(monthMeta.summaryDataFile);
      }

      const weekMeta = getWeekMeta(monthMeta, selectedWeek) || getWeekMeta(monthMeta, index.defaultWeek);
      if (weekMeta?.dataFile) return fetchJson(weekMeta.dataFile);
    }

    if (monthMeta.dataFile) return fetchJson(monthMeta.dataFile);
    return emptyData("لا توجد بيانات منشورة لهذا الشهر حتى الآن");
  }

  function exposeNavigation(index) {
    const year = getYearIndex(index);
    window.DASHBOARD_INDEX = index;
    window.DASHBOARD_NAV = {
      selectedMonth,
      selectedWeek,
      months: year.months || [],
      monthMeta: getMonthMeta(index, selectedMonth),
      monthLabel,
      weekLabel
    };
  }

  window.DASHBOARD_READY = (async function () {
    try {
      window.DASHBOARD_LOADING = true;
      const index = await fetchJson("data/index.json").catch(() => DEFAULT_INDEX);
      exposeNavigation(index);
      window.DASHBOARD_DATA = await loadSelectedData(index);
      window.DASHBOARD_ERROR = null;
    } catch (error) {
      console.error(error);
      window.DASHBOARD_DATA = emptyData("حدث خطأ أثناء تحميل البيانات");
      window.DASHBOARD_ERROR = error.message || "تعذر تحميل البيانات";
    } finally {
      window.DASHBOARD_LOADING = false;
    }
  })();
})();
