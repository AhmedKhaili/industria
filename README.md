# IndustrIA

IndustrIA est une plateforme d'IA agentique industrielle, 100% locale, conçue pour l'analyse de données capteurs et l'assistance à la maintenance en environnement souverain.

## Structure du repo

Le dépôt est séparé en deux espaces principaux :

- `core/` : brique open source sous licence Apache 2.0
- `enterprise/` : brique commerciale sous licence BSL 1.1

Arborescence cible :

```text
core/
  LICENSE
  data/
  database/

enterprise/
  LICENSE
  agents/
```

## Double licence

### `core/` — Apache 2.0

Le dossier `core/` contient les composants open source du projet :

- simulateurs et jeux de données industriels ;
- scripts de préparation et d'ingestion TimescaleDB ;
- briques réutilisables sans dépendance à la couche commerciale.

Ces fichiers sont distribués sous la licence Apache 2.0. Le texte complet est disponible dans `core/LICENSE`.

### `enterprise/` — Business Source License 1.1

Le dossier `enterprise/` contient la couche commerciale :

- agents LLM ;
- orchestration et routage agentique ;
- logique de synthèse métier destinée au produit IndustrIA Enterprise.

Cette partie est distribuée sous Business Source License 1.1 avec les paramètres suivants :

- **Licensed Work** : `IndustrIA Enterprise`
- **Additional Use Grant** : usage gratuit hors production uniquement
- **Change Date** : `2030-05-11`
- **Change License** : Apache License, Version 2.0

Le texte complet est disponible dans `enterprise/LICENSE`.

## Notes d'exécution

- Les imports Python utilisent désormais les packages `core.*` et `enterprise.*`.
- Les scripts déplacés peuvent être exécutés depuis la racine du dépôt, par exemple :
  - `py -3 core/database/setup.py`
  - `py -3 core/database/ingest.py`
  - `py -3 enterprise/agents/orchestrator_agent.py`
