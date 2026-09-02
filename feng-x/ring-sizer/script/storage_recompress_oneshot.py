#!/usr/bin/env python3
"""One-shot Supabase storage recompress (v7 "hot cache, low-res").

Context: the `ring-measurements` bucket crossed the 1 GB free-tier quota.
The measurement pipeline never sees past ~1024px (SAM downscales internally),
so storing full-res user uploads buys nothing for re-measurement. This script
shrinks the existing objects in place:

  - photos/   -> 2048px long-edge JPEG q80   (validated measurement-safe)
  - results/  -> 1024px long-edge JPEG q80   (overlay, never re-measured)

Safety model (free tier has NO rollback):
  1. `backup` downloads every photos/ object to a local dir FIRST and leaves
     it pristine. That is the ultimate fallback for photos.
  2. Recompress encodes in memory, RE-DECODES to verify the bytes are a valid
     image, and only then overwrites. Never writes garbage over a good object.
  3. Photos are recompressed only if a verified local backup exists.
  4. skip-if-not-smaller: never write a candidate that isn't meaningfully
     smaller than what's already there (avoids re-encode bloat).

Subcommands:
    inventory                 read-only: count + bytes for photos/ + results/
    backup                    download all photos/ -> BACKUP_DIR (idempotent)
    test-mechanism            upload+overwrite+verify+delete a throwaway object
    recompress --prefix photos  --max-side 2048 [--apply]
    recompress --prefix results --max-side 1024 [--apply]

Without --apply, recompress is a DRY RUN (projects savings, writes nothing).

Requires SUPABASE_URL / SUPABASE_SERVICE_KEY in the environment.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web_demo.supabase_client import _get_client, BUCKET  # noqa: E402

BACKUP_DIR = ROOT / "input" / "supabase_archive"
PAGE_LIMIT = 100
JPEG_QUALITY = 80
MIN_GAIN = 0.95  # only write if candidate <= 95% of original size


# --------------------------------------------------------------------------- #
# storage helpers
# --------------------------------------------------------------------------- #
def _storage():
    client = _get_client()
    if client is None:
        print("ERROR: Supabase client not initialized "
              "(check SUPABASE_URL / SUPABASE_SERVICE_KEY).")
        sys.exit(1)
    return client.storage.from_(BUCKET)


def _obj_size(obj: dict) -> Optional[int]:
    md = obj.get("metadata") or {}
    return md.get("size") if md.get("size") is not None else obj.get("size")


def list_all(storage, folder: str) -> List[dict]:
    out: List[dict] = []
    offset = 0
    while True:
        resp = storage.list(folder, {"limit": PAGE_LIMIT, "offset": offset})
        if not resp:
            break
        # storage may return a placeholder row for the folder itself; drop dirs
        out.extend([o for o in resp if o.get("name") and _obj_size(o) is not None])
        if len(resp) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
    return out


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _overwrite(storage, path: str, data: bytes, content_type: str) -> None:
    """Overwrite an existing object in place. Tries update(), falls back to
    upload() with x-upsert."""
    opts = {"content-type": content_type, "cache-control": "3600"}
    try:
        storage.update(path, data, file_options=opts)
    except Exception:
        storage.upload(path, data,
                       file_options={**opts, "upsert": "true"})


# --------------------------------------------------------------------------- #
# encode
# --------------------------------------------------------------------------- #
def recompress_bytes(raw: bytes, max_side: int) -> Optional[bytes]:
    """Decode -> (optionally) downscale to max_side -> JPEG q80 -> re-decode
    verify. Returns new bytes, or None if decode/verify failed."""
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # drops alpha; BGR
    if img is None:
        return None
    h, w = img.shape[:2]
    long_side = max(h, w)
    if long_side > max_side:
        scale = max_side / long_side
        img = cv2.resize(img, (int(round(w * scale)), int(round(h * scale))),
                         interpolation=cv2.INTER_AREA)
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        return None
    out = enc.tobytes()
    # verify: the new bytes must decode back to a valid image
    if cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR) is None:
        return None
    return out


# --------------------------------------------------------------------------- #
# subcommands
# --------------------------------------------------------------------------- #
def cmd_inventory(_args) -> int:
    storage = _storage()
    grand = 0
    for folder in ("photos", "results", "feedback"):
        objs = list_all(storage, folder)
        total = sum(_obj_size(o) or 0 for o in objs)
        grand += total
        print(f"{folder}/: {len(objs)} objects, {_human(total)}")
    print(f"TOTAL (3 prefixes): {_human(grand)}")
    return 0


def cmd_backup(_args) -> int:
    storage = _storage()
    dest = BACKUP_DIR / "photos"
    dest.mkdir(parents=True, exist_ok=True)
    objs = list_all(storage, "photos")
    print(f"photos/: {len(objs)} objects to back up -> {dest}")
    done = skipped = failed = 0
    for i, o in enumerate(objs, 1):
        name = o["name"]
        size = _obj_size(o) or 0
        local = dest / name
        if local.exists() and local.stat().st_size == size:
            skipped += 1
            continue
        try:
            data = storage.download(f"photos/{name}")
            local.write_bytes(data)
            if local.stat().st_size != size:
                print(f"  [{i}] SIZE MISMATCH {name}: "
                      f"got {len(data)} expected {size}")
                failed += 1
                continue
            done += 1
            if done % 25 == 0:
                print(f"  ...{done} downloaded")
        except Exception as e:
            print(f"  [{i}] FAILED {name}: {e}")
            failed += 1
    print(f"backup done: {done} new, {skipped} already present, {failed} failed")
    return 1 if failed else 0


def cmd_test_mechanism(_args) -> int:
    storage = _storage()
    path = "photos/__recompress_selftest__.jpg"
    a = cv2.imencode(".jpg", np.full((64, 64, 3), 30, np.uint8))[1].tobytes()
    b = cv2.imencode(".jpg", np.full((64, 64, 3), 200, np.uint8))[1].tobytes()
    try:
        try:
            storage.remove([path])
        except Exception:
            pass
        storage.upload(path, a, file_options={"content-type": "image/jpeg"})
        _overwrite(storage, path, b, "image/jpeg")
        back = storage.download(path)
        ok = (back == b)
        print(f"overwrite-in-place {'OK' if ok else 'FAILED'} "
              f"(round-tripped {len(back)} bytes, expected {len(b)})")
        return 0 if ok else 1
    finally:
        try:
            storage.remove([path])
        except Exception:
            pass


def cmd_recompress(args) -> int:
    storage = _storage()
    prefix = args.prefix
    max_side = args.max_side
    apply = args.apply
    objs = list_all(storage, prefix)
    print(f"{prefix}/: {len(objs)} objects, target {max_side}px/q{JPEG_QUALITY}, "
          f"{'APPLY' if apply else 'DRY RUN'}")

    backup_photos = BACKUP_DIR / "photos"
    before = after = 0
    written = skipped_small = skipped_nobackup = failed = 0

    for i, o in enumerate(objs, 1):
        name = o["name"]
        if name.startswith("__recompress_selftest__"):
            continue
        size = _obj_size(o) or 0
        before += size
        path = f"{prefix}/{name}"

        # photos: require a verified local backup before destructive write
        if prefix == "photos":
            b = backup_photos / name
            if not (b.exists() and b.stat().st_size == size):
                skipped_nobackup += 1
                after += size
                continue

        try:
            raw = storage.download(path)
        except Exception as e:
            print(f"  [{i}] download FAILED {name}: {e}")
            failed += 1
            after += size
            continue

        new = recompress_bytes(raw, max_side)
        if new is None:
            print(f"  [{i}] decode/verify FAILED {name} — left untouched")
            failed += 1
            after += size
            continue

        if len(new) >= size * MIN_GAIN:
            skipped_small += 1
            after += size
            continue

        after += len(new)
        if apply:
            try:
                _overwrite(storage, path, new, "image/jpeg")
                written += 1
                if written % 25 == 0:
                    print(f"  ...{written} rewritten")
            except Exception as e:
                print(f"  [{i}] upload FAILED {name}: {e}")
                failed += 1
                after += size - len(new)  # revert projection
        else:
            written += 1  # would-write count in dry run

    verb = "rewrote" if apply else "would rewrite"
    print(f"\n{prefix}/ summary:")
    print(f"  {verb}:            {written}")
    print(f"  skipped (not smaller): {skipped_small}")
    if prefix == "photos":
        print(f"  skipped (no backup):   {skipped_nobackup}")
    print(f"  failed:                {failed}")
    print(f"  size: {_human(before)} -> {_human(after)} "
          f"({(1 - after / before) * 100:.1f}% smaller)" if before else "  size: 0")
    return 1 if failed else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inventory")
    sub.add_parser("backup")
    sub.add_parser("test-mechanism")
    r = sub.add_parser("recompress")
    r.add_argument("--prefix", required=True, choices=("photos", "results"))
    r.add_argument("--max-side", type=int, required=True)
    r.add_argument("--apply", action="store_true",
                   help="actually overwrite (default: dry run)")
    args = p.parse_args()
    return {
        "inventory": cmd_inventory,
        "backup": cmd_backup,
        "test-mechanism": cmd_test_mechanism,
        "recompress": cmd_recompress,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
