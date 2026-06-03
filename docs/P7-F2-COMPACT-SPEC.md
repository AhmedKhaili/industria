# P7-F2 compact — Spec formelle (Phase B → v1 candidate)

> **Statut** : **IMPLÉMENTÉ** — v1 candidate gelée (code F2 compact figé sur `0d7f43d`)  
> **Version doc** : 2.0 — 2026-06-03 (alignement C1 → D4b)  
> **Remplace** : tunnel `narratif_metier` long (P7-F2a–c, gelé via `f2_narratif_enabled: false`)  
> **Référence métier** : rapport vrillage LISI (comparaison matrice × CR50, ~5 p.)  
> **Non-cible** : rapport portrait F1 ; agrégation OF (hors v1)

---

## 0. Objet

PDF **F2 compact** pour l’intention S1 `comparaison_groupes` : comparer **une mesure quantitative** ventilée par **un facteur qualitatif** (matrice, machine, fournisseur…).

Objectifs atteints en v1 :

- **4 à 6 pages** (LISI RD4 CR50 : 5 pages).
- **Cohérence** : verdict, tableaux et textes lisent la **même** sélection filtrée (`F2CompactSelection`).
- **Densité métier** : inspiré du rapport vrillage, sans narratif long.
- **Zéro LLM en S7** ; zéro chiffre inventé ; seuils et filtres depuis **YAML** (pas de règles métier LISI en dur).

**Implémentation** : `systems/s7/f2_compact_*.py`, branchement `a1_assembler`, rendu `renderer_stub` (mode `f2_compact`), filtre boxplot S4 via `intent["chart_include_group_values"]` (D3).

---

## 1. Périmètre et déclenchement

| Élément | Règle (v1) |
|---------|------------|
| Intention S1 | `comparaison_groupes` (famille P6 **F2** `bivariate_quali_quanti`) |
| Donnée S3 requise | Bloc `group_descriptive` (`measure` ou `aggregated_unit` si config active) |
| Test global | `anova_kruskal` (ou équivalent) dans `specialist_results` |
| Graphique | 1 boxplot S4 par variable × `group_by`, **groupes fiables uniquement** si liste intent fournie |
| Mode rendu | `meta.render_mode = "f2_compact"` |
| Activation | **`rapport_pdf.f2_compact_enabled: true`** (défaut **`false`** ; LISI compact = flag + sous-config en mémoire ou YAML) |

**Hors périmètre v1** : F3–F5, RAG, LLM corps du rapport, modification S3, agrégation OF, narratif long, renderer enterprise séparé.

---

## 1.1 Libellés métier, titre et question

| Source autorisée | Usage |
|------------------|--------|
| YAML client | `libelle_court` / tolérances LTI/LTS, `entites.facteurs_analyse` |
| Intent | Question technique conservée pour S1 ; **pas** comme seul titre client |

**Titre métier (cover + synthèse)** — `compact_report_title()` :

```text
Comparaison du {label_variable_yaml} selon la {label_facteur_yaml}
```

Exemple LISI validé : *Comparaison du Vrillage intrados CR50 selon la matrice*.

**Cover F2 compact** :

- Titre métier en gras ;
- Ligne grise : `Référence technique : {question_originale}` (tag S1, non réécrit).

**Interdit** : paraphrase physique absente du YAML ; titre = question brute seule.

---

## 2. Structure du rapport compact (blocs JSON)

Ordre fixe — `F2_COMPACT_BLOCK_ORDER` dans `f2_compact_blocks.py` :

| # | `block_type` | Rôle |
|---|--------------|------|
| 1 | `cover` | Identité, titre métier, référence technique |
| 2 | `business_synthesis` | Titre + cadrage niveau mesure + variable / tolérances |
| 3 | `conclusion_key` | 3 paragraphes (pire / favorable ou à confirmer / prudence) |
| 4 | `verdict` | Bandeau + puces (prioritaire, verdict, point d’attention) |
| 5 | `business_context` | Contexte + définition hors tolérance **LTI/LTS** |
| 6 | `key_indicators` | Tableau indicateurs (prioritaire, % HT, Cpk min, favorable) |
| 7 | `group_comparison_table` | Tableau principal (≤ `max_table_rows`) |
| 8 | `how_to_read_cpk` | Pédagogie Cpk (seuils YAML) |
| 9 | `statistical_reliability` | **Tableau** IC95 (pas liste verticale) |
| 10 | `charts` | Boxplot filtré |
| 11 | `statistical_test` | Kruskal / ANOVA |
| 12 | `business_reading` | ≤ 3 sections (prioritaire / intermédiaires / favorable ou à confirmer) |
| 13 | `final_verdict` | Hiérarchie ≤ 5 + paragraphes |
| 14 | `excluded_groups` | Groupes non exploités + motifs **métier** |
| 15 | `interpretation_limits` | Association ≠ causalité |
| — | `traceability` | (optionnel quality gate) |

**Page cible** : 4–6 pages A4.

---

## 3. Sélection — groupes fiables (C1)

Module : `f2_compact_selection.build_f2_compact_selection()`.

Un groupe entre dans **`rows_reliable`** si :

1. `n` ≥ seuil (`rapport_pdf.f2_compact.min_n_measure` ou défaut aligné S3) ;
2. Pas de valeur manquante bloquante ;
3. `group_value` conforme au **pattern** YAML (`group_value_pattern`) — priorité : `entites.facteurs_analyse.<OP>.<facteur>.group_value_pattern` si `colonne` = `group_by`, sinon `rapport_pdf.f2_compact.group_value_pattern` ;
4. Absent de la **denylist** (`group_value_denylist`) ;
5. Classement S3 (`rank`) conservé parmi les fiables.

**Pire groupe fiable** : `worst_reliable` (rang minimal parmi fiables).

**Référence favorable** (D2) — `_select_favorable_reference()` :

| `favorable_strength` | Critère (résumé) | Affichage |
|----------------------|------------------|-----------|
| `robust` | Cpk si requis ; IC95 % HT étroit si `max_ci95_ht_width_pct` YAML explicite | « Référence favorable la plus robuste » |
| `limited` | Meilleur profil mais IC95 large ou seuil largeur non configuré | « Référence favorable à confirmer » |
| `none` | Pas de contraste fiable | Message d’absence |

**Dégénéré** : aucun fiable → message explicite, verdict prudent (pas de NO-GO sur données non fiables).

---

## 4. Exclusion — groupes non exploités (C1, D4)

**Section** `excluded_groups` — jamais dans tableau principal, conclusion, verdict prioritaire, boxplot.

| Motif (`exclusion_reason`) | Libellé client | Détail client (PDF) |
|--------------------------|----------------|---------------------|
| `effectif_insuffisant` | Effectif insuffisant | `n=X < min_n=Y` |
| `pattern_yaml_non_respecte` | Hors format matrice | *Valeur non conforme au format attendu des matrices* (pas de regex brut) |
| `groupe_parasite` | Groupe exclu… | Formulation métier (denylist) |
| `valeur_manquante` | … | … |

Le **pattern regex** reste en trace interne (`selection_meta` / `detail` assembleur), pas dans le PDF client.

---

## 5. Tableau principal

Colonnes : Groupe, n, Moyenne, Écart-type, % hors tol., Cp, Cpk, Rang, **Niveau**.

**Niveau** — `compact_level_display()` (D4) :

- `Critique` **uniquement** si verdict **NO-GO** (seuils P1 YAML franchis) ;
- sinon S3 `critique` → **Prioritaire** ; `surveillance` → **Surveillance renforcée**.

**Indicateurs clés** (D4/D4b) :

- Pire : **Matrice prioritaire** / **Groupe prioritaire** ;
- Favorable : libellé selon `favorable_strength` (`favorable_indicator_label()`), pas « Groupe le plus favorable » si `limited`.

Formats : virgule française ; % et IC95 harmonisés avec §8.

---

## 6. Synthèse et conclusion

**Conclusion clé** : métriques formatées (`_fmt_pct`, `_fmt_num`, `ci95_display`) — pas de `0.4 %` ni IC95 bruts S3 dans les paragraphes (D4b).

**Verdict** — `compute_compact_verdict()` (D1) :

- NO-GO seulement si % HT ou Cpk pire groupe franchit seuils **YAML** P1 ;
- sinon **SURVEILLANCE** + ton `point_attention` ;
- **indépendant** du `severity_label` S3.

Bandeau : libellés `rapport_pdf.verdict_bandeaux` (tiret long supporté PDF — `formatters._PRINTABLE_RE`).

---

## 7. Lecture Cp/Cpk

Bloc `how_to_read_cpk` — seuils depuis YAML (`f2_pedagogy`).  
**Limite v1** : le texte pédagogique peut encore dire « situation critique » pour Cpk &lt; 1,0 (seuil process, pas niveau groupe).

---

## 8. Fiabilité statistique (D3, D4, D4b)

**Tableau** avec colonnes : Groupe, n, Moyenne, IC95 moyenne, % hors tolérance, IC95 % hors tolérance, Cpk, Statut fiabilité.

**Format IC95** — `ci95_display()` (`f2_compact_display.py`) :

- Moyenne : 3 décimales, virgule — ex. `[0,063 ; 0,072]` ;
- % HT : 2 décimales, pas de `-0,0 %` — ex. `[0,15 % ; 1,30 %]`, `[0,00 % ; 0,69 %]` ;
- source S3 `low`/`high` ; S7 ne recalcule pas.

Même formatage réutilisé dans **paragraphes** (conclusion, lecture métier) via `_row_metrics_phrase()` (D4b).

**Casse codes** : matrices `O52…` préservées en PDF (`clean_cell` / pas de `.lower()` sur référents).

---

## 9. Graphique boxplot (D3)

- `build_compact_chart_items()` régénère le boxplot depuis `df_propre` si disponible ;
- `intent["chart_include_group_values"]` = liste des `group_value` fiables ;
- S4 : filtre uniquement si clé présente et non vide (`chart_builder.py`).

Groupes exclus **absents** du graphique.

---

## 10. Verdict métier (bloc final)

`final_verdict` : hiérarchie ≤ 5 avec `severity_display` compact ; paragraphes sans causalité abusive.

---

## 11. Provenance

| Couche | Rôle |
|--------|------|
| S3 | `group_descriptive`, IC95, ranks, warnings |
| YAML | Seuils, patterns, libellés, verdict |
| S7 | Assemblage, formatage, filtrage présentation **uniquement** |
| S4 | PNG boxplot |
| S5/S6/LLM | **Non utilisés** pour le corps F2 compact v1 |

---

## 12. Interdictions (toujours actives)

1. Narratif long (`f2_narratif_enabled` reste `false`).
2. Causalité abusive (quality gate).
3. Chiffre / libellé inventé.
4. Groupe exclu dans tableau, graphique, conclusion prioritaire.
5. « Critique » affiché sans NO-GO P1 (D4).
6. Regex brut côté client (D4).
7. Recalcul statistique IC95 / ranking en S7.

---

## 13. Anti-patterns F2c — statut

| Observation F2c | v1 candidate |
|-----------------|--------------|
| 14 pages, 18 lignes | ≤ 6 lignes tableau, ~5 pages LISI |
| NO-GO + 0,4 % HT | SURVEILLANCE si P1 non franchi |
| Parasites en tableau | Section non exploités |
| IC95 absents / illisibles | Tableau + formats FR |
| Titre = question technique | Titre métier + ref. technique |

---

## 14. Critères d’acceptation Phase C — bilan

| # | Critère | v1 |
|---|---------|-----|
| 1 | LISI RD4 vrillage × matrice ≤ 6 p., parasites hors tableau | OK (`lisi_rd4_cr50_vrillage_f2_compact_d4.pdf`) |
| 2 | Verdict cohérent pire groupe filtré | OK |
| 3 | Provenance S3/YAML | OK (gate + tests) |
| 4 | Causalité | OK |
| 5 | `f2_narratif_enabled: false`, flag compact dédié | OK |
| 6 | Tests S7 compact + pipeline | **116 passed** |

---

## 15. Commits de référence (C1 → D4b)

| Phase | Commit | Contenu |
|-------|--------|---------|
| C1 | `1499e4c` | Sélection groupes fiables / exclus |
| C2 | `704e144` | Blocs JSON `build_f2_compact_document` |
| C3 | `c423eec` | Branchement assembler + renderer PDF |
| D1 | `9be7dc3` | Verdict prudent, cadrage mesure, libellés |
| D2 | `c84bdd5` | Référence favorable robuste / limited |
| D3 | `974c0e5` | Tableau IC95, boxplot filtré |
| D4 + D4b | `0d7f43d` | Polish libellés, formats, cover, `f2_compact_display.py` |

---

## 16. F2 compact v1 candidate (gel documentaire)

| Élément | Valeur |
|---------|--------|
| **Commit HEAD (référence)** | `0d7f43d` — `fix(s7): polish F2 compact labels and formatting` |
| **Branche de travail** | `feat/p6-analysis-families` |
| **Dernier PDF local LISI** | `reports/lisi_rd4_cr50_vrillage_f2_compact_d4.pdf` |
| **Question technique** | `Comparer CR50_INTRADOS_VRILLAGE selon la matrice sur RD4L1A1C EQUATOR` |
| **Tests S7** | **116 passed** (dernier run doc) |
| **Narratif long** | **Désactivé** (`f2_narratif_enabled: false`) |
| **Activation compact** | Flag explicite `f2_compact_enabled: true` + `rapport_pdf.f2_compact` (pattern, `min_n_measure`, etc.) |
| **Code F2 compact** | **Figé** — pas de évolution sans nouveau chantier |

### Limites acceptées v1

- **Niveau mesure capteur** uniquement — pas d’équivalence revendiquée avec rapport vrillage OF agrégé.
- **Pas de colonne OF** dans `data/lisi_capteurs.csv` — pas d’agrégation OF en v1.
- **YAML LISI** : flag compact et `libelle_court` pas forcément persistés en prod (runs via config mémoire).
- **Mise en page** : codes matrices parfois **coupés** sur plusieurs lignes dans tableaux PDF étroits.
- **Pédagogie Cpk** : formulation « situation critique » possible (seuil Cpk, distinct du niveau groupe).
- **S4 test** : voir §17 (hors périmètre F2, non bloquant compact).

### Améliorations possibles (hors urgence)

- Persister config compact + `libelle_court` dans `configs/lisi_aerospace/client_config.yaml`.
- Smoke PDF LISI en CI non-régression.
- Césure / largeurs colonnes pour codes `O52…`.
- Pédagogie Cpk allégée en mode `f2_compact`.
- Agrégation OF si données + règle métier disponibles (chantier séparé).

---

## 17. Note technique — test S4 préexistant

**Test** : `systems/s4/tests/test_s4.py::TestS4PipelineLisi::test_tendance_timeseries`

**Échec actuel** :

```text
build_timeseries_chart() got an unexpected keyword argument 'specialist_results'
```

**Cause** : `build_charts()` passe `specialist_results=` à tous les builders ; `build_histogram` / `build_boxplot_chart` acceptent ce paramètre optionnel depuis D3, **`build_timeseries_chart` non** (signature 4 args seulement).

**Périmètre** : intention **tendance** / timeseries — **sans lien** avec F2 compact (boxplot comparatif).

**Recommandation avant merge PR** :

| Option | Effort | Verdict |
|--------|--------|---------|
| **A — Correction courte** | Ajouter `specialist_results: list[dict] \| None = None` à `build_timeseries_chart` (symétrie builders) | **Recommandé** — 1 ligne, PR dédiée ou commit chore S4 |
| B — Issue / note CI | Documenter test flaky / connu | Acceptable si merge urgent sans toucher S4 |
| C — Exclusion temporaire | `@pytest.mark.skip` avec lien issue | **Déconseillé** — masque une régression réelle du pipeline tendance |

**Impact PR F2 compact** : la branche peut être **prête à PR** côté S7 ; le merge global reste **conditionnel** si la CI exécute toute la suite S4 (14 tests, 1 échec).

---

## 18. FILAGE / pastilles — règles métier et cas F2 reportés

> **Statut** : hors campagne F2 compact v1 (export `lisi_capteurs.csv` sans colonnes/tags passage exploitables).  
> **Référence YAML** : `configs/lisi_aerospace/client_config.yaml` — **aucune règle P1/P2 ou retaille hardcodée** en S2/S3/S7 (application via `dataset.regles_nettoyage` dans `systems/s2/cleaner.py`).

### Règles métier pastille (validées dans le YAML)

| Champ / colonne | Règle métier | Expression YAML actuelle |
|-----------------|--------------|-------------------------|
| `PAS_E_Numero_Passage`, `PAS_I_Numero_Passage` | Valeurs **uniquement** `P1` ou `P2` ; toute autre valeur → non exploitable / anomalie | `valeurs_valides: ["P1", "P2"]` + `action: supprimer_si_invalide` |
| `PAS_E_Niveau_Retaille`, `PAS_I_Niveau_Retaille` | Seules les valeurs **≤ 0** pour les comparaisons métier ; strictement positives → exclues | `condition: "<= 0"` + `action: supprimer_si_invalide` |

Chemins exacts : `dataset.regles_nettoyage.PAS_E_Numero_Passage` (et symétriques `_I_`, `Niveau_Retaille`).

**Limite actuelle (données, pas règles)** : l’export LONG ne contient ni colonnes `PAS_*_Numero_Passage`, ni tags `Tag/Value` avec `Value` renseigné pour le passage ; les tags `PAS_E` / `PAS_I` existent mais sans `Value` pivotable. S2 **n’efface pas** ces règles : les colonnes sont **absentes** → règles **skipped** (`colonne_absente`).

### Cas F2 FILAGE / pastille à tester plus tard (après enrichissement export)

Prérequis données : colonnes wide ou tags LONG `PAS_E_Numero_Passage` / `PAS_I_Numero_Passage` avec valeurs `P1`/`P2`, et retaille ≤ 0 appliquée par S2 avant pivot.

| Cas envisagé | Question type | Variable | Facteur | Notes |
|--------------|---------------|----------|---------|-------|
| Passage ext. | `Comparer CR1 selon le numero de passage pastille ext sur {piece} au filage` | `CR1` (ou autre `CRx`) | `PAS_E_Numero_Passage` | Vérifier effectifs P1 vs P2 ; groupes hors {P1,P2} → **non exploités** |
| Passage int. | Idem pastille **int** | `CR1` | `PAS_I_Numero_Passage` | Même règle P1/P2 |
| Passage combiné | Comparaison si les deux colonnes sont dans le wide post-pivot | `CR1` | `PAS_E` + `PAS_I` (à trancher métier) | S1 peut résoudre `group_by` bi-colonnes — à valider avec métier |

**Contrôles attendus lors des futurs runs** :

- S2 `cleaning_stats.rules` : `applied` sur les 4 colonnes (pas `skipped`) ;
- valeurs passage ∉ {P1,P2} dans `df_anomalies` ou absentes de `df_propre` ;
- retaille > 0 exclue avant F2 ;
- F2 compact : facteur passage avec peu de groupes (2–4 max) — PDF court, pas de pattern matrice `^O\d{7}` sur P1/P2.

**Non retenu tant que source vide** : `Comparer CR1 selon l’ordre de passage de la pastille` (question ambiguë ext/int sans pièce/opération).

---

## 19. Campagne validation LISI multi-cas (2026-06-03)

> **Statut F2 compact v1** : validé fonctionnellement sur données réelles `data/lisi_capteurs.csv` (activation `f2_compact_enabled` **en mémoire** pour les runs ; **non** activé par défaut dans le YAML).

### Cas testés

| ID | Question (résumé) | Pièce / op. | Facteur | Pattern matrice | Verdict compact | Statut |
|----|-------------------|-------------|---------|-----------------|-----------------|--------|
| **B** | CR50 intrados vrillage × four | RD4L1A1C / EQUATOR | `Numero Machine` | — | SURVEILLANCE | Validé |
| **C** | CR1 × presse | RD4L1A1C / FILAGE | `Numero Machine` | — | NO-GO | Validé |
| **D** | CR10 intrados forme × matrice | M2L1A1C / EQUATOR | `Ref_Matrice` | `^O\d{7}$` (test) | SURVEILLANCE (dégénéré) | **Non validé** (config) |
| **D bis** | Idem D | M2L1A1C / EQUATOR | `Ref_Matrice` | `^O\d{7}[A-Z0-9-]*$` | SURVEILLANCE | Validé |

PDF de référence (runs campagne, non versionnés) : `reports/f2_compact_B_cr50_four_RD4L1A1C_equator.pdf`, `f2_compact_C_cr1_presse_RD4L1A1C_filage.pdf`, `f2_compact_D_cr10_matrice_M2L1A1C_equator.pdf`, `f2_compact_D_cr10_matrice_M2L1A1C_equator_bis.pdf`.

### Pattern matrice LISI retenu

**Expression** : `^O\d{7}[A-Z0-9-]*$`

**Chemin YAML** (persisté) :

```yaml
entites.facteurs_analyse.EQUATOR.matrice.group_value_pattern
```

**Consommation S7** : `f2_compact_selection._resolve_group_pattern()` — le pattern facteur est lu **en premier** lorsque `group_by` correspond à `colonne` (`Ref_Matrice`).

| `group_value` | Résultat attendu |
|---------------|------------------|
| `O5220911B3-0` | Fiable (si n ≥ seuil) |
| `O5220911B2-0` | Fiable |
| `O5220911C1` | Fiable |
| `M748710` | Exclu — `pattern_yaml_non_respecte` (identifiant type machine, pas référence matrice O…) |

**Échec D initial** : le pattern `^O\d{7}$` (ancré fin de chaîne après 7 chiffres) **rejette** les suffixes réels (`B3-0`, `C1`, etc.) → 0 groupe fiable → rapport dégénéré. **Ce n’est pas une régression pipeline.**

**Variante rejetée** : `rapport_pdf.f2_compact.group_value_pattern` seul — équivalent fonctionnel si le facteur n’est pas renseigné, mais moins précis (s’appliquerait à tout run compact utilisant ce bloc YAML global).

### Groupes fiables / exclus (résumé campagne)

- **B** : 8 fiables / 3 exclus (P03, M2346B, M2348B — effectif &lt; 6).
- **C** : 2 fiables (M1994, M1567) / 2 exclus (M1503, M790).
- **D bis** : 3 fiables (O5220911B3-0, O5220911B2-0, O5220911C1) / 1 exclu (M748710).

### Anomalies hors pattern

- Warnings contrat A4 (verdict GO/NO-GO « premières sections », tableau Cpk global, reco) — **attendus** en mode F2 compact.
- Cas pastilles FILAGE : hors campagne (§18).

---

## 20. Validation documentaire (2026-06-03)

- [x] Spec alignée implémentation C1 → D4b  
- [x] Section v1 candidate §16  
- [x] Règles FILAGE / pastille documentées §18  
- [x] Campagne multi-cas documentée §19  
- [x] Pattern matrice LISI persisté (`entites…EQUATOR.matrice.group_value_pattern`)  
- [x] Limites et commits référencés  
- [ ] Activation produit `f2_compact_enabled: true` (décision séparée)  
- [ ] Export enrichi pastille (passage P1/P2 + retaille en colonnes ou Tag/Value)  
- [ ] Correction S4 `test_tendance_timeseries` (§17 option A)
