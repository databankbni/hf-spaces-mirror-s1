from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import __version__
from .config import RunConfig, key_for, load_dotenv
from .report import write_report
from .trial import metrics, run_suite


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="arbiter",
        description="Reproduce web bug reports with an LLM actor, then have an independent "
                    "judge confirm or reject the claim from the evidence.")
    p.add_argument("--version", action="version", version="arbiter " + __version__)
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the benchmark")
    run.add_argument("--only", help="comma separated bug ids, default is all of them")
    run.add_argument("--trials", type=int, default=3, help="repeats per bug, for the flakiness score")
    run.add_argument("--provider", default="gemini", choices=["gemini", "openai", "anthropic", "mock"])
    run.add_argument("--actor-model", default="gemini-3.5-flash-lite")
    run.add_argument("--rpm", type=float, default=12.0,
                     help="client side pacing, requests per minute across all calls. "
                          "Free tiers throttle hard, so this matters more than retries.")
    run.add_argument("--judge-provider", default="", help="defaults to the actor's provider")
    run.add_argument("--judge-model", default="gemini-3.5-flash",
                     help="point this at a different model to strengthen judge independence")
    run.add_argument("--record", action="store_true",
                     help="save every model exchange to traces/ so the run can be replayed offline")
    run.add_argument("--headed", action="store_true", help="show the browser window")
    run.add_argument("--video", action="store_true", help="record webm video of each trial")
    run.add_argument("--out", default="docs", help="where the report is written")
    run.add_argument("--bugs-dir", default="benchmark/bugs")
    run.add_argument("--apps-dir", default="benchmark/apps")
    run.add_argument("--evidence-dir", default="evidence")
    run.add_argument("--trace-dir", default="traces")

    rej = sub.add_parser("rejudge",
                         help="re-run only the judge over evidence already on disk")
    rej.add_argument("--only", help="comma separated bug ids")
    rej.add_argument("--all", action="store_true",
                     help="re-judge every trial, not just the unresolved ones")
    rej.add_argument("--provider", default="gemini", choices=["gemini", "openai", "anthropic", "mock"])
    rej.add_argument("--judge-provider", default="")
    rej.add_argument("--judge-model", default="gemini-3.5-flash-lite")
    rej.add_argument("--rpm", type=float, default=8.0)
    rej.add_argument("--record", action="store_true",
                     help="record the review traffic so an offline replay covers these trials too")
    rej.add_argument("--out", default="docs")
    rej.add_argument("--bugs-dir", default="benchmark/bugs")
    rej.add_argument("--evidence-dir", default="evidence")
    rej.add_argument("--trace-dir", default="traces")

    aud = sub.add_parser("judge-audit",
                         help="adversarial check: judge each run's evidence against a "
                              "report it does not match")
    aud.add_argument("--only", help="comma separated bug ids")
    aud.add_argument("--provider", default="gemini", choices=["gemini", "openai", "anthropic", "mock"])
    aud.add_argument("--judge-provider", default="")
    aud.add_argument("--judge-model", default="gemini-3.5-flash-lite")
    aud.add_argument("--rpm", type=float, default=8.0)
    aud.add_argument("--out", default="docs")
    aud.add_argument("--bugs-dir", default="benchmark/bugs")
    aud.add_argument("--evidence-dir", default="evidence")

    smk = sub.add_parser("smoke", help="drive the benchmark with scripted actions, no API key needed")
    smk.add_argument("--apps-dir", default="benchmark/apps")
    smk.add_argument("--headed", action="store_true")

    chk = sub.add_parser("check", help="verify the environment before a real run")
    chk.add_argument("--provider", default="gemini", choices=["gemini", "openai", "anthropic", "mock"])
    chk.add_argument("--actor-model", default="gemini-3.5-flash-lite")
    chk.add_argument("--judge-model", default="gemini-3.5-flash")
    return p


def cmd_check(args: argparse.Namespace) -> int:
    ok = True
    print("arbiter {0}".format(__version__))

    try:
        import playwright
        print("  [ok]   playwright is installed")
    except ImportError:
        print("  [fail] playwright is missing. Run: pip install -r requirements.txt")
        return 1
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            page = b.new_page()
            page.set_content("<h1 data-testid='x'>hello</h1>")
            title = page.text_content("[data-testid=x]")
            b.close()
        print("  [ok]   chromium launches and renders ({0!r})".format(title))
    except Exception as exc:
        print("  [fail] chromium could not start: {0}".format(str(exc)[:200]))
        print("         Run: python -m playwright install chromium")
        ok = False

    for mod in ("cv2", "numpy", "PIL", "yaml", "requests"):
        try:
            __import__(mod)
            print("  [ok]   {0}".format(mod))
        except ImportError:
            print("  [fail] {0} is missing".format(mod))
            ok = False

    key = key_for(args.provider)
    if args.provider == "mock":
        print("  [ok]   mock provider needs no key")
    elif not key:
        print("  [fail] no API key found for provider {0}. Copy .env.example to .env "
              "and fill it in.".format(args.provider))
        ok = False
    else:
        print("  [ok]   API key found ({0}...{1})".format(key[:6], key[-4:]))
        from .llm.base import build_provider
        for role, model in (("actor", args.actor_model), ("judge", args.judge_model)):
            try:
                reply = build_provider(args.provider, model, key).complete(
                    "You are a test harness.", "Reply with the single word: ready")
                print("  [ok]   {0} model {1} answered {2!r} ({3} prompt tokens)".format(
                    role, model, reply.text.strip()[:40], reply.usage.prompt_tokens))
            except Exception as exc:
                print("  [fail] {0} model {1} failed: {2}".format(role, model, str(exc)[:260]))
                ok = False
        if args.actor_model == args.judge_model:
            print("  [warn] actor and judge share a model. The judge still cannot see the "
                  "actor's reasoning, but different models make the review more independent.")

    print("\n{0}".format("environment looks good" if ok else "fix the failures above first"))
    return 0 if ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    cfg = RunConfig(
        provider=args.provider, actor_model=args.actor_model,
        judge_provider=args.judge_provider, judge_model=args.judge_model,
        trials=args.trials, rpm=args.rpm,
        headless=not args.headed, record=args.record, video=args.video,
        bugs_dir=args.bugs_dir, apps_dir=args.apps_dir, out_dir=args.out,
        evidence_dir=args.evidence_dir, trace_dir=args.trace_dir, only=args.only)

    if cfg.provider != "mock" and not key_for(cfg.provider):
        print("No API key for provider {0}. Copy .env.example to .env and add your key, "
              "or run with --provider mock to replay recorded traces.".format(cfg.provider))
        return 1

    from .llm.base import set_rate_limit
    set_rate_limit(cfg.rpm)

    suite = run_suite(cfg)
    paths = write_report(suite, cfg.out_dir)
    m = metrics(suite)

    print("\n" + "=" * 66)
    print("seeded bugs reproduced   {0}/{1} ({2:.0%})".format(
        m["reproduced"], m["seeded_bugs"], m["reproduction_rate"]))
    print("false positives          {0}/{1} controls".format(m["false_positives"], m["controls"]))
    print("overall accuracy         {0:.0%}".format(m["accuracy"]))
    print("actor claimed            {0} trials".format(m["actor_claimed"]))
    print("judge confirmed          {0} trials".format(m["judge_confirmed"]))
    print("judge rejected           {0} trials ({1:.0%} of claims were overclaims)".format(
        m["judge_rejected"], m["overclaim_rate"]))
    print("never resolved           {0} trials (judge unavailable or unsure)".format(
        m["unresolved"]))
    print("cost                     ${0:.4f} over {1} calls".format(
        m["cost"]["usd"], m["cost"]["calls"]))
    print("=" * 66)
    print("report  {0}".format(paths["html"]))
    print("data    {0}".format(paths["json"]))
    return 0


def cmd_rejudge(args: argparse.Namespace) -> int:
    from .llm.base import set_rate_limit
    from .rejudge import rejudge

    cfg = RunConfig(provider=args.provider, judge_provider=args.judge_provider,
                    judge_model=args.judge_model, rpm=args.rpm, bugs_dir=args.bugs_dir,
                    evidence_dir=args.evidence_dir, trace_dir=args.trace_dir,
                    out_dir=args.out, only=args.only, record=args.record)
    if cfg.effective_judge_provider != "mock" and not key_for(cfg.effective_judge_provider):
        print("No API key for provider {0}.".format(cfg.effective_judge_provider))
        return 1
    set_rate_limit(cfg.rpm)
    suite = rejudge(cfg, only_unresolved=not args.all)
    if not suite.results:
        print("no evidence found under {0}. Run the benchmark first.".format(cfg.evidence_dir))
        return 1
    paths = write_report(suite, cfg.out_dir)
    m = metrics(suite)
    print("\n" + "=" * 66)
    print("seeded bugs reproduced   {0}/{1} ({2:.0%})".format(
        m["reproduced"], m["seeded_bugs"], m["reproduction_rate"]))
    print("false positives          {0}/{1} controls".format(m["false_positives"], m["controls"]))
    print("overall accuracy         {0:.0%}".format(m["accuracy"]))
    print("actor claimed            {0} trials".format(m["actor_claimed"]))
    print("judge confirmed          {0} trials".format(m["judge_confirmed"]))
    print("judge rejected           {0} trials ({1:.0%} of claims were overclaims)".format(
        m["judge_rejected"], m["overclaim_rate"]))
    print("never resolved           {0} trials".format(m["unresolved"]))
    print("=" * 66)
    print("report  {0}".format(paths["html"]))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "check":
        return cmd_check(args)
    if args.command == "judge-audit":
        from .audit import run_audit
        from .llm.base import set_rate_limit
        cfg = RunConfig(provider=args.provider, judge_provider=args.judge_provider,
                        judge_model=args.judge_model, rpm=args.rpm, bugs_dir=args.bugs_dir,
                        evidence_dir=args.evidence_dir, out_dir=args.out, only=args.only)
        if cfg.effective_judge_provider != "mock" and not key_for(cfg.effective_judge_provider):
            print("No API key for provider {0}.".format(cfg.effective_judge_provider))
            return 1
        set_rate_limit(cfg.rpm)
        run_audit(cfg)
        return 0
    if args.command == "rejudge":
        return cmd_rejudge(args)
    if args.command == "smoke":
        from .smoke import run_smoke
        return run_smoke(args.apps_dir, headless=not args.headed)
    return 1


if __name__ == "__main__":
    sys.exit(main())
