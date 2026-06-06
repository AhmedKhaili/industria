# P7-F2 high-cardinality — Spec extension (pré-implémentation)

> **Statut** : **SPEC** — documentation uniquement, aucune implémentation dans cette étape  
> **Version doc** : 1.0 — 2026-06-02  
> **Prérequis** : [P7-F2-COMPACT-SPEC.md](./P7-F2-COMPACT-SPEC.md) (F2 compact v1 candidate)  
> **Cas pilote** : CR1 × niveau de retaille pastille (client démo, export traçabilité)

---

## 0. Objet

Extension **présentation** du PDF F2 compact lorsque le facteur qualitatif possède **trop de modalités** pour un tableau lisible (retaille, OF, lots, matrices…).

Objectif : conserver l’analyse statistique exhaustive (S3) tout en projetant côté S7 un sous-ensemble **actionnable** : top groupes à risque, référence favorable, reste agrégé.

**Non-cible** : catégorisation métier automatique, multi-facteurs (F3), modification du pipeline S3 dans cette spec.

---

## 1. Problème

### 1.1 Ce qui fonctionne aujourd’hui

Le **F2 compact standard** (v1) convient aux facteurs à **faible cardinalité** :

- passage pastille P1 / P2 (2 groupes) ;
- matrice avec pattern filtré et denylist ;
- fournisseur lorsque plusieurs origines coexistent.

Dans ces cas : tableau ≤ 6 lignes (`max_table_rows`), boxplot lisible, verdict cohérent avec `F2CompactSelection`.

### 1.2 Ce qui casse la lisibilité

Certains facteurs produisent **des dizaines de modalités distinctes** après nettoyage S2 :

| Facteur type | Cardinalité observée (exemple pilote) | Conséquence PDF brut |
|--------------|--------------------------------------|----------------------|
| `PAS_*_Niveau_Retaille` | 28–41 niveaux | Tableau + boxplot ingérables |
| `Numero OF MAR` | Très élevée (attendu) | Même problème |
| Lot / sous-lot | Élevée (attendu) | Même problème |
| `Ref_Matrice` | Élevée sans filtre strict | Même problème |

Le F2 compact v1 **tronque déjà** le tableau principal à `max_table_rows` (défaut 6), mais :

- la section **fiabilité statistique** peut encore lister tous les groupes fiables ;
- le **boxplot** peut inclure toutes les modalités fiables ;
- il n’existe pas de ligne **« Autres modalités »** ni d’avertissement **mode exploratoire** explicite.

Résultat : un PDF techniquement générable mais **illisible** et **trompeur** (signal noyé dans le bruit modal).

### 1.3 Cas non exploitable (hors high-cardinality)

Si le facteur n’a **qu’une seule modalité fiable** après S2 (ex. fournisseur = un seul code sur un périmètre pièce/opération), **aucune comparaison inter-groupes** n’est possible. Le mode high-cardinality ne s’applique pas : le diagnostic doit conclure **non exploitable**, sans PDF comparatif.

---

## 2. Principe

| Règle | Détail |
|-------|--------|
| **S3 exhaustif** | Tous les groupes restent calculés, classés et exportés dans `group_descriptive`. Aucune troncature côté analyse. |
| **Projection S7 uniquement** | La réduction s’applique au **rendu F2 compact** : sélection `rows_display` dérivée de `rows_reliable`. |
| **Priorisation** | Afficher les modalités **les plus défavorables** selon le **ranking S3 existant** (pas de second score). |
| **Référence favorable** | Inclure le **meilleur groupe fiable** (`best_reliable` / `favorable_strength`) s’il est distinct du top K. |
| **Regroupement** | Agréger le reste des groupes fiables en une ligne **« Autres modalités »** (configurable). |
| **Exclusions inchangées** | Groupes non fiables → section `excluded_groups` (logique C1 actuelle). |
| **Prudence** | Bandeau / paragraphe **exploratoire** : association statistique ≠ causalité (renforce `interpretation_limits` S3). |

```
S3 group_descriptive (N groupes, tous ranks)
        │
        ▼
S7 f2_compact_selection (rows_reliable, filtre fiabilité)
        │
        ▼
S7 high-cardinality projection (si N > seuil)
        │
        ├── rows_display : top K + best + Autres
        ├── charts : groupes affichés seulement
        └── disclaimer exploratoire
```

---

## 3. Règle proposée

### 3.1 Déclenchement

Le mode **high-cardinality** s’active lorsque :

```text
len(rows_reliable) > high_cardinality_threshold
```

Défaut proposé : `high_cardinality_threshold: 8`.

Si le seuil n’est pas franchi → comportement F2 compact v1 inchangé.

### 3.2 Construction de `rows_display`

Ordre des lignes affichées (stratégie `top_risk_plus_best`) :

1. **Top K** groupes défavorables — ceux de rang 1 à K parmi `rows_reliable` (tri S3 déjà appliqué via `rank`).
2. **Référence favorable** — `best_reliable` si :
   - `favorable_strength` ∈ `{robust, limited}` ;
   - `group_value` distinct de tous les groupes du top K.
3. **Autres modalités** (si `aggregate_remainder: true`) — agrégat des groupes fiables restants (hors top K et hors best si déjà listé).

Les groupes **exclus** (`rows_excluded`) ne participent ni au top K ni à l’agrégat ; ils restent documentés dans `excluded_groups`.

### 3.3 Limites du tableau

| Paramètre | Rôle |
|-----------|------|
| `max_groups_displayed` | K — nombre de groupes défavorables affichés (défaut 5) |
| `max_table_rows` | Plafond total lignes tableau (top K + best + Autres ; défaut aligné sur 7) |

### 3.4 Agrégat « Autres modalités »

Champs minimaux sur la ligne synthétique :

| Champ | Calcul proposé |
|-------|----------------|
| `n` | Somme des effectifs des groupes restants |
| `mean` | Moyenne pondérée par `n` (à partir des rows S3) |
| `out_of_tolerance_rate` | Taux pondéré par `n`, ou recalcul exact depuis `df_propre` si disponible en S7 |
| `cpk` | Recalcul sur le sous-ensemble `df_propre` (recommandé) ; sinon affichage « — » |
| `group_value` | Libellé YAML `remainder_label` |

**Important** : l’agrégat est une **synthèse de présentation** ; le détail exhaustif reste dans `group_descriptive` S3.

### 3.5 Avertissement exploratoire

Si `exploratory_disclaimer: true`, ajouter (ou renforcer) un bloc texte du type :

> *Analyse exploratoire : X modalités ont été analysées, Y sont affichées (les plus défavorables). Les écarts observés sont des associations statistiques ; ils ne démontrent pas à eux seuls une causalité directe.*

---

## 4. Configuration YAML proposée

Sous `rapport_pdf.f2_compact` (client YAML ou config mémoire au run) :

```yaml
high_cardinality_threshold: 8
max_groups_displayed: 5
display_strategy: top_risk_plus_best   # top_risk | top_risk_plus_best
aggregate_remainder: true
remainder_label: "Autres modalités"
exploratory_disclaimer: true
```

Paramètres existants conservés :

```yaml
min_n_measure: 6
max_table_rows: 7
require_cpk_for_favorable: true
```

Surcharge **optionnelle par facteur** (futur) dans `entites.facteurs_analyse.<OPERATION>.<facteur>.f2_display` — hors scope v1 de cette extension, mais compatible multi-client.

---

## 5. Critères de ranking

**Réutiliser strictement** le ranking S3 — identifiant `pct_hors_tol_then_cpk_then_risk_to_limit` (`systems/s3/group_descriptive.py`).

Ordre de tri (du plus défavorable au plus favorable) :

1. **`out_of_tolerance_rate`** — décroissant (% hors tolérance le plus élevé en premier) ;
2. **`cpk`** — croissant (Cpk le plus faible en premier ; `inf` si absent) ;
3. **`risk_to_limit_score`** — décroissant (proximité / dépassement des limites LTI/LTS selon `worse_direction`).

**Interdit** : créer un score composite opaque ou recalculer un rang en S7.

**Lecture métier** (footnote tableau, inchangée) :

> Classement : taux hors tolérance décroissant, puis Cpk croissant, puis proximité aux limites.

---

## 6. Exemple diagnostic — retaille pastille (client démo)

> Données : export traçabilité local, pièce **RD4L1A1C**, opération **FILAGE**, variable **CR1**.  
> Config : `client_config_traceability.yaml`.  
> **Aucun PDF brut généré** — projection documentaire uniquement.

### 6.1 Synthèse

| Cas | `group_by` | Groupes S3 | Groupes fiables | Test global | Mode high-cardinality ? |
|-----|------------|------------|-----------------|-------------|-------------------------|
| Retaille extérieure | `PAS_E_Niveau_Retaille` | 41 | 41 | Kruskal-Wallis, p < 0,001 | **Oui** |
| Retaille intérieure | `PAS_I_Niveau_Retaille` | 29 | 29 | Kruskal-Wallis, p < 0,001 | **Oui** |
| Fournisseur extérieur | `PAS_E_Fournisseur` | 1 | 1 | Aucun (1 groupe) | **Non** — non exploitable |
| Fournisseur intérieur | `PAS_I_Fournisseur` | 1 | 1 | Aucun (1 groupe) | **Non** — non exploitable |

### 6.2 Retaille extérieure — top défavorables (projection K=5)

| Rang | Niveau | n | Moy. CR1 | % HT | Cpk |
|------|--------|---|----------|------|-----|
| 1 | -16 | 655 | 41,73 | 7,18 % | 0,44 |
| 2 | -6,5 | 1 298 | 41,67 | 4,47 % | 0,49 |
| 3 | -3,5 | 1 449 | 41,70 | 2,35 % | 0,59 |
| 4 | -20 | 852 | 41,70 | 1,76 % | 0,49 |
| 5 | -9,5 | 1 738 | 41,69 | 0,12 % | 0,67 |

**Référence favorable** (distincte du top 5) : niveau **-1** (n=332, % HT=0 %, Cpk=1,70) — `favorable_strength: limited`.

**Autres modalités** (36 groupes, n≈37 600) : profil homogène, % HT pondéré ≈ 0 % — le signal est concentré sur quelques niveaux isolés.

### 6.3 Retaille intérieure — top défavorables (projection K=5)

| Rang | Niveau | n | Moy. CR1 | % HT | Cpk |
|------|--------|---|----------|------|-----|
| 1 | -5 | 716 | 41,70 | 6,56 % | 0,50 |
| 2 | -8 | 811 | 41,70 | 1,85 % | 0,58 |
| 3 | -1 | 4 062 | 41,66 | 0,84 % | 0,61 |
| 4 | -1,5 | 7 473 | 41,69 | 0,78 % | 0,59 |
| 5 | -3 | 2 822 | 41,68 | 0,04 % | 0,62 |

**Référence favorable** : niveau **-0,5** (n=631, % HT=0 %, Cpk=1,52) — `limited`.

**Autres modalités** (24 groupes, n≈27 700) : % HT pondéré négligeable.

### 6.4 Lecture du cas pilote

- Le test global est **significatif** ; quelques modalités portent un **fort % HT** apparent.
- Un PDF listant 28–41 lignes serait **illisible** ; la projection top-5 + favorable + Autres est **justifiée**.
- La **catégorisation métier** (neuve / usure légère / forte) reste **optionnelle** et **hors scope** de cette extension.
- **Fournisseur** sur ce périmètre : **non exploitable** (une seule modalité) — pas de PDF comparatif.

### 6.5 Dette données (note, hors implémentation)

Les niveaux retaille peuvent apparaître sous formats hétérogènes (`-6,5` vs `-6`) — fragmentation artificielle des groupes. Une normalisation S2 (virgule décimale) réduirait la cardinalité ; indépendant du mode high-cardinality.

---

## 7. Architecture cible

### 7.1 Répartition des responsabilités

| Couche | Rôle | Modification |
|--------|------|--------------|
| **S3** `group_descriptive` | Stats exhaustives, ranks, IC95, warnings | **Aucune** (pipeline inchangé) |
| **S7** `f2_compact_selection` | Filtre fiabilité → `rows_reliable` | **Étendre** : détection seuil + `rows_display` |
| **S7** `f2_high_cardinality` (nouveau module) | Projection top K + best + remainder | **Créer** (logique isolée, appelée par selection/blocks) |
| **S7** `f2_compact_blocks` | Tableaux, synthèse, disclaimer | **Étendre** : consommer `rows_display` |
| **S7** `f2_compact_charts` | Boxplot | **Étendre** : `chart_include_group_values` = groupes affichés |
| **S4** | Génération PNG | **Aucune** (filtre déjà via intent) |
| **YAML** | Seuils, libellés, stratégie | **Ajouter** clés sous `f2_compact` |

### 7.2 Flux de données

```text
group_descriptive.rows (S3, N groupes)
    → build_f2_compact_selection() → rows_reliable (M groupes, M peut = N)
    → if M > high_cardinality_threshold:
          build_high_cardinality_display(rows_reliable, cfg, df_propre?)
              → rows_display (≤ K + 1 + 1)
    → build_f2_compact_document() utilise rows_display pour :
          group_comparison_table, key_indicators, charts, statistical_reliability (mode HC)
```

### 7.3 Calcul « Autres modalités »

- **Préféré** : fonction pure (emplacement proposé : `systems/s3/group_descriptive.py` en **helper importable**, sans changer la sortie pipeline S3) appelée depuis S7 avec `df_propre` + liste des `group_value` restants → % HT et Cpk exacts sur le pool.
- **Fallback** : moyennes / % HT pondérés depuis les rows S3 ; Cpk affiché « — ».

### 7.4 Multi-client / config-driven

- Seuils et libellés depuis **YAML client** (`rapport_pdf.f2_compact`).
- Aucune règle retaille, pièce ou colonne hardcodée en S7.
- Compatible tout facteur qualitatif à cardinalité élevée (OF, lot, matrice, retaille…).
- Pattern / denylist existants (`group_value_pattern`, `group_value_denylist`) s’appliquent **avant** la projection.

---

## 8. Hors scope

| Élément | Statut |
|---------|--------|
| Catégorisation métier automatique (buckets neuve / usée…) | Hors scope — chantier YAML / métier séparé |
| Modèle multi-facteurs | Hors scope (F3) |
| F3 | Hors scope |
| PDF généré dans la PR spec | **Interdit** |
| Modification code S3 / S4 / S7 | **Interdit** dans cette étape (spec seule) |
| Modification `client_config*.yaml` | **Interdit** dans cette étape |
| Normalisation retaille S2 | Recommandée en parallèle, non bloquante |

---

## 9. Critères d’acceptation (implémentation future)

| # | Critère |
|---|---------|
| 1 | Avec 41 groupes fiables (fixture ou retaille), tableau principal ≤ `max_table_rows` lignes dont « Autres modalités » |
| 2 | Boxplot et fiabilité n’affichent que les groupes de `rows_display` en mode HC |
| 3 | `rows_reliable` complet conservé dans `selection_meta` / trace |
| 4 | Ranking identique à S3 (aucun re-rank S7) |
| 5 | Disclaimer exploratoire présent si `exploratory_disclaimer: true` |
| 6 | Cas 1 seul groupe → pas de mode HC, message non exploitable |
| 7 | Tests S7 dédiés ; pas de régression F2 compact standard (≤ seuil) |
| 8 | Zéro règle retaille / client en dur |

---

## 10. Références

- F2 compact v1 : [P7-F2-COMPACT-SPEC.md](./P7-F2-COMPACT-SPEC.md)
- Ranking S3 : `systems/s3/group_descriptive.py` — `RANKING_METHOD_ID`
- Sélection v1 : `systems/s7/f2_compact_selection.py`
- Troncature tableau v1 : `systems/s7/f2_compact_blocks.py` — `max_table_rows`

---

## 11. Prochaine étape

1. Valider cette spec (revue produit / métier).
2. Implémenter extension S7 + tests (PR dédiée, sans PDF retaille en CI).
3. Activer config en mémoire sur cas pilote retaille ; générer PDF **après** implémentation.
4. Optionnel : `value_buckets` retaille dans YAML client (catégorisation métier complémentaire).
