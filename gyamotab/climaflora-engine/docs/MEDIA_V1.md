# ClimaFlora — Média v1 Wikimedia Commons

## Statut

Cette couche est strictement descriptive. Elle ne participe jamais à la sélection des candidats, au score climat, au score sol, aux vetos, à la confiance ni au tri scientifique.

- Runtime cible : `0.9.43`
- Catalogue scientifique : `2.0.0` inchangé
- Moteur de score : `climaflora-score-0.6.0` inchangé
- Source média v1 : Wikimedia Commons via Wikidata P225/P18 + API Commons
- Base média : `data/climaflora_media_v1.sqlite`
- Binaires image dans SQLite : non
- Appels Wikimedia pendant `/recommendations` ou `/trajectory` : aucun

## Architecture

Le catalogue scientifique canonique reste `/data/climaflora_global_plants_v2_0.sqlite` et est ouvert en lecture seule par l'ingesteur.

Les métadonnées Wikimedia sont écrites dans un sidecar SQLite dérivé et léger :

```text
catalogue v2.0 (read-only)
        │
        ├── exact scientific name
        ▼
Wikidata P225 + P18
        │
        ▼
Wikimedia Commons metadata
        │
        ├── exact match only
        ├── licence whitelist
        ├── safe HTTPS URLs
        └── deterministic primary selection
        ▼
data/climaflora_media_v1.sqlite
        │
        ▼
/api/v1/plants/enrichment
        │
        ▼
OVH frontend (lazy image)
```

Le sidecar peut être supprimé sans aucune restauration du catalogue scientifique.

## Taxonomie

Méthode v1 : `exact_scientific_name` uniquement.

L'ingesteur interroge Wikidata avec la propriété taxonomique P225 pour le nom scientifique canonique exact. Un nom scientifique ClimaFlora n'est traité que s'il est unique dans `plant_index` et s'il correspond à un unique taxon Wikidata pour ce P225.

Sont rejetés :

- fuzzy matching ;
- genre seul ;
- espèce voisine ;
- sous-espèce différente ;
- cultivar différent ;
- plusieurs taxons Wikidata portant le même P225 exact.

La confiance enregistrée pour `exact_scientific_name` est `0.95`. L'architecture réserve `exact_taxon_id=1.0` à une évolution future lorsqu'un identifiant taxonomique commun fiable sera disponible.

## Licences

Whitelist :

- CC0 ;
- Public domain ;
- CC BY ;
- CC BY-SA.

Rejet systématique :

- toute mention NC ;
- toute mention ND ;
- licence vide ;
- licence inconnue ou ambiguë ;
- droits réservés.

Le déploiement contient un gate SQL qui exige zéro primaire NC/ND/vide et zéro primaire multiple.

## Sécurité URL et contenu

Le runtime n'accepte comme URL image que :

```text
https://upload.wikimedia.org/...
```

La page source doit être :

```text
https://commons.wikimedia.org/...
```

Les métadonnées auteur/crédit venant de Commons sont converties en texte brut avant persistance. Aucun HTML Wikimedia n'est injecté dans le frontend.

MIME admis : JPEG, PNG, WebP.

## Schéma sidecar

Table principale : `plant_image_asset`.

Champs essentiels :

- `taxon_id`
- `asset_id`
- `source_name`
- `source_page_url`
- `image_url`
- `thumbnail_url`
- `license`
- `license_url`
- `author`
- `attribution`
- `width`, `height`, `mime_type`
- `is_primary`
- `materialized`
- `match_method`
- `match_confidence`
- `quality_rank`
- `retrieved_at`, `last_checked_at`
- `source_metadata_json`

Un index unique partiel impose au maximum une ligne `is_primary=1` par taxon.

`media_ingest_attempt` conserve un résultat auditable par taxon : `selected`, `no_result`, `rejected_license`, `rejected_taxonomy`, `network_error`, `invalid_media`.

`media_metadata` stocke la version d'ingesteur, le hash du catalogue source et `image_scoring_effect=false`.

## Sélection primaire

Le rang média est séparé du score scientifique. Il privilégie :

1. exactitude taxonomique ;
2. image JPEG/PNG/WebP ;
3. résolution suffisante ;
4. attribution et URL de licence complètes ;
5. licence plus permissive à qualité égale ;
6. identifiant média stable comme dernier tie-break.

Ce rang n'est jamais exposé comme score d'adaptation.

## CLI

Cas de référence :

```bash
python .github/tools/media_ingest_wikimedia.py \
  --catalog /data/climaflora_global_plants_v2_0.sqlite \
  --taxon "Akebia trifoliata" \
  --dry-run \
  --report-path /tmp/akebia-media-report.json
```

Lot pilote :

```bash
python .github/tools/media_ingest_wikimedia.py \
  --catalog /data/climaflora_global_plants_v2_0.sqlite \
  --output data/climaflora_media_v1.sqlite \
  --report-path data/climaflora_media_v1_report.json \
  --limit 100
```

Lot intermédiaire :

```bash
python .github/tools/media_ingest_wikimedia.py \
  --catalog /data/climaflora_global_plants_v2_0.sqlite \
  --output data/climaflora_media_v1.sqlite \
  --report-path data/climaflora_media_v1_report.json \
  --limit 5000
```

Options réseau : `--request-delay-ms`, `--max-retries`, `--timeout-seconds`. La politique utilise un User-Agent ClimaFlora explicite, un backoff borné et aucun parallélisme agressif.

## API

`GET /api/v1/plants/enrichment?taxon_id=...`

Ajoute :

```json
{
  "image": {
    "asset_id": "commons-...",
    "thumbnail_url": "https://upload.wikimedia.org/...",
    "image_url": "https://upload.wikimedia.org/...",
    "source_name": "wikimedia_commons",
    "source_page_url": "https://commons.wikimedia.org/...",
    "license": "CC BY-SA 4.0",
    "license_url": "https://creativecommons.org/...",
    "author": "...",
    "attribution": "..."
  },
  "image_scoring_effect": false
}
```

Sans média admissible : `image=null`, sans erreur.

`GET /api/v1/media/status` publie la couverture et les gates descriptifs : primaires, licences, rejets, manquants, thumbnails cassés, doublons.

Aucun appel Wikimedia n'est effectué par ces endpoints.

## Frontend

- miniature 480 px native Commons ;
- `loading="lazy"` ;
- `decoding="async"` ;
- `object-fit: cover` ;
- mode grille ;
- mode liste avec miniature compacte ;
- panneau latéral avec image jusqu'à 960 px, auteur, licence et source ;
- fallback végétal en absence d'image ou sur erreur réseau ;
- le texte scientifique est rendu indépendamment de l'image.

La phase v1 force une source Wikimedia-only : une image GBIF historique du catalogue n'est pas utilisée comme substitution lorsqu'aucun média Wikimedia v1 n'est admissible.

## CI et déploiement

`media-wikimedia-v1.yml` exécute sur PR :

1. hash ZST du catalogue v2.0 ;
2. hash SQLite après décompression ;
3. `PRAGMA integrity_check` ;
4. dry-run live `Akebia trifoliata` ;
5. lot pilote de 100 taxons ;
6. audit licences ;
7. audit fuzzy match ;
8. audit unicité primaire ;
9. audit `materialized=0` ;
10. artefact pilote auditable.

Après fusion, `deploy-huggingface.yml` prépare un sidecar de 5 000 taxons. Un sidecar existant n'est réutilisé que s'il est lié au même SHA-256 du catalogue v2.0 et passe tous les gates.

Le frontend est déployé séparément sur OVH par `deploy-ovh.yml`, avec vérification live de `media-v1.css` et `media-v1.js`.

## Non-régression scientifique

La protection principale est architecturale :

- aucune modification du catalogue v2.0 ;
- aucun import de `app.services.media` dans le moteur de score ;
- la couche média n'est appelée que depuis le routeur descriptif `plants/enrichment` et `media/status` ;
- `APP_VERSION` évolue, `METHOD_VERSION` et `CATALOG_SCHEMA_VERSION` restent identiques.

Les tests existants de scoring/ranking continuent de s'exécuter dans la suite complète.

## Rollback

Rollback applicatif : revenir au commit runtime 0.9.42 / désactiver la version 0.9.43.

Rollback frontend : redéployer le frontend précédent sans `media-v1.css` et `media-v1.js`.

Rollback média seul : supprimer ou ignorer `data/climaflora_media_v1.sqlite` ; l'API renverra `image=null` et le frontend utilisera le fallback.

Le catalogue scientifique v2.0 et ses hashes restent inchangés :

- SQLite : `3e80f432ebe2b4b59fed1b76549d2fc7df4e9330f1c315ae804746b616baee55`
- ZST : `1683c43c6fb1e68f9b6c6c4cd7f291642feba6c37a3691c3452b319856335c32`
