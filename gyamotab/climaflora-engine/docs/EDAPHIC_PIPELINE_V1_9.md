# ClimaFlora — Pipeline édaphique consolidé v1.9

## Objet

La v1.9 transforme les preuves édaphiques déjà validées dans le catalogue v1.8 en une architecture conforme au cadrage d’enrichissement édaphique mondial : provenance explicite, base de build séparée, hiérarchie des preuves, seuil minimal pour les observations, conflits conservés, priors d’aire native non scorants et projection de production rétrocompatible.

La v1.8 est traitée comme un artefact source immuable. Le build vérifie son SHA-256 avant et après traitement.

## Artefacts

- `climaflora_edaphic_build.sqlite` : base scientifique de travail, non utilisée par l’API de production.
- `climaflora_global_plants_v1_9.sqlite` : catalogue maître de production.
- `climaflora_global_plants_v1_9.report.json` : manifeste, métriques, contrôles et échantillon d’audit.
- Les deux bases sont compressées en zstd ; le catalogue est publié sur OVH et la base de build est persistée dans le dataset privé Hugging Face `gyamotab/climaflora-edaphic-builds`.

## Sources consolidées

| Source | Rôle | Traitement v1.9 |
|---|---|---|
| FAO ECOCROP | contraintes expertes pH et préférences catégorielles | priorité experte ; doublons conservés comme preuves et consolidés sans fusion destructive |
| EIVE 1.0 | humidité, nutriments, réaction | conservé sur l’échelle écologique harmonisée ; aucune conversion en unités physiques |
| sPlotOpen + SoilGrids | niche édaphique réalisée | conservée ; `n >= 10` obligatoire pour le scoring numérique |
| WCVP + WGSRPD + SoilGrids | contexte de l’aire native | contexte uniquement ; `scoring_enabled=0` invariant |

SoilGrids est distribué sous CC BY 4.0. Le backbone et les distributions WCVP exposés par POWO sont attribués à Kew avec la licence indiquée par la source. sPlotOpen et EIVE sont conservés avec leurs citations et conditions d’attribution. ECOCROP reste associé aux conditions FAO ; seuls les résultats dérivés nécessaires à ClimaFlora et leur provenance sont redistribués dans le catalogue.

## Hiérarchie

1. `EXPERT`
2. `OCCURRENCE_DERIVED`
3. `NATIVE_RANGE_DERIVED`
4. `UNKNOWN`

Une enveloppe experte numérique conserve la priorité sur une enveloppe d’occurrence. L’occurrence reste disponible comme preuve secondaire. Le prior géographique n’est jamais utilisé comme tolérance de la plante.

## Seuils occurrence

- `n >= 100` : confiance forte ;
- `30 <= n < 100` : confiance intermédiaire forte ;
- `10 <= n < 30` : confiance modérée ;
- `n < 10` : contexte conservé mais scoring interdit.

Le score de confiance est déterministe et documenté dans `build_edaphic_v1_9.py`. Les classes sont : A `>=0.85`, B `>=0.70`, C `>=0.50`, D `<0.50`.

## Tables de production

La compatibilité avec le moteur actuel est préservée :

- `soil_envelope` : projection numérique unique, uniquement pour les enveloppes autorisées au scoring ; une ligne maximum par taxon/variable.
- `soil_categorical_preference` et `soil_indicator_preference` : interfaces historiques conservées.
- `soil_geographic_prior` : invariant `scoring_enabled=0`.

La v1.9 ajoute :

- `soil_source_envelope` : lignes numériques v1.8 originales ;
- `soil_source_categorical_preference` : préférences catégorielles v1.8 originales ;
- `soil_sources` : registre de provenance/licence ;
- `soil_envelopes` : enveloppe canonique, y compris contexte non scorant ;
- `soil_preferences` : préférences expertes harmonisées ;
- `soil_evidence` : preuves compactes et références aux tables sources.

## Correction ECOCROP

Le parseur historique remplaçait tous les `/` par un séparateur de valeurs. Cela fragmentait notamment :

- `dS/m` dans les classes de salinité ;
- `excessive (dry/moderately dry)` dans le drainage.

La v1.9 conserve les valeurs historiques dans `soil_source_categorical_preference`, mais répare de façon déterministe la projection runtime/canonique. Aucun nouveau libellé écologique n’est inféré.

## Conflits

Les doublons ECOCROP numériques ne sont jamais supprimés de la preuve. Pour leur enveloppe consolidée :

- la tolérance absolue est l’union des limites documentées ;
- l’optimum est l’intersection des plages optimales si cette intersection existe ;
- si les optima sont incompatibles, le conflit est enregistré et la valeur numérique n’est pas scorée automatiquement.

Un désaccord expert/occurrence est également signalé dans la table canonique sans remplacer la source experte.

## Base de build

`climaflora_edaphic_build.sqlite` contient :

- `edaphic_sources` ;
- `edaphic_expert_values` ;
- `edaphic_occurrence_stats` ;
- `edaphic_native_range_stats` ;
- `edaphic_envelopes` ;
- `edaphic_evidence` ;
- `edaphic_build_metadata`.

Les statistiques P10/P50/P90/mean/stddev restent nulles pour les enveloppes sPlot héritées lorsque la v1.8 ne les avait pas matérialisées. Elles ne sont pas inventées. Une future ré-extraction à partir des occurrences brutes pourra compléter ces colonnes sans modifier le schéma.

## Gates production

Une v1.9 n’est `ready` que si :

- la v1.8 conserve exactement son SHA-256 ;
- `PRAGMA integrity_check` retourne `ok` sur le catalogue et la base de build ;
- aucun doublon taxon/variable n’existe dans `soil_envelope` ;
- aucune occurrence avec `n < 10` n’est scorée ;
- aucun prior d’aire native n’est scoré ;
- aucune valeur EIVE n’est convertie en pH ou autre unité physique ;
- les plages numériques sont ordonnées et plausibles ;
- les fragments ECOCROP `dS/m`/drainage ont disparu de la projection runtime ;
- chaque source du registre possède des conditions/licence documentées ;
- la couverture et les anomalies sont publiées dans le rapport.

## Déploiement

1. `build-catalog-v1.9.yml` construit et valide les deux bases.
2. `promote-catalog-v1.9.yml` revérifie l’artefact, publie le catalogue sur OVH et persiste la base de build sur Hugging Face.
3. `activate-catalog-v1.9.yml` ne s’exécute sur `main` qu’après promotion vérifiée ; il bascule les variables runtime et incrémente l’application en `0.9.39`.
4. `verify-production-v1.9.yml` interroge le Space après déploiement et n’écrit `production-v1.9-status.json` que si le catalogue live est `ready` et `scientific_ready=true`.

Les catalogues v1.8, v1.7, v1.6 et v1.2 restent conservés comme cibles de rollback.
