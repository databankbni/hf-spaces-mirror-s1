from __future__ import annotations
import shutil, time, uuid
from pathlib import Path
from dataclasses import dataclass
from .sandbox import PatchSandbox, PatchResult

@dataclass
class RepairRecord:
    repair_id: str
    status: str
    reason: str
    changed_files: list[str]
    backup_dir: str = ""

class AutoRepairEngine:
    """
    AI is a proposer, not an executor.
    The engine only accepts a patch after sandbox validation/tests.
    """
    def __init__(self, project_root: str, backup_root: str="data/repair_backups"):
        self.root=Path(project_root).resolve()
        self.backups=Path(backup_root)
        self.backups.mkdir(parents=True,exist_ok=True)
        self.sandbox=PatchSandbox(str(self.root))

    def propose_and_test(self, patch: str, tests=None) -> tuple[RepairRecord,PatchResult]:
        rid=str(uuid.uuid4())
        result=self.sandbox.test(patch,tests=tests)
        status="approved" if result.passed else "rejected"
        return RepairRecord(rid,status,result.reason,result.changed_files),result

    def apply_approved(self, record: RepairRecord, sandbox_dir: str) -> RepairRecord:
        if record.status!="approved":
            raise RuntimeError("Only an approved repair can be applied")
        backup=self.backups/(record.repair_id)
        backup.mkdir(parents=True,exist_ok=True)
        # Backup only files the patch is allowed to change.
        for rel in record.changed_files:
            src=self.root/rel
            if src.exists() and src.is_file():
                dst=backup/rel; dst.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(src,dst)
        # Copy the tested versions from sandbox.
        tested=Path(sandbox_dir)/"project"
        for rel in record.changed_files:
            src=tested/rel
            dst=self.root/rel
            if src.exists():
                dst.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(src,dst)
        record.backup_dir=str(backup)
        record.status="applied"
        return record

    def rollback(self, record: RepairRecord):
        if not record.backup_dir:
            raise RuntimeError("No backup recorded")
        backup=Path(record.backup_dir)
        for rel in record.changed_files:
            src=backup/rel
            dst=self.root/rel
            if src.exists(): shutil.copy2(src,dst)
            elif dst.exists(): dst.unlink()
        record.status="rolled_back"
        return record
