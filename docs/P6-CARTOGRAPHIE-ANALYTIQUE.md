# P6 — Cartographie analytique industrielle

> **Statut** : SPEC — à valider avant implémentation  
> **Version** : 1.0 — 2026-05-28  
> **Prérequis** : `docs/VISION.md`, `docs/PHILOSOPHY.md`, `docs/S3.md`, `docs/S3-extended.md`  
> **Suite** : `docs/P7-RAPPORT-METIER.md` (rendu PDF, dépend de P6)  
> **Ne pas confondre** : **P5** = `eta_squared` et extensions statistiques (`docs/S3-extended.md` § P5)

---

## 1. Objectif du chantier P6

Définir et implémenter le **socle méthodologique** d’IndustrIA : une grille explicite de la data science qualité industrielle, de l’analyse **univariée** jusqu’aux analyses **multivariées**, **réduction de dimension** et **temporelles/SPC**.

**But** : qu’une question utilisateur soit routée vers la **bonne famille d’analyse** (Python), puis vers les **spécialistes**, **graphiques** et **sorties JSON** adaptés — sans laisser le LLM choisir les méthodes.

**Hors périmètre P6** : mise en page PDF premium (→ **P7**), monitoring temps réel (→ **S8**), ingestion TimescaleDB, UI production.

**Succès P6** : on peut répondre honnêtement :

> « IndustrIA couvre la chaîne univariée → bivariée (tous les cas) → multivariée → temporelle, avec règles de validité et garde-fous EN9100. »

---

## 2. Problème actuel

### 2.1 Ce qui fonctionne

- Pipeline **S1→S7** validé sur LISI (portrait, comparaison matrices, Cpk, Kruskal, Dunn, corrélation partielle).
- **15 spécialistes** dans `specialists/` branchés via `systems/s3/dispatcher.py`.
- Intentions S1 : `conformite`, `comparaison_groupes`, `tendance`, `anomalie`, `portrait_statistique`, `diagnostic_causal`, `analyse_complete`.
- Pre-gates S3, judge, `group_ranking`, formatage p-values (`systems/stats_format.py`).

### 2.2 Ce qui manque structurellement

| Lacune | Symptôme |
|--------|----------|
| **Pas de typage « famille d’analyse » explicite** | Le dispatch suit une **intention linguistique**, pas une matrice statistique (quanti×quanti, quali×quali, etc.). |
| **Quali vs quali** | Pas de specialist dédié (chi², Cramer, table de contingence conforme OUI/NON). |
| **Quanti vs quanti** | `correlation` existe mais pas comme parcours complet (scatter, régression simple systématique). |
| **Multivarié explicatif** | `regression` présent, peu routé ; pas d’importance variables « métier ». |
| **Réduction de dimension** | PCA / MCA / FAMD : vision `AGENTS.md`, **non** dans v4 LISI. |
| **Carte intentions ↔ méthodes** | `diagnostic_causal` S3 = seulement `anova_kruskal` ; η² en **P5** pas encore branché. |
| **Cohérence S4** | Graphiques liés à l’**intention**, pas à la **famille** (ex. `analyse_complete` sans QQ si portrait implicite). |

### 2.3 Conséquence

IndustrIA est un **ensemble de spécialistes assemblés par mot-clé**, pas encore une **plateforme méthodologique nommée**. P6 corrige cela sans casser S1–S7.

---

## 3. Principes non négociables

Alignés sur `docs/PHILOSOPHY.md` :

1. **Python certifie** tous les chiffres, verdicts (`normale` / `non_normale`, `loi_retenue`, significativité, Cpk, η²).
2. **LLM reformule uniquement** (S5/S6) — modèle local ~7b (S1) / ~14b (S5–S6), file FIFO, pas de zoo d’agents LLM par cas.
3. **Pas de causalité abusive** (§28) : associations et variance expliquée, jamais « X cause Y » sans étude dédiée.
4. **Pas de nouveau pipeline parallèle** : extension de **S3 dispatcher + executor**, **S4 dispatcher**, enrichissement `intent.json` si besoin.
5. **ClientContext** seul accès au YAML ; tolérances LTI/LTS depuis config.
6. **Pre-gates + judge** avant toute méthode paramétrique lourde (ANOVA si non-normalité, n petit, etc.).
7. **Une question → une ou plusieurs familles** ; si ambiguïté, S1 clarification ou famille primaire + warning.

---

## 4. Modèle conceptuel : familles d’analyse

### 4.1 Typage des variables (entrée S2 / S1)

Après S2, chaque colonne du `df_propre` est classée :

| Type | Définition IndustrIA | Exemples LISI |
|------|----------------------|---------------|
| `numeric_continuous` | Mesure capteur | CR90_INTRADOS_FORME, Vrillage_Libre_S50 |
| `numeric_tolerance` | Numérique + LTI/LTS YAML | CR*, cotes géométriques |
| `categorical` | Faible cardinalité, regroupement | Ref_Matrice, PAS_E_Fournisseur |
| `binary` | 2 modalités | conforme OUI/NON (dérivé) |
| `datetime` | Axe temps | Date |
| `identifier` | OF, lot (si ajouté) | — |

**Responsable** : extension **S2 `validator.py`** + champs optionnels dans `intent` (`variable_roles`).

### 4.2 Les 7 familles P6

| ID | Famille | Condition de détection (Python) | Question type |
|----|---------|-------------------------------|---------------|
| **F1** | `univariate` | 1 variable numérique cible, pas de `group_by` | « Analyse-moi CR90 » |
| **F2** | `bivariate_quali_quanti` | 1 quali + 1 quanti (cible) | « La matrice influence-t-elle CR90 ? » |
| **F3** | `bivariate_quanti_quanti` | 2+ numériques, pas de regroupement demandé | « Lien CR70 / CR90 » |
| **F4** | `bivariate_quali_quali` | 2 qualitatives (ou quali + binaire) | « Matrice vs taux de non-conformes » |
| **F5** | `multivariate_explanatory` | 1 cible + ≥2 explicatives | « CR90 expliqué par matrice + machine » |
| **F6** | `dimension_reduction` | ≥3 numériques, intent exploration | « Profils de défauts sur 5 cotes » |
| **F7** | `temporal_spc` | axe temps actif ou intention `tendance` / `anomalie` | « Dérive depuis lundi » |

Une analyse peut déclencher **plusieurs familles** (ex. `analyse_complete` = F1 par variable + F3 + F2 si `group_by`).

### 4.3 Fonction cible S3 (à implémenter en P6)

```text
classify_analysis_families(intent, df_schema, context) -> list[AnalysisFamilyPlan]

AnalysisFamilyPlan:
  family_id: F1..F7
  target_variables: list[str]
  grouping_variables: list[str]
  specialists: list[str]      # ordre d'exécution
  chart_types: list[str]      # pour S4
  priority: int                 # ordre rapport P7
  warnings: list[str]
```

**Règle** : `classify_*` est **100 % Python**. L’`intention` S1 reste un **raccourci linguistique** qui pré-sélectionne des familles, mais ne les remplace pas.

### 4.4 Mapping intention S1 → familles (compatibilité)

| Intention S1 | Familles déclenchées (défaut) |
|--------------|-------------------------------|
| `portrait_statistique` | F1 |
| `comparaison_groupes` | F2 |
| `diagnostic_causal` | F2 (+ F5 partiel si P5 η²) |
| `conformite` | F1 + F7 (zscore/spc) |
| `tendance` | F7 |
| `anomalie` | F7 |
| `analyse_complete` | F1 (× variables) + F3 + F2 si `group_by` + F1 cp_cpk |

Les intentions **ne disparaissent pas** : elles orientent S5/S7/P7. P6 ajoute la couche **famille** sous S3.

---

## 5. Détail par famille

### F1 — Analyse univariée (`univariate`)

**Objectif** : décrire une variable, tester normalité, ajuster une loi, quantifier conformité.

| Élément | Spécification |
|---------|---------------|
| **Spécialistes** | `descriptive`, `normality`, `distribution_fit`, `cp_cpk` (si LTI/LTS) |
| **Graphiques S4** | `histogram` (+ densité loi), `boxplot` univarié, `qqplot` |
| **Sorties clés** | n, moments, % hors tol, `verdict_normalite`, `loi_retenue`, Cpk/Cp |
| **Pre-gates** | n&lt;5 → skip Cpk ; n&lt;8 → skip normalité |
| **État** | ✅ P1 / P4 portrait — **référence** pour les autres familles |

**Extensions P6** :

- Harmoniser champs `descriptive` avec `systems/stats/portrait_metrics.py` (IC95, outliers IQR).
- Documenter verdict portrait NO-GO (% hors tol &gt; 0) comme règle S7, pas S3.

---

### F2 — Bivariée quali × quanti (`bivariate_quali_quanti`)

**Objectif** : comparer une mesure entre groupes (matrice, machine, fournisseur…).

| Élément | Spécification |
|---------|---------------|
| **Spécialistes** | `descriptive` par groupe (agrégat), `anova_kruskal`, `dunn_posthoc` (auto si sig.), `cp_cpk` par groupe si tolérances, `group_ranking` |
| **Graphiques** | `boxplot` par `group_by`, tableaux synthèse (moyenne, % hors tol par groupe) |
| **Tests** | Normalité globale ou par groupe → ANOVA si OK, sinon Kruskal-Wallis |
| **Sorties clés** | p-value affichée, `paires_significatives`, `pire_groupe`, IC95 % hors tol par groupe (cible P6) |
| **État** | ✅ partiel (Kruskal, Dunn, ranking) — ❌ tableaux type rapport vrillage, IC sur proportions |

**Extensions P6** :

- Specialist **`group_descriptive`** (ou enrichir `pivot`) : moyenne, écart-type, n, % hors tol **par groupe**.
- Règle **effectif minimum par groupe** (ex. n≥6 mesures ou n≥5 OF) — aligné vrillage.
- **P5** : `eta_squared` en tête si `diagnostic_causal` + groupes (variance expliquée, pas causalité).

**Référence métier** : rapport vrillage (matrices, % OF hors tol, Cpk par matrice).

---

### F3 — Bivariée quanti × quanti (`bivariate_quanti_quanti`)

**Objectif** : mesurer association entre deux mesures continues.

| Élément | Spécification |
|---------|---------------|
| **Spécialistes** | `correlation` (Pearson, Spearman, Kendall), `regression` (simple si 1 prédicteur) |
| **Graphiques** | `scatter`, matrice corrélations (heatmap si &gt;2 variables) |
| **Pre-gates** | n&lt;10 → warning ; relation non linéaire → privilégier Spearman |
| **État** | ✅ `correlation` sous `analyse_complete` — ❌ scatter S4 dédié, intention S1 « corrélation » |

**Extensions P6** :

- Intention S1 optionnelle `association_variables` ou détection F3 depuis 2 variables explicites.
- S4 : `scatter` + ligne de régression dans `chart_builder.py`.
- Interdiction LLM : « corrélation forte » sans rappeler **association**, pas causalité.

---

### F4 — Bivariée quali × quali (`bivariate_quali_quali`)

**Objectif** : lien entre deux facteurs catégoriels (ex. matrice × statut conforme).

| Élément | Spécification |
|---------|---------------|
| **Spécialistes** | **Nouveau** `contingency` : table, chi², Fisher si effectifs faibles, V de Cramer |
| **Graphiques** | barres empilées, heatmap proportions |
| **Dérivation conforme** | Règle Python : variable binaire `hors_tolerance` ou `conforme` depuis LTI/LTS |
| **État** | ❌ non implémenté |

**Extensions P6** (vague 2) :

- `specialists/contingency.py` + tests `systems/s3/tests/`.
- S1 : intention `comparaison_conformite` ou détection si question « plus de NC sur matrice X ».

---

### F5 — Multivariée explicative (`multivariate_explanatory`)

**Objectif** : expliquer une cible numérique (ou binaire) par plusieurs facteurs.

| Élément | Spécification |
|---------|---------------|
| **Spécialistes** | `regression` (OLS), importance variables (coefficients standardisés) ; plus tard RF/SHAP **hors P6 v1** |
| **Graphiques** | barres importance, résidus |
| **Pre-gates** | colinéarité, n &gt; 10×p |
| **État** | ⚠️ specialist existe, routage faible |

**Extensions P6** (vague 3) :

- Intent champs : `target`, `predictors[]`.
- Garde-fous : pas de prédiction « boîte noire » en rapport client sans section limites.

---

### F6 — Réduction de dimension (`dimension_reduction`)

**Objectif** : résumer plusieurs variables en axes interprétables (exploration, pas preuve seule).

| Méthode | Usage |
|---------|--------|
| **PCA** | ≥3 variables numériques corrélées |
| **MCA** | ≥3 variables qualitatives |
| **FAMD** | mixte quanti + quali |

| Élément | Spécification |
|---------|---------------|
| **Spécialistes** | **Nouveau** `pca_exploratory` (v1 : PCA seulement) |
| **Graphiques** | biplot simplifié, variance expliquée par axe |
| **Règle client** | Toujours `interpretation_limits` : axes = synthèse, pas décision seule |
| **État** | ❌ |

**Extensions P6** (vague 4 — après F2–F4 stables) :

- Ne pas livrer PCA sans libellés métier des axes (template S5 ou Python).

---

### F7 — Temporel / SPC (`temporal_spc`)

**Objectif** : dérives, anomalies, cartes de contrôle.

| Élément | Spécification |
|---------|---------------|
| **Spécialistes** | `mann_kendall`, `ewma_cusum`, `zscore`, `spc` |
| **Graphiques** | `timeseries`, cartes Shewhart (via enterprise ou S4) |
| **Intentions** | `tendance`, `anomalie`, `conformite` |
| **État** | ✅ specialists — ⚠️ S8 monitoring non branché |

**Extensions P6** :

- Lier F7 à filtres temporels S1 (`Date_debut`, `EVENT_*`).
- Préparer contrat sorties pour **S8** (alertes P1–P4 sans LLM continu).

---

## 6. Orchestration S3 révisée

### 6.1 Flux

```text
intent + df_schema
    → classify_analysis_families()
    → pour chaque plan:
          pre-gates (existant + par famille)
          executor (familles portrait | multi_target | single_target | correlation)
          judge (règles étendues)
          dunn_posthoc si anova_kruskal significatif
    → group_ranking si F2
    → metrics_summary enrichi (familles exécutées)
```

### 6.2 Familles d’exécution executor (existant + P6)

| Famille executor | Spécialistes |
|------------------|--------------|
| `portrait` | descriptive, normality, distribution_fit |
| `multi_target` | cp_cpk, zscore, correlation, … |
| `single_target` | anova_kruskal |
| `grouped` (P6) | group_descriptive, contingency |
| `pairwise` (P6) | correlation entre paires intent |

### 6.3 Judge — règles additionnelles P6

| Règle | Action |
|-------|--------|
| ANOVA demandée + `non_normale` | Invalider ANOVA, conserver Kruskal |
| F4 chi² + effectif &lt;5 dans ≥25 % cellules | Fisher + warning |
| F3 corrélation + n&lt;30 | Warning « faible puissance » |
| F6 PCA + n&lt;50 | Skip ou warning |

---

## 7. Orchestration S4 révisée

**Principe** : `chart_types` dérivés de **`AnalysisFamilyPlan`**, pas seulement de `intention`.

| Famille | Graphiques par défaut |
|---------|----------------------|
| F1 | histogram, boxplot, qqplot |
| F2 | boxplot, table_summary (P6) |
| F3 | scatter, correlation_heatmap |
| F4 | stacked_bar, contingency_heatmap |
| F5 | importance_bar, residual_plot |
| F6 | pca_scree, pca_biplot |
| F7 | timeseries, spc_chart |

Plafonds : `rapport_pdf.max_graphiques_*` + YAML `analyse_etendue`.

---

## 8. Contrat sorties pour S5 / P7

Chaque famille produit un **bloc métier typé** (JSON) consommable par S5 templates et P7 :

```json
{
  "family_id": "bivariate_quali_quanti",
  "summary": {
    "critical_group": "O5220910A4-1",
    "best_group": "O5220910A3-0",
    "pct_hors_tol_critical": 47.5,
    "cpk_min": -0.007
  },
  "certified_phrases": [],
  "interpretation_limits": "Association matrice / mesure — pas causalité certaine."
}
```

S5 ne invente pas ces champs ; il reformule `certified_phrases` et `summary`.

---

## 9. P5 (stats) dans la cartographie

**P5** reste un chantier **statistique** distinct, intégré à P6 :

| Livrable P5 | Famille | Rôle |
|-------------|---------|------|
| `eta_squared` | F2, F5 | % variance expliquée par facteur (langage §28) |
| Cpk ajusté loi | F1 | déjà partiel via `distribution_fit` |
| IC95 groupes | F2 | fiabilité type vrillage |

P6 **référence** P5 ; ne pas dupliquer la spec η² ici — voir `docs/S3-extended.md`.

---

## 10. Contraintes modèle local (Ollama)

- **Pas** d’agent LLM par famille : classification **Python**.
- S1 : 7b pour désambiguïsation entités/intentions.
- S5–S6 : 14b, reformulation courte, **templates d’abord**.
- Contexte limité : envoyer au LLM des **résumés JSON compacts** (≤7 clés), jamais le DataFrame.

---

## 11. État d’implémentation (matrice)

| Famille | Specialists | S4 | S1 intent | Tests LISI | Priorité vague |
|---------|-------------|-----|-----------|------------|----------------|
| F1 | ✅ | ✅ | ✅ | ✅ | Maintenance |
| F2 | ⚠️ | ⚠️ | ✅ | ✅ | **Vague 1** |
| F3 | ⚠️ | ❌ scatter | ⚠️ | partiel | **Vague 1** |
| F4 | ❌ | ❌ | ❌ | ❌ | **Vague 2** |
| F5 | ⚠️ | ❌ | ❌ | ❌ | Vague 3 |
| F6 | ❌ | ❌ | ❌ | ❌ | Vague 4 |
| F7 | ✅ | ⚠️ | ✅ | partiel | Vague 2 + S8 |

---

## 12. Plan d’implémentation recommandé (après validation spec)

### Phase 0 — Documentation et tests de non-régression

- Valider cette spec + P7.
- Suite pytest S3/S4/S5 existante verte.

### Phase 1 — Cerveau méthodologique (cœur P6)

1. `systems/s3/analysis_families.py` : `classify_analysis_families`, `AnalysisFamilyPlan`.
2. Refactor `dispatcher.py` : intentions → plans ; plans → specialists.
3. Tests unitaires classification (cas limites n, types colonnes).
4. Enrichir `metrics_summary` avec `families_executed[]`.

### Phase 2 — F2 renforcement (vrillage)

1. `group_descriptive` ou extension `pivot`.
2. IC95 sur moyennes et % hors tol par groupe.
3. S4 tableaux synthèse + code couleur documenté.
4. Intégration **P5 η²** quand spec P5 validée.

### Phase 3 — F3

1. S4 scatter + intention / détection 2 variables.
2. Tests corrélation + régression simple.

### Phase 4 — F4

1. `contingency.py` + graphiques.
2. S1 synonymes « taux de conformité », « non-conformes ».

### Phase 5 — F5, F6, F7/S8

- Selon temps de stage ; F6 dernier (risque pédagogique).

**P7 (rapport)** : démarrer **après Phase 1–2** minimum (sorties F2 structurées), pas avant.

---

## 13. Critères d’acceptation P6

- [ ] Toute question de démo LISI mappe à au moins une `family_id` documentée.
- [ ] `classify_analysis_families` couvert par tests sans LLM.
- [ ] F2 produit ranking + tableau groupe comparable au vrillage (chiffres, pas mise en page).
- [ ] F3 produit scatter + coefficients corrélation certifiés.
- [ ] F4 spec validée + au moins un test LISI matrice×conforme.
- [ ] Aucune régression sur portrait F1 (tests P4/P1 verts).
- [ ] Documentation `docs/S3.md` mise à jour avec renvoi P6.

---

## 14. Documents liés

| Fichier | Lien |
|---------|------|
| `docs/P7-RAPPORT-METIER.md` | Rendu PDF à partir des sorties P6 |
| `docs/S3-extended.md` | Portrait, P5 η² |
| `docs/PHILOSOPHY.md` | §28 langage, règles LLM |
| `docs/S1.md` | Intentions et agents |

---

*Chantier P6 — socle méthodologique. Toute implémentation doit citer la version de ce document en en-tête de PR.*
