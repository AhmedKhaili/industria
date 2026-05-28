# S3 étendu — Portrait statistique, normalité, ajustement de loi

> **Statut** : **VALIDÉ v1.1** (GO D0 — 2026-05-27)  
> **D1** : annexe A intégrée → `docs/PHILOSOPHY.md` §28  
> **P0** : `correlation` branché sous `analyse_complete` ✅  
> **P1** : `descriptive`, `normality`, `distribution_fit` + `portrait_statistique` ✅  
> **P2** : intentions S1 (`portrait_statistique`, `diagnostic_causal`, `analyse_complete`) ✅

**Documents liés** : `docs/VISION.md`, `docs/PHILOSOPHY.md` (§28), `docs/S3.md`, `docs/S5.md`, `docs/S7.md`.

---

## 0. Périmètre client LISI (opérations réelles)

### Opérations actives

Dans `configs/lisi_aerospace/client_config.yaml` :

```yaml
operations_actives: ["FILAGE", "EQUATOR"]
```

**Il n’existe pas d’opération `FORMage` dans la config actuelle.**

Toute question utilisateur mentionnant « formage » doit être interprétée ainsi :

| Formulation utilisateur | Résolution S1 attendue (spec) |
|-------------------------|-------------------------------|
| « formage », « profil », « intrados », « veine au contrôle » | **EQUATOR** + groupe variable `forme` ou `veine` selon tags |
| « filage », « corde », « pastille », « presse » | **FILAGE** + groupe variable adapté |

**Exemple corrigé** (au lieu de « FORMAGE ») :

- « Analyse complète de la **veine** sur **M2L1A1C** à **EQUATOR** »  
  → `operation: EQUATOR`, variables matching `VEINE_SCAN_*`, intention `analyse_complete`.

### Si un jour `FORMage` devient une opération distincte

**Aucun code dans cette phase.** Prérequis documentés uniquement :

| Composant | Changement requis |
|-----------|-------------------|
| **YAML S0** | Ajouter `FORMage` dans `operations_actives`, `entites.facteurs_analyse.FORMage`, `groupes_variables.FORMage`, tolérances `pieces.*.operations.FORMage` |
| **S2** | Règles de filtre pièce/opération ; colonnes temps et tags dédiés |
| **S1** | Synonymes « formage » → résolution explicite vs EQUATOR |
| **S3/S4** | Aucun changement de contrat spécialiste si `df_propre` reste homogène |

---

## 1. Cohérence PHILOSOPHY

| Règle | Application S3 étendu |
|-------|------------------------|
| §1 — LLM ne calcule pas | Tous les chiffres et verdicts (`normale` / `non_normale`, `loi_retenue`) sortent de `specialists/*.py` |
| §10 — Agents calcul Python pur | `descriptive`, `normality`, `distribution_fit` suivent `BaseSpecialist` |
| §5 — LLM rédige seulement | S5 R1 interprète ; R2 vérifie les nouveaux champs numériques |
| PHILOSOPHY §28 — Langage client | Jamais « causent » ; η² = **variance expliquée**, pas causalité prouvée |

**Pas de contradiction** avec S7 (PDF sans LLM) ni avec le pipeline v4 actuel.

---

## 2. Nouvelles intentions S1

À ajouter dans `entites.intentions` (YAML) **et** dans `systems/s1/agent_4_intent_builder.py` (résolution + synonymes).

### 2.1 `portrait_statistique`

**Questions types**

- « Analyse-moi CR90_INTRADOS_FORME sur M2L1A1C »
- « Donne-moi le portrait statistique de cette mesure »
- « Cette mesure suit-elle une loi normale ? » (sous-intention : inclure `normality` + `distribution_fit`)

**Dispatcher S3** (liste ordonnée) :

```text
descriptive → normality → distribution_fit
```

**Optionnel si LTI/LTS** : ajouter `cp_cpk` lorsque tolérances YAML disponibles (même pré-gate S3 actuel).

**S4** (phase ultérieure P4 PDF) : histogramme + QQ-plot (spec S4 à compléter lors de l’implémentation).

---

### 2.2 `diagnostic_causal`

**Questions types**

- « Quels facteurs **influencent** les problèmes de veine ? » (jamais « causent » en sortie)
- « Quel facteur explique le plus la variabilité sur CR90 ? »

**Dispatcher S3** (phase 1 — **sans** `eta_squared` tant que P5 non validé) :

```text
anova_kruskal → cp_cpk (si variables + tolérances)
→ dunn_posthoc (auto si ANOVA/Kruskal significatif — règle existante)
```

**Phase 2 (P5)** : ajouter `eta_squared` en tête de liste si `group_by` ou facteurs YAML résolus.

**Prérequis intent**

- `group_by` non vide (ex. `Ref_Matrice` sur EQUATOR, `PAS_E_Fournisseur` sur FILAGE), **ou**
- `facteurs_analyse[]` explicite (extension intent — à spécifier en P2 S1).

---

### 2.3 `analyse_complete`

**Questions types**

- « Analyse complète de la veine sur M2L1A1C à EQUATOR »
- « Bilan qualité complet sur les 5 sections intrados »

**Dispatcher S3** (union contrôlée par plafonds YAML §5) :

```text
descriptive → normality → distribution_fit (P1 — portrait en tête)
→ correlation (P0 — pas d'intention dédiée)
→ cp_cpk (P2+)
→ zscore : NON par défaut (uniquement si plafond YAML ou intent explicite)
→ anova_kruskal (+ dunn si significatif) si group_by présent
```

**État code P1** : `analyse_complete` → portrait + `correlation` ; `portrait_statistique` → portrait seul.

**Variables** : résolues par S1 (`groupes_variables.veine`, `forme`, ou liste explicite) — **pas** toutes les colonnes numériques du CSV.

**Rapport S7** : `rapport_type: complet` (§6).

---

### 2.4 Matrice intentions × opérations LISI

| Intention | FILAGE | EQUATOR |
|-----------|--------|---------|
| `portrait_statistique` | corde, EP_*, pastille (si mesures numériques) | forme, veine, vrillage, desaxage |
| `diagnostic_causal` | fournisseur, retaille, passage, machine | matrice, machine |
| `analyse_complete` | groupe choisi + facteurs FILAGE | groupe choisi + matrice |

---

## 3. Nouveaux spécialistes — niveau 1 (spec détaillée)

### 3.1 Orchestration S3 (`systems/s3/executor.py`)

**Familles d’exécution** (extension du modèle actuel) :

| Famille | Agents | Comportement |
|---------|--------|--------------|
| `single_target` | `anova_kruskal` | 1× sur 1ʳᵉ colonne cible (inchangé) |
| `multi_target` | `cp_cpk`, `zscore`, `spc`, `mann_kendall`, … | 1× par variable intent (inchangé) |
| **`portrait`** | `descriptive`, `normality`, `distribution_fit` | 1× par variable intent |
| **`correlation`** | `correlation` | 1× par variable intent ; intention **`analyse_complete`** uniquement (P0 branché) |

Enregistrement : `_SPECIALIST_CLASSES` + `INTENTION_SPECIALISTS["analyse_complete"]`.

---

### 3.2 `specialists/descriptive.py`

**Entrée** : `df_propre`, `target_column`, tolérances via `ClientContext` (LTI/LTS/nominal comme `cp_cpk`).

**Calculs** (Python / scipy.stats ou numpy) :

| Champ `result` | Description |
|----------------|-------------|
| `colonne` | Variable analysée |
| `n` | Effectif non nul |
| `moyenne`, `mediane` | Tendance centrale |
| `ecart_type`, `variance` | Dispersion |
| `skewness`, `kurtosis` | Forme (scipy.stats.skew / kurtosis) |
| `min`, `max`, `q1`, `q3`, `iqr` | Extrêmes et quartiles |
| `pct_hors_lt_lts` | % hors [LTI, LTS] si tolérances présentes, sinon `null` |
| `centrage` | `(moyenne - nominal) / (LTS - LTI)` si nominal + LTI/LTS valides |
| `lti`, `lts`, `nominal` | Rappel seuils (traçabilité) |
| `interpretation_dispersion` | Phrase Python courte (template, pas LLM) |

**Pre-gates**

- `n < 5` → `skipped`
- Colonne non numérique → `error`

**Verdict** : pas de verdict binaire unique ; tableau descriptif complet.

---

### 3.3 `specialists/normality.py`

**Tests** (choix **Python** selon effectif) :

| Condition | Rôle | Champs `result` |
|-----------|------|-----------------|
| `n < 5000` | **Shapiro-Wilk** — test principal pour le verdict | `shapiro_stat`, `shapiro_p` |
| `n ≥ 5000` | **Anderson-Darling** — test principal pour le verdict | `ad_stat`, `ad_critical`, `ad_significatif` |
| `n ≥ 5000` | Kolmogorov-Smirnov — **indicatif seulement** | `ks_stat`, `ks_p`, `ks_note` |

**Règle KS (importante)** : le KS contre une normale avec **moyenne et écart-type estimés sur les données** n’est pas un test Lilliefors complet dans cette phase. Il est stocké à titre **indicatif** ; le verdict `verdict_normalite` ne s’appuie **pas** seul sur le KS. Pour `n ≥ 5000`, le verdict repose sur **Anderson-Darling** (et Shapiro reste disponible en complément si `n < 5000`).

**Verdict Python** (jamais LLM) :

```text
verdict_normalite: "normale" | "non_normale"
alpha: 0.05
regle_verdict: texte court (ex. "Anderson-Darling non significatif" ou "Shapiro p >= 0.05")
test_verdict_source: "shapiro" | "anderson_darling"
```

**Si `non_normale`** : champ `loi_candidate_aic` (pas « distribution probable ») :

- Si `distribution_fit` exécuté dans la même passe → recopier `loi_retenue` + `aic_min` depuis son `result`
- Sinon → `null` et phrase Python : « ajustement de loi non calculé sur cette passe »

**Interdit côté client** : « la distribution est probablement Weibull » → utiliser « **meilleur ajustement** parmi les lois testées : Weibull (AIC = …) ».

**Pre-gates**

- `n < 8` → `skipped` (tests non fiables)
- Constante sur la série → `skipped`

**Libellé certifié S5** (comme p-value) :

```text
normalite_phrase: "compatible avec une loi normale (test …, p = …)"
ou "écart significatif à la normale (test …, p = …)"
```

---

### 3.4 `specialists/distribution_fit.py`

**Lois candidatas** (ajustement scipy, MLE ou méthode documentée dans le code) :

1. Normale  
2. Log-normale  
3. Weibull  
4. Exponentielle  
5. Uniforme  

**Pour chaque loi** :

| Champ | Description |
|-------|-------------|
| `loi` | Identifiant interne |
| `aic`, `bic` | Scores |
| `parametres` | dict des paramètres estimés |
| `ajustement_ok` | bool (ex. log-normale si valeurs ≤ 0 → false) |

**Décision Python** :

```text
loi_retenue = argmin(aic) parmi lois avec ajustement_ok == true
classement: liste triée par AIC croissant
```

**Champs obligatoires** :

```text
loi_retenue: str
aic_min: float
bic_min: float
classement: [{loi, aic, bic, ajustement_ok}, ...]
interpretation_loi: phrase Python (ex. "Meilleur ajustement parmi les lois testées : Weibull (AIC = …)")
libelle_client: jamais "loi probable" — toujours "meilleur ajustement selon AIC/BIC"
```

**Pre-gates**

- `n < 50` → `skipped` (fits instables — **décision §12.1**)
- >50 % valeurs identiques → `skipped` + warning

**Règle PHILOSOPHY** : le LLM **cite** `loi_retenue` et les AIC du `result` ; il ne choisit pas la loi.

---

## 4. Extension S5 — R2 et prompts

### 4.1 Champs ajoutés à la vérification R2 (`flatten_numbers` / références)

| Spécialiste | Nombres de référence |
|-------------|---------------------|
| `descriptive` | moyenne, médiane, ecart_type, variance, skewness, kurtosis, min, max, q1, q3, iqr, pct_hors_lt_lts, centrage |
| `normality` | shapiro_p, ks_p, ad_stat, seuils alpha |
| `distribution_fit` | aic/bic par loi, **pas** le rang — libellé `loi_retenue` qualitatif |

**η², R²** : réservés phase P5 (`eta_squared`, régression) — hors R2 phase 1.

### 4.2 Fallback Python (`python_fallback_interpretation`)

Obligatoire pour chaque nouveau spécialiste avant merge (même pattern que `enriched_anova_interpretation`).

### 4.3 Corpus R6 / synthèse

| Mode | Règle |
|------|--------|
| `mode_synthese: llm` | Comportement actuel |
| Multi-variables S5 | Si `variables > seuil` : warning durée uniquement ; R1 LLM par spécialiste inchangé ; `zero_llm_synthese` = opt-in YAML |

### 4.4 Consignes langage (R1 / R6 / R7)

- Interdit : **« causent »**, « cause racine prouvée », « responsable de » (sauf plan d’action S6 formulé comme hypothèse d’action).
- Obligatoire pour association : **« influencent »**, **« expliquent X % de la variance »**, **« associé à »**.
- Voir **PHILOSOPHY §28** (langage association / variance).

---

## 5. Plafonds YAML (`client_config.yaml`)

Section proposée (à valider) :

```yaml
analyse_etendue:
  portrait_statistique:
    max_variables: 3
    max_specialistes_par_variable: 3   # descriptive, normality, distribution_fit
  analyse_complete:
    max_variables: 5
    max_specialistes_total: 8          # toutes exécutions S3 confondues (hors dunn auto)
    max_specialistes_par_variable: 3
    inclure_cp_cpk: true
    inclure_comparaison_groupes: true  # si group_by résolu
  synthese_s5:
    avertissement_si_variables_gt: 3
    zero_llm_synthese: false            # opt-in explicite — jamais auto
  rapport:
    type_simple: "client_quality"        # actuel v5c
    type_complet: "client_quality_complet"
```

**Executor S3** : avant boucle, compter `len(targets) × len(specialists)` ; si dépassement → tronquer variables (ordre : intent explicite, puis pire Cpk si dispo) + `warnings[]`.

---

## 6. Layout PDF S7

### 6.1 Mode `simple` (inchangé)

Correspond au rapport actuel **client_quality** (`rapport_lisi_v5c.pdf`) :

- Verdict + 3 puces  
- Résumé exécutif court  
- Plan d’action  
- ≤3 boxplots  
- Tableau Cpk coloré  
- Interprétations regroupées  
- Traçabilité SHA-256  

**Intentions** : `conformite`, `comparaison_groupes`, `tendance`, `anomalie` (existant).

---

### 6.2 Mode `complet` (`analyse_complete` / `portrait_statistique` étendu)

Déclenché par : `intent.rapport_type == "complet"` **ou** intention `analyse_complete` (règle A1 Python).

| Ordre | Section | Contenu |
|-------|---------|---------|
| 1 | **Verdict** | Bandeau GO/NO-GO + puces (inchangé) |
| 2 | **Portrait statistique** | Table descriptive synthétique (1 tableau multi-lignes ou 1 variable détaillée) |
| 3 | **Normalité & distribution** | Verdict `normale`/`non_normale` + `loi_retenue` + AIC (table, pas prose LLM brute) |
| 4 | **Capabilité** | Cpk coloré (existant) |
| 5 | **Facteurs influents** | Seulement si `diagnostic_causal` ou `analyse_complete` + ANOVA/Dunn ; libellé **η² reporté en P5** |
| 6 | **Graphiques** | Histogrammes / boxplots selon intention (plafond YAML) |
| 7 | **Plan d’action** | S6 (inchangé) |
| 8 | **Annexe** | Dunn, métriques brutes, traçabilité |

**Regroupement A1** : familles `portrait` / `conformite` / `comparaison` — pas 1 bloc par agent technique.

---

## 7. Dépendances Python (par phase produit)

| Phase | Libs | Contenu |
|-------|------|---------|
| **Niveau 1** | `scipy`, `numpy`, `pandas` (déjà dans `requirements.txt`) | descriptive, normality, distribution_fit |
| **Niveau 2** | + `statsmodels` | η², ANOVA II, régression (P5+) |
| **Niveau 3** | + `ruptures` | change-point (futur) |
| **Niveau 4** | + `scikit-learn` | clustering / régression avancée (futur) |

**Phase 1 implémentation** : **aucune** nouvelle dépendance.

---

## 8. Graphiques S4 (spec minimale — implémentation P4)

| Intention / spécialiste | Type chart (à ajouter) |
|-------------------------|-------------------------|
| `portrait_statistique` | `histogram` (existe) |
| `normality` | `qqplot` — **reportable P4** ; profil `ingenieur` uniquement, pas PDF client |
| `distribution_fit` | `histogram` + courbe loi ajustée (nouveau, optionnel P4) |

---

## 9. Ordre d’implémentation validé

### Phase documentaire

| Étape | Statut |
|-------|--------|
| **D0** | ✅ Validé (réponses §12 ci-dessous) |
| **D1** | ✅ `PHILOSOPHY.md` §28 |

### Phases code

| Phase | Livrable spec | Statut |
|-------|---------------|--------|
| **P0** | `correlation` sous `analyse_complete` — dispatcher + executor + test LISI | ✅ **Validé** — ne pas lancer P1 sans relecture |
| **P1** | `descriptive`, `normality`, `distribution_fit` + tests unitaires | ✅ Validé |
| **P2** | S1 : intentions YAML + `agent_4` + tests S1 | PR dédié |
| **P3** | S5 : R2 refs, fallbacks, `normalite_phrase`, `loi_candidate_aic`, mode `agregee_python` | ✅ Validé |
| **P4** | S7 : `rapport_type complet`, sections A1/renderer | PR dédié |
| **P5** | `eta_squared` + PDF « Facteurs influents » | **Nouvelle validation** doc v2 |

**Interdit avant validation D0** : tout code dans `specialists/` ou `systems/s3/`.  
**Interdit en P1** : mélanger P0 correlation + trois nouveaux spécialistes dans le même PR.

---

## 10. Hors phase 1 — réservé (ne pas coder)

Documentés pour traçabilité, **sans spec détaillée** dans cette version :

- `eta_squared`, `anova_two_way`, `regression_multivariee`
- `change_point`, `seasonality`
- `benchmarking`, `similarity`

Spec dédiée ou amendement `S3-extended` v2 après retour terrain sur P1–P4.

---

## 11. Tests d’acceptation (definition of done)

### Spécialistes (P1)

- [ ] LISI EQUATOR : `descriptive` sur `CR90_INTRADOS_FORME` — tous champs présents, `n` cohérent S2  
- [ ] `normality` : `verdict_normalite` cohérent avec Shapiro (`n < 5000`) ou Anderson-Darling (`n ≥ 5000`) ; KS jamais seul décideur
- [ ] Texte client : pas de « loi probable » ; formulation « meilleur ajustement selon AIC »  
- [ ] `distribution_fit` : `loi_retenue == argmin(aic)` vérifiable en test unitaire  
- [ ] Aucun champ `loi_retenue` vide si `status == success`

### S1 (P2)

- [ ] « Analyse complète veine M2L1A1C EQUATOR » → `analyse_complete`, variables `VEINE_SCAN_*`, pas `FORMage`  
- [ ] « Quels facteurs influencent… » → `diagnostic_causal`, pas le mot « causent » dans intent

### S5 (P3)

- [ ] R2 Reject si LLM invente une moyenne hors tolérance 5 %  
- [ ] Fallback Python sans appel LLM si timeout

### S7 (P4)

- [ ] PDF `complet` ≤ plafond pages YAML (ex. 12 pages)  
- [ ] Section normalité affiche `loi_retenue` depuis Python, pas texte libre LLM seul

---

## 12. Décisions validées (GO D0)

| # | Décision |
|---|----------|
| 1 | `n_min` **distribution_fit** = **50** |
| 2 | **zscore** dans `analyse_complete` = **non par défaut** |
| 3 | **correlation** = sous-ensemble **`analyse_complete` uniquement** — pas d'intention dédiée |
| 4 | **QQ-plot** = reportable P4 ; profil **`ingenieur`** seulement |
| 5 | **> 3 variables** = warning S5 durée ; **pas** de mode agregee auto ; `zero_llm_synthese` opt-in |
| 6 | **`ks_note`** = log technique uniquement — **pas** en PDF client |

---

## 13. Résumé pour relecture rapide

| Aujourd’hui S3 | Après phase 1 validée |
|----------------|------------------------|
| Y a-t-il un problème ? (Cpk, groupes, tendance) | + **Comment** est distribuée la mesure (descriptive, normalité, loi) |
| 4 intentions | +3 intentions (`portrait_statistique`, `diagnostic_causal`, `analyse_complete`) |
| scipy seul | scipy seul (inchangé) |
| PDF simple | PDF **simple** + PDF **complet** |

**Prochaine étape** : **P3** — fallbacks S5 étendus, `agregee_python`, R2.
