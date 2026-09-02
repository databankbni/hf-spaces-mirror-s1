import argparse
import json
from core.app import App

def main():
    parser=argparse.ArgumentParser(description="P29 runtime")
    parser.add_argument("--readiness", action="store_true")
    parser.add_argument("--manifest", action="store_true")
    parser.add_argument("--go-live", action="store_true")
    parser.add_argument("--require-telegram", action="store_true")
    args=parser.parse_args()
    app=App(project_root=".")
    if args.readiness:
        report=app.production_readiness()
        print(json.dumps({"ready":report.ready,"findings":[f.__dict__ for f in report.findings]}, ensure_ascii=False))
        return 0 if report.ready else 2
    if args.manifest:
        print(json.dumps(app.release_manifest(phase="24"), ensure_ascii=False))
        return 0
    if args.go_live:
        report = app.go_live_report(require_telegram=args.require_telegram)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["ready"] else 2
    print("P29 Phase 24 final runtime ready; legacy callbacks remain enabled for compatibility.")
    print("plugins:", ", ".join(app.discover_plugins()))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
