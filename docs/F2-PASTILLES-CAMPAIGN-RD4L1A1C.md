# F2 pastilles — clôture campagne RD4L1A1C / FILAGE

> **Statut** : **CLÔTURÉ** — campagne validée sur `main`  
> **Date** : 2026-06-06  
> **Périmètre** : client démo, export traçabilité local  
> **Références** : [P7-F2-COMPACT-SPEC.md](./P7-F2-COMPACT-SPEC.md), [P7-F2-HIGH-CARDINALITY.md](./P7-F2-HIGH-CARDINALITY.md)

---

## 1. Contexte

| Élément | Valeur |
|---------|--------|
| **Pièce (modèle)** | RD4L1A1C |
| **Opération** | FILAGE |
| **Variable quantitative** | CR1 |
| **Config client** | `configs/lisi_aerospace/client_config_traceability.yaml` |
| **Niveau d'analyse** | Mesure capteur (une ligne par mesure) |
| **Activation F2 compact** | `f2_compact_enabled: true` en mémoire uniquement (hors YAML commité) |
| **Pipeline** | S1 → S2 → S3 → S4 → S7 (PDF F2 compact) |

Les runs de validation utilisent l'export traçabilité local (`data/lisi_capteurs_export_complet_tracabilite.csv`, gitignored). Aucune donnée process ni valeur métier confidentielle n'est versionnée dans ce dépôt.

---

## 2. Cas validés

| # | Question métier (résumé) | Facteur (`group_by`) | Mode F2 | Statut |
|---|--------------------------|----------------------|---------|--------|
| 1 | CR1 selon numéro de passage pastille **extérieure** | `PAS_E_Numero_Passage` | F2 compact standard | **Validé** |
| 2 | CR1 selon numéro de passage pastille **intérieure** | `PAS_I_Numero_Passage` | F2 compact standard | **Validé** |
| 3 | CR1 selon niveau de retaille pastille **extérieure** | `PAS_E_Niveau_Retaille` | F2 compact + **high-cardinality** | **Validé** |
| 4 | CR1 selon niveau de retaille pastille **intérieure** | `PAS_I_Niveau_Retaille` | F2 compact + **high-cardinality** | **Validé** |

### Cas non retenu sur ce périmètre

| Facteur | Motif |
|---------|--------|
| `PAS_E_Fournisseur` / `PAS_I_Fournisseur` | **Non exploitable** — une seule modalité fournisseur détectée sur RD4L1A1C / FILAGE → pas de comparaison inter-groupes possible |

---

## 3. Résultats clés (lecture métier)

### Passage pastille (2 groupes fiables)

| Côté | Groupe prioritaire | Groupe favorable | Verdict |
|------|-------------------|------------------|---------|
| Extérieur (P1 / P2) | **P2** | **P1** | NO-GO |
| Intérieur (P1 / P2) | **P2** | **P1** | NO-GO |

### Retaille pastille (high-cardinality)

| Côté | Groupe prioritaire | Modalités fiables (S3) | Lignes affichées (S7) | Verdict |
|------|-------------------|------------------------|----------------------|---------|
| Extérieure | **-16** | 41 | 7 (top 5 + favorable + Autres) | NO-GO |
| Intérieure | **-5** | 29 | 7 (top 5 + favorable + Autres) | NO-GO |

Effectifs « Autres modalités » (non tronqués en PDF) : **37 301** (ext.) / **27 110** (int.).

### Fournisseur

Diagnostic S1→S3 : cardinalité unitaire → **analyse comparative non exploitable** (pas de PDF F2 comparatif attendu).

---

## 4. Décisions produit

| Situation | Comportement retenu |
|-----------|---------------------|
| **Faible cardinalité** (ex. passage P1/P2) | F2 compact **standard** — tableau complet des groupes fiables |
| **Forte cardinalité** (ex. retaille 28–41 niveaux) | F2 compact + **high-cardinality** — top K + référence favorable + « Autres modalités » |
| **Une seule modalité fiable** (ex. fournisseur) | **Non exploitable** — pas de livrable comparatif |

Règles figées pour cette campagne :

- S3 reste **exhaustif** (ranking inchangé).
- S7 projette uniquement le **rendu PDF** (labels, tableaux, graphiques, wording).
- Labels pastille résolus via YAML `colonne_ext` / `colonne_int` (PR #11).
- Boxplot : label métier sur titre et axe X via `chart_group_label` (PR #11).

---

## 5. Limites et réserves

| Limite | Détail |
|--------|--------|
| **Causalité** | Les écarts observés sont des **associations statistiques** ; le PDF rappelle les limites d'interprétation (pas de causalité directe affirmée). |
| **Niveau d'analyse** | Mesure brute capteur — pas d'agrégation OF / pièce contrôlée dans ces livrables. |
| **Retaille S2** | Formats hétérogènes (`-6,5` vs `-6`) peuvent fragmenter artificiellement les groupes ; une **normalisation S2** reste une piste ultérieure, non bloquante pour cette campagne. |
| **Rendu PDF** | Wording et tableaux jugés **suffisants pour démo pilote** ; réserves mineures non bloquantes : en-tête `% hors tol.` parfois coupé, format décimal du bandeau verdict (`Cpk 0.55` vs virgule). |
| **Fournisseur** | Non testable tant qu'un second fournisseur n'apparaît pas sur le périmètre. |

---

## 6. État Git et livrables

### Code produit (`main`)

Correctifs mergés pour cette campagne :

| PR | Objet |
|----|--------|
| #9 | F2 high-cardinality |
| #10 | Effectifs remainder / largeur colonne `n` |
| #11 | Labels métier + axe boxplot |
| #12 | Pluralisation lecture métier retaille |

Tests de régression au moment de la clôture : `pytest systems/s7/tests/ -q` → **138 passed**.

### PDF locaux (non versionnés)

Les PDF finaux sont générés **localement** dans `outputs/` (gitignored) :

| Cas | Fichier local |
|-----|---------------|
| Passage extérieur | `outputs/f2_pastilles_passage_ext_RD4L1A1C.pdf` |
| Passage intérieur | `outputs/f2_pastilles_passage_int_RD4L1A1C.pdf` |
| Retaille extérieure | `outputs/f2_pastilles_retaille_ext_RD4L1A1C.pdf` |
| Retaille intérieure | `outputs/f2_pastilles_retaille_int_RD4L1A1C.pdf` |

**Ne pas** committer les PDF, `outputs/`, exports CSV, ni caches parquet.

### Hors périmètre document

- Pas de données process détaillées dans ce fichier.
- Pas de valeurs confidentielles client au-delà des identifiants génériques de démo (pièce, tags, chemins config).

---

## 7. Verdict campagne

**Campagne F2 pastilles RD4L1A1C / FILAGE / CR1 : VALIDÉE** pour démo pilote.

Prochaines pistes optionnelles (hors clôture) : normalisation retaille S2, polish cosmétique PDF, réévaluation fournisseur si l'export gagne une seconde modalité.
