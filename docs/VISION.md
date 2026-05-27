# VISION IndustrIA v4.0

## Principe absolu
LLM = parser sémantique et rédacteur uniquement.
Python = tous les calculs et décisions méthodologiques.

## Hiérarchie des documents
- VISION.md = architecture macro v4.0 et état d'avancement
- AGENTS.md = référence historique v3.0 et assets réutilisables
- PHILOSOPHY.md = règles de code pour tous les systèmes
- docs/S1.md, docs/S2.md, etc. = spec détaillée par système

## Les 9 systèmes

| Système | Responsabilité | Mode |
|---------|---------------|------|
| S0 | Onboarding client → client_config.yaml | Manuel (Ahmed) |
| S1 | Comprendre la question → intent.json | Automatique |
| S2 | Récupérer, pivoter, nettoyer → df_propre | Automatique |
| S3 | Calculer les métriques pertinentes | Automatique |
| S4 | Générer graphiques + descriptions tabulaires | Automatique |
| S5 | Interpréter en langage métier vérifié | Automatique |
| S6 | Recommandation actionnelle adaptée au profil | Automatique |
| S7 | Assembler le rapport PDF EN9100 SHA-256 | Automatique |
| S8 | Monitoring temps réel, alertes P1-P4 | Automatique |

## Ségrégation
- S0 et S1 connaissent la structure du dataset via le YAML
- S1 ne lit JAMAIS le CSV ni les données brutes
- S2 traduit données brutes → df_propre standardisé
- S3 à S8 ne voient jamais les données brutes

## Infra locale
- GPU : RTX 3060 12 Go VRAM
- LLM : Ollama local, qwen2.5-coder:7b (S1) et 14b (S5/S6)
- OLLAMA_KEEP_ALIVE=-1, file FIFO, 1 appel à la fois
- Toutes les passes 7b avant toutes les passes 14b
- Conformité ITAR : zéro donnée hors du réseau local

## Client actuel : LISI Aerospace
- CSV 4M lignes, format LONG (Tag + Value)
- 16 colonnes, 2 opérations (FILAGE, EQUATOR)
- 10 modèles de pièces
- Numero Machine = presse au FILAGE, four à EQUATOR
- Ref_Matrice pertinent uniquement sur EQUATOR
- Colonnes PAS_* pertinentes uniquement sur FILAGE
- Config : configs/lisi_aerospace/client_config.yaml

## Configuration
- Client : configs/{client}/client_config.yaml (v4.0)
- Runtime Ollama : data/config.py (legacy, à migrer)

## Assets existants réutilisables
- specialists/ → S3
- enterprise/report/ → S7
- enterprise/rag/ → S6

## Statut
- S0 : ✅ YAML LISI + client générique (`configs/`)
- S1 : ✅ VALIDÉ — 32+ tests (`systems/s1/`, docs/S1.md)
- S2 : ✅ VALIDÉ — 6 tests LISI (`systems/s2/`, docs/S2.md)
- S3 : ✅ VALIDÉ — métriques + pre-gates (`systems/s3/`, docs/S3.md)
- S4 : ✅ VALIDÉ — graphiques + tableaux (`systems/s4/`, docs/S4.md)
- S5 : ✅ VALIDÉ — interprétation vérifiée, E2E LISI (`systems/s5/`, `tests/test_pipeline_e2e.py`, docs/S5.md)
- S6 à S8 : ⏳ À FAIRE (reco/RAG, PDF EN9100, monitoring)

## Méthode
Un système à la fois.
Définition → Code → Tests données LISI → Validation → Suivant.
