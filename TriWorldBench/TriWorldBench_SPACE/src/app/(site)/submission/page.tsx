import React from "react";
import { FaGithub } from "react-icons/fa";
import { LanguageMenu } from "@/components/triworldbench/LanguageMenu";
import { LocalizedMarkdown } from "@/components/triworldbench/LocalizedMarkdown";
import {
  getSubmissionGuideMeta,
  getSubmissionGuideNavItems,
  getSubmissionGuideSections,
} from "@/lib/data/submission-guide";
import { getSiteInfo } from "@/lib/data/site-info";
import { contentValue, hasLocalizedText, localized, type LocalizedText } from "@/lib/i18n";

export const dynamic = "force-dynamic";

function I18nText({ text }: { text?: LocalizedText }) {
  if (!hasLocalizedText(text)) return null;
  return <LocalizedMarkdown text={text} inline />;
}

function SectionHead({ number, title }: { number: string; title: LocalizedText }) {
  return (
    <div className="section-head">
      <span>{number}</span>
      <h2><I18nText text={title} /></h2>
    </div>
  );
}

export default function TriWorldSubmissionPage() {
  const pageNavItems = getSubmissionGuideNavItems();
  const sections = getSubmissionGuideSections();
  const siteInfo = getSiteInfo();
  const configuredGithubUrl = contentValue(siteInfo?.github_url);
  const githubUrl =
    configuredGithubUrl && configuredGithubUrl !== "#"
      ? configuredGithubUrl
      : "https://github.com/TriWorldBench/TriWorldBench";
  const meta = getSubmissionGuideMeta() || {
    eyebrowText: localized("Submission Portal", "提交入口"),
    titleText: localized("Submission Guide", "提交指南"),
    introText: localized("TriWorldBench submission requirements.", "TriWorldBench 提交要求。"),
    backLabelText: localized("Back to Benchmark", "返回基准页面"),
    backHref: "/",
  };

  return (
    <div data-page="triworldbench" className="twb-doc submission-guide">
      <header className="site-nav">
        <a className="brand" href="/#top">TriWorldBench</a>
        <nav aria-label="Submission guide sections">
          {pageNavItems.map((item) => (
            <a href={item.href} key={item.id}>
              <I18nText text={item.labelText} />
            </a>
          ))}
        </nav>
        <LanguageMenu />
      </header>

      <section id="top" className="twb-hero">
        <div className="twb-hero-bg" aria-hidden="true" />
        <div className="twb-hero-inner">
          <p className="eyebrow"><I18nText text={meta.eyebrowText} /></p>
          <h1><I18nText text={meta.titleText} /></h1>
          <div className="subtitle"><I18nText text={meta.introText} /></div>
          <div className="actions">
            <a className="hero-action-primary" href={meta.backHref}>
              <I18nText text={meta.backLabelText} />
            </a>
            <a className="hero-action-primary" href={githubUrl} target="_blank" rel="noreferrer">
              <FaGithub aria-hidden="true" size={16} />
              GitHub
            </a>
          </div>
        </div>
      </section>

      <main>
        {sections.map((section, index) => (
          <section className="section submission-guide-section" id={section.sectionKey} key={section.id}>
            <SectionHead number={String(index + 1).padStart(2, "0")} title={section.titleText} />
            <LocalizedMarkdown text={section.bodyText} />
          </section>
        ))}
      </main>
      <footer><I18nText text={meta.titleText} /></footer>
    </div>
  );
}
