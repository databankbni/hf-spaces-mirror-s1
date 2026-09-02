# ClimaFlora Media v2.4

Media v2.4 separates botanical media storage from source-specific ingestion.
Images remain descriptive only and never participate in ClimaFlora scoring.

## Storage contract

The deployed sidecar remains `data/climaflora_media_v2.sqlite` and contains two application-facing tables.

### `media_taxon`

One row exists for every canonical ClimaFlora taxon.

| column | meaning |
| --- | --- |
| `taxon_id` | canonical ClimaFlora taxon identifier; primary key |
| `scientific_name` | canonical catalog scientific name |
| `image_count` | number of retained images, from 0 to 3 |
| `status` | `ready` when at least one image is retained, otherwise `no_image` |
| `updated_at` | UTC normalization timestamp |

For the current canonical catalog, the required row count is **420,532**.

### `plant_image_asset`

Zero to three rows may exist for one taxon. Source-specific collectors can contribute candidates, but the runtime consumes one normalized table.

| column | meaning |
| --- | --- |
| `taxon_id` | canonical taxon identifier |
| `position` | deterministic rank 1, 2 or 3 |
| `is_primary` | 1 only for position 1 |
| `thumbnail_url` | HTTPS display thumbnail |
| `image_url` | HTTPS larger image |
| `source` | source provider identifier |
| `source_record_id` / `source_dataset_id` | source provenance |
| `license` / `license_raw` | normalized and original licence information |
| `author` | credited author when supplied |
| `attribution_url` | source page carrying provenance/licence |
| `quality_rank` | deterministic source-builder quality rank |
| `verified_taxon_name` | scientific name used for exact source matching |

The `(taxon_id, position)` pair is unique. No taxon may retain more than three image rows.

## Ranking

The finalizer ranks all already-validated candidates for a taxon by:

1. descending `quality_rank`;
2. previous primary status as a deterministic secondary key;
3. descending `asset_id` as the final deterministic tie-break.

Only the top three rows are retained. Position 1 becomes the primary image used by existing cards. This keeps the current API/frontend compatible while making positions 2 and 3 available for later plant-sheet galleries.

## Licensing and provenance

The finalizer does not loosen any source policy. It rejects a build when a retained candidate has a blank licence, explicit NC/ND/All Rights Reserved terms, non-HTTPS media/source URLs, or a taxon identifier absent from the canonical catalog. The explicit project exception `Pl@ntNet : licence non renseignée` remains supported.

Every retained asset keeps source, author, licence, source record/dataset identifiers and attribution URL. Source priority is therefore an ingestion concern rather than a frontend concern.

## Build order

1. Pl@ntNet/GBIF + WFO base build;
2. Australian Plant Image Index / ALA;
3. Dryades / Flora d’Italia;
4. Wikimedia Commons;
5. Media v2.4 normalization into `media_taxon` + top-three `plant_image_asset`.

Future image providers only need to emit validated `plant_image_asset` candidates before step 5. They do not require a new frontend storage contract.

## Required invariants

A production Media v2.4 build is rejected unless:

- `media_taxon` contains exactly the canonical catalog row count;
- every media asset belongs to one `media_taxon` row;
- `image_count` is between 0 and 3;
- each `(taxon_id, position)` is unique;
- position 1 is the only primary image;
- no taxon retains more than three assets;
- all retained licences and URLs pass the project media policy;
- `image_scoring_effect=false`.
