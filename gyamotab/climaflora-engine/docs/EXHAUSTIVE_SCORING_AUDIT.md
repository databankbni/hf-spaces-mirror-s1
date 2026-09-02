# Audit du scoring exhaustif ClimaFlora

## Objet

Le moteur public de recherche doit évaluer l'ensemble des taxons encore éligibles après les filtres descriptifs de type et de fonction. Aucun `TOP N`, seuil de rough score ou ordre alphabétique ne doit pré-éliminer un taxon avant l'attribution de son statut climatique/édaphique.

La référence métier reste `app/domain/scoring.py::score_plant`. L'implémentation exhaustive est `app/services/exhaustive_search.py` et doit reproduire en SQL les mêmes règles de score/statut pour permettre le calcul sur le catalogue complet sans hydrater tous les taxons en Python.

## Parité vérifiée

| Règle | `score_plant()` | Recherche exhaustive SQL | État |
| --- | --- | --- | --- |
| Bornes `hard_low/optimum_low/optimum_high/hard_high` | 0 hors borne dure, 100 dans l'optimum, interpolation dans les marges | même `CASE` SQL | aligné |
| Groupes climatiques | M 0,30 / V 0,20 / E 0,35 / A 0,15, renormalisés sur les groupes disponibles | mêmes coefficients et renormalisation | aligné |
| Données climatiques insuffisantes | `UNKNOWN` si poids connu < `min_known_weight` ou score absent | même règle | aligné |
| Critère climatique fatal | composante `RED` et `fatal=True` force le climat à `RED` | `fatal=1` et score < 40 force `RED` | aligné |
| Seuils de statut | GREEN >= 75 ; ORANGE >= 40 ; sinon RED | mêmes seuils | aligné |
| Sol numérique | même fonction d'enveloppe 0–100 | même fonction SQL | aligné |
| Sol catégoriel | optimum 100 ; accepté 65 ; sinon 0 | mêmes valeurs | aligné |
| Suffisance du sol | au moins 2 composantes connues et poids connu >= `min_known_weight` | même règle | aligné |
| Score combiné | 75 % climat + 25 % sol quand le sol est exploitable | même formule | aligné |
| Garde climatique | climat RED => combiné RED ; climat UNKNOWN => combiné UNKNOWN | mêmes gardes | aligné |
| EIVE / prior géographique | contexte uniquement, non scoré | non intégré au score exhaustif | aligné |
| Confiance | information séparée, ne majore pas le score | ne majore pas le score exhaustif | aligné |

## Différence volontaire de politique de classement

Le score et les statuts sont alignés, mais le départage final n'est pas strictement identique à l'ancien `_sort_key` Python. Le moteur exhaustif utilise la centralité climatique comme départage scientifique avant l'identifiant du taxon, alors que l'ancien classement utilisait notamment le nom scientifique et plaçait le veto réglementaire en premier critère de tri.

Cette différence n'altère pas le score ou le statut d'une plante. Elle évite notamment qu'un grand groupe d'ex aequo soit artificiellement favorisé par l'ordre alphabétique. Le test `test_exhaustive_search_has_no_1000_taxon_prelimit_and_no_alphabetic_tie_bias` protège ce comportement.

Le veto réglementaire reste exposé sur chaque recommandation et `recommendation_eligible=False` dans le modèle détaillé. Toute évolution future visant à faire du veto un critère global de tri doit être décidée explicitement et testée séparément.

## Garanties attendues

- `metrics.catalog_total` représente le catalogue complet.
- `metrics.evaluated_candidates` représente tous les taxons après filtres type/fonction, pas seulement la page retournée.
- Les facettes climat et sol sont calculées sur la population évaluée complète.
- La pagination intervient après le scoring/classement exhaustif.
- L'hydratation détaillée Python ne porte que sur les identifiants de la page demandée.
- Le cache de snapshot peut réutiliser le classement exhaustif pour les pages suivantes sans modifier la population évaluée.

## Validation de production

Le workflow `.github/workflows/verify-exhaustive-search-performance.yml` vérifie sur le catalogue v2.0 de production :

- 420 532 taxons au catalogue ;
- absence de pré-limite à 1 000 ;
- cohérence des compteurs de formes biologiques et fonctions ;
- absence de biais alphabétique A-only sur les premiers résultats ;
- réutilisation du cache sur la page suivante ;
- plafonds de temps de réponse sur le Space Hugging Face.
