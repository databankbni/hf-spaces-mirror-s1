"""P29 phase-15 composition root.

The legacy runtime remains available, but all new section traffic can now use one
shared RuntimeIntegration instance. External adapters are registered by the host.
"""
from __future__ import annotations

from .config.settings import settings
from .plugins.registry import PluginRegistry
from .plugins.builtin import register_builtins
from .plugins.manager import SectionManager
from .events.bus import EventBus
from .runtime.integration import RuntimeIntegration
from .ai.http_adapters import register_default_http_adapters
from .release.readiness import ProductionReadiness
from .release.backup import BackupManager
from .release.release import ReleaseManifest
from .release.go_live import GoLiveGate


class App:
    def __init__(self, legacy_db=None, project_root="."):
        self.settings = settings
        self.plugins = PluginRegistry()
        register_builtins(self.plugins)
        self.events = EventBus()
        self.runtime = RuntimeIntegration(
            db=legacy_db,
            db_path=settings.db_path,
            project_root=project_root,
        )
        register_default_http_adapters(self.runtime.ai)
        self.sections = SectionManager(self.plugins)
        self.readiness = ProductionReadiness(self.runtime, project_root)
        self.backups = BackupManager(settings.data_dir, "backups")
        self.release_manifest_builder = ReleaseManifest(project_root)
        self.go_live = GoLiveGate(self)

    def discover_plugins(self):
        return self.plugins.discover()

    def register_ai_provider(self, provider, adapter):
        self.runtime.register_ai_provider(provider, adapter)

    def register_publisher(self, target, adapter):
        self.runtime.register_publisher(target, adapter)

    def health(self):
        return self.runtime.health_snapshot()

    def metrics(self):
        return self.runtime.metrics_snapshot()

    def controls(self):
        return self.runtime.control_snapshot()

    def production_readiness(self, require_secrets=()):
        return self.readiness.evaluate(tuple(require_secrets))

    def create_backup(self, databases=None, label="release"):
        dbs = databases or [self.settings.db_path]
        return self.backups.create(dbs, label=label)

    def release_manifest(self, version="29.0", phase="24", output=None):
        return self.release_manifest_builder.build(version=version, phase=phase, output=output)

    def go_live_report(self, require_telegram=False):
        return self.go_live.evaluate(require_telegram=require_telegram)
