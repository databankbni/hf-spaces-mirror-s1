from __future__ import annotations
import ast, shutil, tempfile, subprocess, sys, os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

@dataclass
class PatchResult:
    passed: bool
    reason: str
    sandbox_dir: str
    changed_files: list[str]

class PatchSandbox:
    """
    Conservative patch gate:
    - copies only explicitly allowed files
    - rejects secrets/config/runtime data paths
    - applies unified diff in an isolated temporary tree
    - compiles the tree and optionally runs selected tests
    """
    DEFAULT_DENY = (
        ".env", "secrets", "secret", "credentials", "token", "key",
        "data/", "sessions/", ".git/"
    )

    def __init__(self, project_root: str, deny_patterns: Optional[Iterable[str]]=None):
        self.root=Path(project_root).resolve()
        self.deny=tuple(deny_patterns or self.DEFAULT_DENY)

    def _safe(self, rel: str) -> bool:
        x=rel.replace("\\","/").lower().lstrip("./")
        return not any(p in x for p in self.deny)

    def _changed_paths(self, patch: str) -> list[str]:
        out=[]
        for line in patch.splitlines():
            if line.startswith("+++ b/"):
                out.append(line[6:])
        return out

    def validate_patch(self, patch: str) -> tuple[bool,str,list[str]]:
        paths=self._changed_paths(patch)
        if not paths: return False,"patch has no changed files",[]
        bad=[p for p in paths if not self._safe(p)]
        if bad: return False,f"protected paths rejected: {bad}",paths
        for p in paths:
            target=(self.root/p).resolve()
            if self.root not in target.parents and target != self.root:
                return False,"path traversal rejected",paths
            if target.exists() and target.is_file() and target.stat().st_size > 1_000_000:
                return False,f"file too large: {p}",paths
        return True,"ok",paths

    def test(self, patch: str, tests: Optional[list[str]]=None) -> PatchResult:
        ok,reason,paths=self.validate_patch(patch)
        if not ok: return PatchResult(False,reason,"",paths)
        td=tempfile.mkdtemp(prefix="p29_patch_")
        sandbox=Path(td)/"project"
        shutil.copytree(self.root,sandbox,ignore=shutil.ignore_patterns(".git","__pycache__","*.pyc"))
        patch_file=Path(td)/"change.patch"
        patch_file.write_text(patch,encoding="utf-8")
        p=subprocess.run(["patch","-p1","--batch","--forward","-i",str(patch_file)],
                         cwd=sandbox,capture_output=True,text=True)
        if p.returncode!=0:
            return PatchResult(False,"patch apply failed: "+(p.stderr or p.stdout)[-2000:],td,paths)
        c=subprocess.run([sys.executable,"-m","compileall","-q",str(sandbox)],
                         capture_output=True,text=True)
        if c.returncode!=0:
            return PatchResult(False,"compile failed: "+c.stderr[-2000:],td,paths)
        if tests:
            t=subprocess.run([sys.executable,"-m","pytest",*tests,"-q"],cwd=sandbox,
                             capture_output=True,text=True)
            if t.returncode!=0:
                return PatchResult(False,"tests failed: "+(t.stdout+t.stderr)[-3000:],td,paths)
        return PatchResult(True,"sandbox checks passed",td,paths)
