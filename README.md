# IndustrIA

Plateforme d’IA agentique pour l’analyse qualité industrielle — **100 % locale**, données capteurs on-premise (conformité ITAR / souveraineté).

Un technicien pose une question en français ; le pipeline comprend l’intention, charge les données, calcule les métriques (Cp/Cpk, ANOVA, etc.), produit graphiques et une interprétation LLM **dont les chiffres sont vérifiés en Python**.

## État d’avancement (v4.0)

| Système | Rôle | Statut |
|---------|------|--------|
| S0 | Config client (`client_config.yaml`) | YAML client démo + générique |
| S1 | Compréhension de la question → `intent.json` | Validé (32+ tests) |
| S2 | ETL, pivot Long→Large, Parquet | Validé (client démo) |
| S3 | Métriques (`specialists/`) | Validé |
| S4 | Graphiques + descriptions tabulaires | Validé |
| S5 | Interprétation LLM vérifiée (Ollama 14b) | Validé + E2E |
| S6 | Recommandations actionnelles (P1–P4, profil) | Validé — tests client démo + critiques |
| S7 | Rapport PDF EN9100 (SHA-256, `contrat_rapport`) | Validé — démo aéronautique (`systems/s7/`, 9 tests) |
| S8 | Monitoring temps réel, alertes P1–P4 | Prochain — spec à rédiger |

Détail : [`docs/VISION.md`](docs/VISION.md) · specs : [`docs/S1.md`](docs/S1.md) … [`docs/S7.md`](docs/S7.md)

## Démarrage rapide

**Prérequis** : Python 3.11+, [Ollama](https://ollama.com/) avec `qwen2.5-coder:14b`, données client locales non versionnées.

```bash
# Cloner et installer les dépendances du projet (pandas, pyarrow, pytest, requests, …)

# Placer le CSV client (non versionné) :
#   data/lisi_capteurs.csv

# Chaîne manuelle S1 → S5
python -c "
from systems.s1.pipeline import S1Pipeline
from systems.s2.pipeline import S2Pipeline
from systems.s3.pipeline import S3Pipeline
from systems.s4.pipeline import S4Pipeline
from systems.s5.pipeline import S5Pipeline

YAML = 'configs/lisi_aerospace/client_config.yaml'
q = 'La matrice a-t-elle un impact sur la forme intrados de M2L1A1C ?'
intent = S1Pipeline(YAML).run(q)['intent']
s2 = S2Pipeline(YAML).run(intent)
s3 = S3Pipeline(YAML).run(intent, s2['df_propre'])
s4 = S4Pipeline(YAML).run(intent, s2['df_propre'], s3)
s5 = S5Pipeline(YAML).run(intent, s3, s4)
print(s5.get('synthese', '')[:500])
"
```

**Tests** (Ollama requis pour E2E S5) :

```bash
python -m pytest systems/s1/tests systems/s2/tests systems/s3/tests systems/s4/tests systems/s5/tests systems/s6/tests systems/s7/tests -q
python -m pytest tests/test_pipeline_e2e.py -v   # chaîne S1→S5, données client locales non versionnées (Ollama)
```

## Structure du dépôt

```text
systems/s1/ … s7/     # Pipelines v4.0 (open core)
configs/              # YAML multi-client (S0)
specialists/          # Calculs statistiques (S3)
enterprise/           # PDF, RAG, agents legacy v3 (BSL 1.1)
tests/                # Tests E2E intégration
docs/                 # VISION, PHILOSOPHY, S1–S7
data/                 # config.py + cache local (CSV non versionné)
```

## Principes

- **LLM** = parser sémantique et rédacteur uniquement  
- **Python** = calculs, validation, fidélité des chiffres (reject explicite si écart > 5 %)  
- **Multi-client** : un seul fichier `configs/{client}/client_config.yaml` par site  

Voir [`docs/PHILOSOPHY.md`](docs/PHILOSOPHY.md).

## Licences

- Composants réutilisables / `specialists/` / `systems/` : voir politique du dépôt  
- `enterprise/` : Business Source License 1.1 — usage production commercial selon `enterprise/LICENSE`  
- Ancienne arborescence `core/` : Apache 2.0 si présente  

## Client de démonstration

**Client aéronautique démo** — 4M+ lignes capteurs, opérations FILAGE / EQUATOR, métriques EN9100.
