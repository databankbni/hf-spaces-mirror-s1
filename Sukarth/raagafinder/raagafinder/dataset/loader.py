"""THE format adapter for the Indian Art Music Raga Recognition Dataset zip.

Discovered schema (see DATASET_NOTES.md):
    Carnatic layout (differs from Hindustani!):
        RagaDataset/Carnatic/features/<ragaid>/<Artist>/<Release>/<Track>/<Track>.<ext>
    exts: .pitch (time_s \t f0_hz, hop 4.4444 ms, 0.0 = unvoiced),
          .pitchSilIntrpPP (post-processed variant), .tonic (coarse Hz),
          .tonicFine (fine-tuned Hz), .flatSegNyas, .taniSegKNN
    RagaDataset/Carnatic/_info_/path_mbid_ragaid.json      mbid -> {path, mbid, ragaid}
        where path points at audio/ ("<...>/audio/<ragaid>/<Artist>/<Release>/<Track>/<Track>")
    RagaDataset/Carnatic/_info_/ragaId_to_ragaName_mapping.json  ragaid -> name

Join: metadata audio path -> replace "/audio/" with "/features/" -> that base
plus extensions are the feature files. Everything is streamed from the zip;
nothing is extracted to disk.
"""

import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import numpy as np
import pandas as pd

from raagafinder.config import DATASET_ZIP

CARNATIC_FEATURES_PREFIX = "RagaDataset/Carnatic/features/"
CARNATIC_INFO = "RagaDataset/Carnatic/_info_/"


@dataclass
class RecordingRecord:
    mbid: str
    raga_id: str
    raga_name: str
    artist: str
    release: str
    track: str
    files: dict  # ext_lowercase -> zip member name


class RagaDatasetLoader:
    def __init__(self, zip_path: Path = DATASET_ZIP):
        self.zf = zipfile.ZipFile(zip_path)
        self._raga_names = json.loads(
            self.zf.read(CARNATIC_INFO + "ragaId_to_ragaName_mapping.json")
        )
        meta = json.loads(self.zf.read(CARNATIC_INFO + "path_mbid_ragaid.json"))

        # Index feature members by (dir + stem) -> {ext_lower: member name}
        by_base: dict[str, dict[str, str]] = {}
        for name in self.zf.namelist():
            if not name.startswith(CARNATIC_FEATURES_PREFIX) or "__MACOSX" in name:
                continue
            p = PurePosixPath(name)
            if not p.suffix:
                continue
            base = str(p.parent / p.stem)
            by_base.setdefault(base, {})[p.suffix.lstrip(".").lower()] = name

        self.recordings: list[RecordingRecord] = []
        for mbid, entry in meta.items():
            base = entry["path"].replace("/audio/", "/features/")
            files = by_base.get(base)
            if not files:
                continue
            parts = PurePosixPath(base).parts
            # [RagaDataset, Carnatic, features, ragaid, artist, release, track, stem]
            raga_id = entry["ragaid"]
            self.recordings.append(
                RecordingRecord(
                    mbid=mbid,
                    raga_id=raga_id,
                    raga_name=self._raga_names.get(raga_id, raga_id),
                    artist=parts[4],
                    release=parts[5],
                    track=parts[6],
                    files=files,
                )
            )

    # -- data access ---------------------------------------------------------

    def read_pitch(
        self, rec: RecordingRecord, post_processed: bool = False
    ) -> tuple[np.ndarray, float]:
        """Return (f0_hz float64 array, hop_s). Unvoiced frames are 0.0."""
        ext = "pitchsilintrppp" if post_processed else "pitch"
        with self.zf.open(rec.files[ext]) as f:
            df = pd.read_csv(
                io.BufferedReader(f), sep=r"\s+", header=None, engine="c",
                dtype=np.float64, names=["t", "f0"],
            )
        t = df["t"].to_numpy()
        hop = float(np.median(np.diff(t[: min(len(t), 5000)])))
        return df["f0"].to_numpy(), hop

    def read_tonic(self, rec: RecordingRecord) -> float:
        """Fine-tuned tonic Hz (falls back to coarse .tonic)."""
        ext = "tonicfine" if "tonicfine" in rec.files else "tonic"
        return float(self.zf.read(rec.files[ext]).decode().strip())
