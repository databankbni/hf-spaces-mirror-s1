from __future__ import annotations
import hashlib, json, os, sqlite3, tempfile, time
from dataclasses import dataclass, asdict
from pathlib import Path

@dataclass(frozen=True)
class BackupResult:
    ok: bool
    path: str
    sha256: str
    size: int
    databases: tuple[str, ...]
    verified: bool
    error: str = ""

class BackupManager:
    """Atomic, verifiable backups for P29 SQLite state and release metadata."""
    def __init__(self, data_dir: str = "data", backup_dir: str = "backups"):
        self.data_dir = Path(data_dir)
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sha256(path: Path) -> str:
        h=hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda:f.read(1024*1024), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _sqlite_backup(src: Path, dst: Path) -> None:
        src_con = sqlite3.connect(src, timeout=30)
        dst_con = sqlite3.connect(dst)
        try:
            src_con.execute("PRAGMA integrity_check")
            src_con.backup(dst_con)
        finally:
            dst_con.close(); src_con.close()

    def create(self, databases: list[str] | tuple[str, ...], label: str = "release") -> BackupResult:
        stamp=time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        final=self.backup_dir / f"p29-{label}-{stamp}-{os.getpid()}.bak"
        temp=Path(tempfile.mktemp(prefix=final.name+".", dir=str(self.backup_dir)))
        dbs=[]
        try:
            with temp.open("wb") as out:
                manifest={"created_at":time.time(),"label":label,"databases":[]}
                for raw in databases:
                    p=Path(raw)
                    if not p.exists():
                        continue
                    if p.suffix.lower() not in {".sqlite3",".sqlite",".db"}:
                        continue
                    dbtmp=Path(tempfile.mktemp(prefix="db-", suffix=p.suffix))
                    try:
                        self._sqlite_backup(p, dbtmp)
                        blob=dbtmp.read_bytes()
                    finally:
                        dbtmp.unlink(missing_ok=True)
                    entry={"path":str(p),"name":p.name,"sha256":hashlib.sha256(blob).hexdigest(),"size":len(blob)}
                    manifest["databases"].append(entry); dbs.append(str(p))
                    name_bytes=json.dumps(entry,sort_keys=True).encode()
                    out.write(len(name_bytes).to_bytes(4,"big")); out.write(name_bytes)
                    out.write(len(blob).to_bytes(8,"big")); out.write(blob)
                m=json.dumps(manifest,ensure_ascii=False,sort_keys=True).encode()
                out.write(b"P29M"); out.write(len(m).to_bytes(8,"big")); out.write(m)
                out.flush(); os.fsync(out.fileno())
            os.replace(temp,final)
            digest=self._sha256(final)
            verified=self.verify(final)
            return BackupResult(verified,str(final),digest,final.stat().st_size,tuple(dbs),verified)
        except Exception as exc:
            temp.unlink(missing_ok=True)
            return BackupResult(False,str(final),"",0,tuple(dbs),False,str(exc))

    def verify(self, backup_path: str | Path) -> bool:
        p=Path(backup_path)
        if not p.exists() or p.stat().st_size < 12:return False
        raw=p.read_bytes()
        pos=0; seen=[]
        try:
            while pos < len(raw):
                if raw[pos:pos+4] == b"P29M":
                    n=int.from_bytes(raw[pos+4:pos+12],"big"); m=json.loads(raw[pos+12:pos+12+n]);
                    if m.get("schema") not in (None,): pass
                    return bool(m.get("databases",[]) or m.get("label"))
                n=int.from_bytes(raw[pos:pos+4],"big"); pos+=4
                entry=json.loads(raw[pos:pos+n]); pos+=n
                size=int.from_bytes(raw[pos:pos+8],"big"); pos+=8
                blob=raw[pos:pos+size]; pos+=size
                if len(blob)!=size or hashlib.sha256(blob).hexdigest()!=entry.get("sha256"):return False
                seen.append(blob)
            return False
        except Exception:return False


    def restore(self, backup_path: str | Path, target_dir: str | Path, overwrite: bool = False) -> list[str]:
        """Restore verified SQLite images into target_dir; refuses overwrite by default."""
        backup=Path(backup_path); target=Path(target_dir); target.mkdir(parents=True, exist_ok=True)
        if not self.verify(backup): raise RuntimeError("backup verification failed")
        raw=backup.read_bytes(); pos=0; restored=[]
        while pos < len(raw):
            if raw[pos:pos+4] == b"P29M": break
            n=int.from_bytes(raw[pos:pos+4],"big"); pos+=4
            entry=json.loads(raw[pos:pos+n]); pos+=n
            size=int.from_bytes(raw[pos:pos+8],"big"); pos+=8
            blob=raw[pos:pos+size]; pos+=size
            name=Path(entry["name"]).name
            dest=target/name
            if dest.exists() and not overwrite: raise FileExistsError(str(dest))
            tmp=dest.with_suffix(dest.suffix+".restore.tmp")
            tmp.write_bytes(blob); os.replace(tmp,dest)
            with sqlite3.connect(dest) as c:
                row=c.execute("PRAGMA integrity_check").fetchone()
                if not row or row[0] != "ok":
                    dest.unlink(missing_ok=True); raise RuntimeError(f"restored database failed integrity check: {dest}")
            restored.append(str(dest))
        return restored

    def latest(self) -> Path | None:
        items=sorted(self.backup_dir.glob("p29-*.bak"), key=lambda p:p.stat().st_mtime, reverse=True)
        return items[0] if items else None
