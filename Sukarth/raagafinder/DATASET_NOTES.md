# Dataset notes (schema discovery)

Source: "Indian Art Music Raga Recognition Dataset (features)", Zenodo 7278506,
CC-BY 4.0, zip MD5 `5dfc26dd1c2652ab75a62faec7f45f08` (3.36 GiB compressed,
14.38 GB uncompressed, 11,280 members incl. `__MACOSX` junk).

## Verified invariants (Carnatic subset = CMD)
- 480 recordings, 40 unique ragas, exactly 12 recordings per raga.
- Every recording has all six feature files, including `.pitch` and `.tonicFine`.
- 64 unique artists; 183 unique (artist, release) "concert" groups.
  Artist skew is severe (Sanjay Subrahmanyan 61, T.M. Krishna 33, KVN 26)
  → GroupKFold by (artist, release); artist-grouped score as diagnostic.

## Layout (Carnatic — Hindustani differs!)
```
RagaDataset/Carnatic/features/<ragaid>/<Artist>/<Release>/<Track>/<Track>.<ext>
RagaDataset/Carnatic/_info_/path_mbid_ragaid.json      # mbid -> {path(audio!), mbid, ragaid}
RagaDataset/Carnatic/_info_/ragaId_to_ragaName_mapping.json  # 71 entries; CMD uses 40
```
Join: metadata `path` (points at `audio/`) → replace `/audio/` with
`/features/` → base path of the six feature files. Hindustani instead puts
`<Track>_<mbid>.<ext>` directly in the release dir (no track dir, mbid suffix).

## File formats
- `.pitch`: two-column text `time_s \t f0_hz`, hop = 4.4444 ms (196/44100),
  unvoiced = `0.0` (Melodia). ~3-35 MB per recording.
- `.pitchSilIntrpPP`: post-processed variant (silence-interpolated), scientific
  notation, ~2x size. Training reads raw `.pitch` (matches app-time Melodia
  output); any gap interpolation is done in this project's own feature code.
- `.tonic`: coarse tonic Hz (sometimes integer). `.tonicFine`: fine-tuned tonic
  Hz. `.tonicFine` is the one used.
- `.flatSegNyas` / `.taniSegKNN`: nyas/tani segment annotations (unused in v1).

## Notes
- Raga names use IAST diacritics (Mōhanaṁ, Śankarābharaṇaṁ, ...): keep UTF-8
  everywhere; Windows console needs PYTHONIOENCODING=utf-8.
- Sample check: Mōhanaṁ / Sumithra_Vasudev: 584,295 frames, 72.9% voiced,
  tonic 191.3 Hz.
- Nothing is extracted to disk: loader streams members from the zip.
