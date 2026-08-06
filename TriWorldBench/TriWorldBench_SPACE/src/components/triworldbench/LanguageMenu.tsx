"use client";

import React, { useEffect, useState } from "react";

type Language = "en" | "zh";

const STORAGE_KEY = "triworldbench-language";

function normalizeLanguage(value: string | null): Language {
  return value === "zh" ? "zh" : "en";
}

function applyLanguage(language: Language) {
  document.documentElement.setAttribute("data-twb-lang", language);
}

export function LanguageMenu() {
  const [language, setLanguage] = useState<Language>("en");

  useEffect(() => {
    const stored = normalizeLanguage(window.sessionStorage.getItem(STORAGE_KEY));
    setLanguage(stored);
    applyLanguage(stored);
  }, []);

  const chooseLanguage = (nextLanguage: Language) => {
    setLanguage(nextLanguage);
    window.sessionStorage.setItem(STORAGE_KEY, nextLanguage);
    applyLanguage(nextLanguage);
  };

  return (
    <div className="language-menu" role="group" aria-label="Language">
      <button
        type="button"
        className={language === "en" ? "is-active" : ""}
        aria-pressed={language === "en"}
        onClick={() => chooseLanguage("en")}
      >
        English
      </button>
      <button
        type="button"
        className={language === "zh" ? "is-active" : ""}
        aria-pressed={language === "zh"}
        onClick={() => chooseLanguage("zh")}
      >
        中文
      </button>
    </div>
  );
}
