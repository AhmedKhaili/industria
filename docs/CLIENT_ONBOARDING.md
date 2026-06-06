# Onboarding client — IndustrIA

> **Statut** : **GUIDE PRODUIT**  
> **Version** : 1.0 — 2026-06-06  
> **Public** : intégrateur, data engineer, responsable qualité pilote  
> **Références** : [VISION.md](./VISION.md), [PHILOSOPHY.md](./PHILOSOPHY.md), [F2-PASTILLES-CAMPAIGN-RD4L1A1C.md](./F2-PASTILLES-CAMPAIGN-RD4L1A1C.md)

---

## 1. Objectif du processus onboarding

IndustrIA transforme un **export industriel client** en pipeline analytique question → `df_propre` → statistiques → rapport PDF, en restant **config-driven** autant que possible.

| Objectif | Détail |
|----------|--------|
| **POC rapide** | Si le format est proche du standard **LONG Tag/Value** (comme le client démo aéronautique), viser un premier parcours bout-en-bout en **quelques jours** après 1–2 rendez-vous. |
| **Cœur moteur intact** | S3+ (statistiques, ranking, tests, rendu PDF) est réutilisé ; l'adaptation se concentre sur **S0 (YAML)**, **S1 (langage métier)** et **S2 (ingestion / nettoyage)**. |
| **Cadrage honnête** | Formats WIDE, multi-sources ERP/GMAO/capteurs, ou données sans tolérances nécessitent un chantier dédié — pas de promesse « tout format, zéro effort ». |

```
Export client (échantillon anonymisé)
        │
        ▼
S0 YAML ──► S1 questions métier ──► S2 df_propre
        │                                    │
        └──────── vocabulaire / règles ─────┘
                                             ▼
                              S3 → S4 → S5/S6 → S7 (PDF)
```

---

## 2. Ce qu'on demande au client (1er rendez-vous)

Checklist matérielle à collecter **avant** d'écrire la moindre ligne de code :

| Livrable demandé | Pourquoi |
|------------------|----------|
| **Export échantillon anonymisé** | Valider format, volume, qualité, colonnes réelles |
| **Dictionnaire des colonnes** | Mapping YAML `dataset.colonnes` |
| **Liste des opérations** | `operations_actives`, tags par opération |
| **Liste des pièces / références produit** | `modeles_actifs`, tolérances par pièce |
| **Variables critiques (tags)** | Groupes variables, unités, LTI/LTS |
| **Tolérances** | Cpk, % hors tolérance, verdicts — **indispensables** pour analyses capabilité |
| **Facteurs de comparaison** | Matrice, machine, passage, retaille, OF, lot… |
| **5–10 questions métier types** | Calibrer S1 (intentions, synonymes, ambiguïtés) |
| **Livrable attendu** | PDF ponctuel, dashboard, analyse récurrente, alerte ? |

**Confidentialité** : échantillon **anonymisé** ; fichiers de données restent **locaux et gitignored** — jamais commités dans le dépôt produit.

---

## 3. Arbre de décision — format de données

```
                    Export reçu
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
   LONG Tag/Value   LONG colonnes    WIDE (1 col
   proche démo      différentes       par mesure)
         │               │               │
         ▼               ▼               ▼
   YAML + cache     YAML + mapping   S2 adapté ou
   S2 rebuild       colonnes +       pré-pivot
                    règles S2        externe
         │               │               │
         └───────────────┴───────────────┘
                         │
              Multi-fichiers / ERP / GMAO ?
                         │
                         ▼
              Chantier ingestion dédié
              (hors template standard)

              Tolérances absentes ?
                         ▼
              Catalogue métier requis
              avant Cpk / % HT fiables
```

| Profil | Effort typique | Action principale |
|--------|----------------|-------------------|
| **LONG proche démo** | Faible | Nouveau dossier `configs/<client>/`, YAML, rebuild cache S2 |
| **LONG colonnes différentes** | Faible à moyen | Mapping `dataset.colonnes`, règles `regles_nettoyage` |
| **WIDE** | Moyen à élevé | Adapter pivot S2 ou normaliser en amont |
| **Multi-sources** | Élevé | Connecteurs, fusion, contrat `df_propre` explicite |
| **Sans tolérances** | Bloquant analyses Cpk | Compléter catalogue pièce/opération/tag avant POC |

---

## 4. Rôle de chaque système

| Système | Rôle onboarding | Touche typique à l'onboarding |
|---------|-----------------|-------------------------------|
| **S0 — Config YAML** | Contrat client : colonnes, pièces, ops, tolérances, facteurs | **Toujours** |
| **S1 — Langage** | Comprendre la question, résoudre pièce/opération/variable/facteur | Synonymes, ambiguïtés, dual-colonnes |
| **S2 — Données** | Charger, nettoyer, pivoter → **`df_propre` stable** | Mapping, règles, `pivot_index_keys` |
| **S3 — Statistiques** | Analyses exhaustives, ranking, tests globaux | Rarement (moteur générique) |
| **S4 — Graphiques** | Boxplots, distributions, séries | Rarement |
| **S5 / S6** | Interprétation, recommandations | Stubs / LLM selon profil |
| **S7 — Rapport** | PDF compact, labels, quality gate | Labels via YAML ; `f2_compact_enabled` en mémoire pour POC |
| **F2 compact standard** | Peu de modalités (ex. 2 passages P1/P2) | Config facteurs + seuils fiabilité |
| **F2 high-cardinality** | Beaucoup de modalités (ex. retaille 29–41 niveaux) | Projection S7, pas de changement S3 |
| **Non exploitable** | Une seule modalité fiable | Diagnostic, pas de PDF comparatif |

---

## 5. Contrat minimal de `df_propre`

`df_propre` est la **sortie S2** consommée par S3+. Contrat cible (concepts, noms YAML) :

| Concept | Colonne type (ex. démo) | Obligatoire POC |
|---------|-------------------------|-----------------|
| **Horodatage** | `Date` | Recommandé |
| **Opération** | `Operation` | **Oui** |
| **Tag / variable** | `Tag` (LONG) ou colonnes pivotées (WIDE) | **Oui** |
| **Valeur mesure** | `Value` (LONG) | **Oui** |
| **Référence produit / modèle** | `Designation Reference` | **Oui** |
| **Machine / presse** | `Numero Machine` | Selon facteurs |
| **Identifiants traçabilité** | OF, pièce contrôlée | Si analyse par unité métier |
| **Facteurs qualitatifs** | Colonnes physiques ou pivotées | Selon questions F2 |
| **Tolérances** | Via YAML `pieces.*.operations.*.tags.*` (LTI, LTS, nominal) | **Oui** pour Cpk / % HT |
| **Types numériques** | Variables numériques, décimales normalisées | **Oui** |

Règles :

- Une ligne = typiquement **une mesure capteur** (niveau `measure`) sauf agrégation métier explicite.
- Les facteurs à **dual-colonnes** (ext/int, gauche/droite…) doivent être déclarés dans `entites.facteurs_analyse` avec `colonne_ext` / `colonne_int`.

---

## 6. Checklist configuration YAML

Créer `configs/<client_slug>/client_config.yaml` (copier le template démo, adapter) :

### Identité & dataset

- [ ] `client.nom`, `client.site`, `client.secteur`, `client.langue`
- [ ] `dataset.format` (`LONG` ou documenter WIDE)
- [ ] `dataset.fichier` (chemin local gitignored)
- [ ] `dataset.separateur`, `dataset.encoding`
- [ ] `dataset.colonnes.*` (mapping complet)

### Périmètre produit

- [ ] `operations_actives`
- [ ] `modeles_actifs` / liste pièces
- [ ] `pieces.<ref>.operations.<op>.tags.*` (LTI, LTS, nominal, unité, libellés)

### Pivot & traçabilité (si colonnes hors LONG standard)

- [ ] `dataset.pivot_index_keys` (colonnes à conserver à l'index après pivot Tag/Value)
- [ ] Règles `dataset.regles_nettoyage` par colonne métier

### Langage & analyse

- [ ] `entites.groupes_variables` (pattern tags, synonymes)
- [ ] `entites.facteurs_analyse` (colonnes, `colonne_ext`/`colonne_int`, synonymes)
- [ ] `intentions` / exemples de questions si présents dans le template

### Rapport PDF (POC)

- [ ] `rapport_pdf` (mode, libellés verdict, chemins locaux)
- [ ] `rapport_pdf.f2_compact` (seuils, `min_n`, patterns groupe)
- [ ] Paramètres **high-cardinality** (seuils activation, `max_table_rows`) — defaults code ou surcharge mémoire POC

> **Note POC** : `f2_compact_enabled: true` est souvent activé **en mémoire** pour les premiers runs, sans modifier le YAML commité.

---

## 7. Checklist S1

| Élément | Exemples à documenter |
|---------|----------------------|
| **Synonymes opérations** | « filage », « mise en forme fil » → `FILAGE` |
| **Synonymes variables** | « corde », « CR » → tags `CR1`… |
| **Synonymes facteurs** | « matrice », « moule » → `Ref_Matrice` |
| **Questions types** | 5 formulations réelles validées avec le client |
| **Cas ambigus** | Pastille sans préciser ext/int → clarification S1 |
| **Facteurs dual-colonnes** | `colonne_ext` / `colonne_int` dans YAML (passage, retaille, poste A/B…) |

Tests cibles : `pytest systems/s1/tests/ -q` après ajout des synonymes / exemples.

---

## 8. Quand toucher S2 ?

| Situation | Action |
|-----------|--------|
| **Renommage colonnes** | YAML `dataset.colonnes` uniquement |
| **Règles métier simples** | YAML `regles_nettoyage` (valeurs valides, `<= 0`, etc.) |
| **Pivot index enrichi** | YAML `pivot_index_keys` ; vérifier que `pivotter.py` les applique |
| **Décimales françaises, types mixtes** | `cleaner.py` — patch S2 si règle générique manquante |
| **Format WIDE** | Adaptation S2 ou ETL externe → LONG |
| **Multi-sources** | Ingestion dédiée, hors template |
| **Granularité différente** | Revoir `pivot_index_keys` et niveau d'analyse F2 |

Validation : **1 run S2** + inspection `df_propre` (colonnes, effectifs, règles `applied`).

---

## 9. Ce qu'on ne touche normalement pas

Sauf besoin métier **explicitement validé** et testé :

| Composant | Raison |
|-----------|--------|
| **S3 ranking** | Source de vérité statistique |
| **Tests globaux** (Kruskal, ANOVA, etc.) | Moteur certifié |
| **S4 rendu de base** | Graphiques génériques |
| **S7 structure rapport** | Blocs F2 compact stables |
| **High-cardinality** | Projection présentation uniquement |
| **Quality gate** | Garde-fous client |

Les corrections **présentation** (labels PDF, largeurs colonnes, wording) restent dans **S7 / S4 présentation** sans altérer S3.

---

## 10. Protocole de validation onboarding

Séquence minimale avant de déclarer un client « POC-ready » :

| Étape | Critère de succès |
|-------|-------------------|
| 1. **5 questions S1** | `clarification_needed: false`, bons `piece` / `operation` / `variables` / `group_by` |
| 2. **1 run S2** | Pas d'erreur ; cache régénéré si besoin |
| 3. **Contrôle `df_propre`** | Colonnes attendues, effectifs cohérents, règles nettoyage `applied` |
| 4. **1 F2 faible cardinalité** | PDF local lisible (tableau + fiabilité + boxplot) |
| 5. **1 F2 high-cardinality** (si facteur riche) | Top K + Autres modalités + disclaimer exploratoire |
| 6. **1 PDF généré** | Dans `outputs/` ou `reports/` — **non versionné** |
| 7. **Git** | `git status` clean ; aucun CSV/PDF/parquet ajouté |

Commandes de régression produit : `pytest systems/s1/tests/ systems/s2/tests/ systems/s7/tests/ -q`.

---

## 11. Estimation d'effort (sobre)

| Profil client | Ordre de grandeur | Hypothèses |
|---------------|-------------------|------------|
| **Proche LONG démo** | **1–3 jours** | Template YAML mature, export propre, tolérances fournies |
| **Premier client / config riche** | **3–7 jours** | Nouveaux facteurs, synonymes S1, règles S2, validation PDF |
| **WIDE ou multi-sources** | **1–3 semaines** | Selon complexité ingestion et contrat `df_propre` |
| **Industrialisation SI client** | Variable | API, refresh données, gouvernance — hors scope POC |

Ces estimations supposent une **équipe connaissant déjà le repo** et un échantillon représentatif dès J1.

---

## 12. Limites et garde-fous

| Garde-fou | Application |
|-----------|-------------|
| **Association ≠ causalité** | Tous les PDF F2 rappellent les limites d'interprétation |
| **Confidentialité** | Données dans `data/`, `outputs/` — gitignored |
| **Pas de PDF/data en git** | Jamais `git add` sur exports ou livrables |
| **Échantillon anonymisé** | Pas de noms réels, pas de valeurs process sensibles dans le repo |
| **Qualité données** | Sans tolérances ou avec colonnes vides, pas d'analyse Cpk fiable |
| **Cardinalité** | Une modalité → diagnostic non exploitable, pas de forcing PDF |

Le produit est **multi-client et config-driven**, pas **format-agnostic** : chaque nouveau format doit passer l'arbre de décision §3.

---

## 13. Exemple — campagne F2 pastilles (client démo)

Référence complète : **[F2-PASTILLES-CAMPAIGN-RD4L1A1C.md](./F2-PASTILLES-CAMPAIGN-RD4L1A1C.md)**

Résumé des **règles produit** illustrées :

| Cardinalité facteur | Mode F2 | Exemple démo |
|--------------------|---------|--------------|
| **2 modalités fiables** | F2 compact **standard** | Passage pastille P1 / P2 |
| **29–41 modalités** | F2 compact + **high-cardinality** | Niveau retaille pastille |
| **1 modalité** | **Non exploitable** | Fournisseur pastille (une seule origine) |

Enseignements onboarding :

- Facteurs **dual-colonnes** (`colonne_ext` / `colonne_int`) → labels S7 via YAML, pas de hardcode client.
- POC PDF : `f2_compact_enabled` en mémoire ; données et PDF **locaux uniquement**.
- Validation = questions S1 + `df_propre` + PDF visuel + tests S7 — pas de merge de données client.

---

## Annexe — structure repo (rappel)

```
configs/<client>/client_config.yaml   ← S0
systems/s1/                           ← langage
systems/s2/                           ← df_propre
systems/s3/ … s7/                     ← moteur + PDF
data/                                 ← gitignored
outputs/                              ← gitignored
docs/                                 ← specs & guides (ce fichier)
```

Pour démarrer : dupliquer `configs/lisi_aerospace/` → adapter → valider avec le protocole §10.
