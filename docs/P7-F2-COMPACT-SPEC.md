# P7-F2 compact — Spec formelle (Phase B)

> **Statut** : SPEC — à valider avant implémentation Phase C  
> **Version** : 1.0 — 2026-06-02  
> **Remplace** : tunnel `narratif_metier` long (P7-F2a–c, gelé via `f2_narratif_enabled: false`)  
> **Référence métier** : rapport vrillage (4 p., dense, quali × quanti)  
> **Non-cible** : rapport portrait F1 (une variable, pas de facteur qualitatif)

---

## 0. Objet

Définir un PDF **F2 compact** pour l’intention S1 `comparaison_groupes` : comparer **une mesure quantitative** ventilée par **un facteur qualitatif** (matrice, machine, fournisseur…).

Objectifs :

- **4 à 6 pages** (pas 14).
- **Cohérence** : verdict, tableau et synthèse lisent la **même** source filtrée.
- **Densité métier** : inspiré du rapport vrillage, pas du portrait statistique.
- **Zéro LLM en S7** ; zéro chiffre inventé ; zéro règle métier hardcodée en Python.

---

## 1. Périmètre et déclenchement

| Élément | Règle |
|---------|--------|
| Intention S1 | `comparaison_groupes` (famille P6 **F2** `bivariate_quali_quanti`) |
| Donnée S3 requise | Bloc `group_descriptive` (niveau `aggregated_unit` si config active, sinon `measure` avec mention explicite) |
| Test global | Résultat `anova_kruskal` ou équivalent dans `specialist_results` |
| Graphique | 1 boxplot S4 par variable × `group_by` (plafond YAML) |
| Mode rendu | Nouveau plan **F2 compact** dans S7 — **distinct** de `narratif_metier` gelé et de l’audit simple v5c |
| Activation | `rapport_pdf.f2_compact_enabled: true` (défaut à définir en Phase C ; **false** tant que non implémenté) |

**Hors périmètre Phase C v1** : F3, F4, F5, diagnostic causal étendu, RAG, modification renderer (réutilisation block_types existants si possible).

---

## 2. Structure exacte du rapport compact

Ordre fixe des sections (11 blocs logiques ; regroupement renderer autorisé pour densité) :

| # | Section | Rôle | Source principale |
|---|---------|------|-------------------|
| 1 | **Cover** | Identité, question, date, profil | intent, ClientContext |
| 2 | **Synthèse métier** | Titre + 2 lignes : variable, nominal, tolérance, facteur | YAML tolérances + `group_descriptive` |
| 3 | **Conclusion clé** | 2–4 phrases : pire groupe, chiffre critique, contraste favorable **si fiable** | Lignes filtrées S3 uniquement |
| 4 | **Contexte de l’analyse** | Définition mesure, hors tolérance, **niveau d’analyse** (mesure / OF / lot…) | YAML + `group_descriptive.level` + `aggregation` |
| 5 | **Indicateurs clés** | Tableau 4 colonnes max : critique / % HT / Cpk min / favorable | Lignes filtrées |
| 6 | **Tableau groupes fiables** | Table principale (voir §4) | `group_descriptive.rows[]` filtré |
| 7 | **Lecture Cp/Cpk simple** | Encadré pédagogique court + phrase « dans ce cas » | Template Python + Cpk du pire groupe filtré |
| 8 | **Fiabilité statistique** | IC95 moyenne et % HT par groupe **présent dans le tableau** | `ci95_*` par row S3 |
| 9 | **Graphique** | Boxplot + légende une ligne | S4 |
| 10 | **Test statistique** | Kruskal/ANOVA + p-value ; Dunn en annexe courte si sig. | `specialist_results` |
| 11 | **Lecture métier** | **3 blocs max** : priorité / intermédiaires (synthèse) / favorable ou « à confirmer » | Templates sur rows filtrées |
| 12 | **Verdict métier** | **3 paragraphes** ; hiérarchie **≤ 5** groupes filtrés ; pas de liste 17 puces | Rows filtrées |
| 13 | **Limite d’interprétation** | Texte fixe association ≠ causalité | `group_descriptive.interpretation_limits` |
| 14 | **Traçabilité** | SHA-256, version, contrôle chiffres | A3 |

**Page cible** : 4–6 pages A4 avec tableau top-N (4–6 groupes), pas d’annexe Dunn longue en v1 client.

**Bandeau GO/NO-GO** (cover) : calculé **uniquement** depuis les indicateurs du **pire groupe filtré** (§6), pas depuis le Cpk global pooled ni la seule priorité S6.

---

## 3. Règles de sélection — groupes fiables

Un groupe entre dans l’ensemble **fiable** (`rows_reliable`) si **toutes** les conditions suivantes sont vraies :

1. **Effectif** : `n` ≥ seuil minimal du niveau d’analyse (YAML, voir §10).
2. **Warnings S3** : aucun warning d’effectif faible sur la row (`effectif_faible_*`, `n<… pour Cp/Cpk fiable` n’exclut pas du tableau si Cp/Cpk affichés N/A — voir §4).
3. **Validité métier** : `group_value` passe le filtre format / allowlist YAML pour la colonne `group_by` (§5).
4. **Classement** : conserver l’ordre S3 (`rank`) **parmi les fiables** ; ne pas recalculer le ranking en S7.

Si **aucun** groupe fiable : rapport **dégénéré** — message « Données insuffisantes pour comparer les groupes de façon fiable », tableau vide, verdict **SURVEILLANCE** ou **GO** avec limite explicite (pas de NO-GO sur des chiffres non fiables).

**Groupe prioritaire (pire)** : première row fiable par `rank` (severity `critique` ou pire rang).

**Groupe favorable** : dernière row fiable par `rank` **seulement si** `n` ≥ seuil favorable (YAML, ≥ seuil minimal) ; sinon section « référence à confirmer » **absente** du verdict principal.

---

## 4. Règles d’exclusion — effectif faible et valeurs parasites

### 4.1 Exclusion effectif

| Niveau S3 | Seuil YAML (clé proposée) | Défaut si absent |
|-----------|---------------------------|------------------|
| `measure` | `dataset.agregation_metier_f2.defaults.min_observations_per_unit` réutilisé comme `rapport_pdf.f2_compact.min_n_measure` | `group_descriptive` utilise déjà `MIN_N_GROUP=6` en warning — **aligner affichage sur warning S3** |
| `aggregated_unit` | `min_units_per_group` dans `aggregation` / YAML unité | Valeur du bloc `aggregation` S3 |

**Règle** : S7 **ne hardcode pas** `n < 6` ; il lit seuils depuis `group_descriptive.aggregation` ou `rapport_pdf.f2_compact.*` ou `dataset.agregation_metier_f2.defaults`.

Rows exclues → **annexe traçabilité interne** ou footnote « X groupes exclus (effectif insuffisant) » — **pas** dans le tableau principal.

### 4.2 Exclusion valeurs parasites

Valeurs typiques à exclure (LISI `Ref_Matrice`) : noms opérateurs, codes hors pattern matrice.

| Source | Mécanisme |
|--------|-----------|
| YAML | `entites.facteurs_analyse.<op>.<facteur>.group_value_pattern` (regex, ex. `^O\\d{7}`) |
| YAML | `group_value_denylist` optionnel (liste) |
| S3 | Si absent, warning S3 `invalid_group_value` (Phase ultérieure) — **Phase C v1** : filtre YAML côté S7 assembleur uniquement |

**Interdit dans tableau principal et verdict** : `PAIROYS ALAIN`, `LANDIER THOMAS`, `M664520` (n=1), tout groupe non conforme au pattern.

---

## 5. Format du tableau principal

**Titre** : « Comparaison des groupes » ou libellé métier du facteur (`friendly_group_label`).

**Colonnes** (ordre fixe) :

| Colonne | Champ S3 | Notes |
|---------|----------|-------|
| Groupe | `group_value` | Libellé métier |
| n | `n` | Unité = niveau d’analyse (mesures ou OF/lots) |
| Moyenne | `mean` | Unité mm ou YAML |
| Écart-type | `std` | |
| % hors tol. | `out_of_tolerance_rate` | Format % client |
| Cp | `cp` | `—` si null + footnote warning |
| Cpk | `cpk` | `—` si null |
| Rang | `rank` | Sur ensemble fiable ré-étiqueté 1..k ou rang S3 d’origine |
| Niveau | `severity_display` | Critique / Surveillance / Favorable — **recalculé sur fiables only** |

**Lignes** : max `rapport_pdf.f2_compact.max_table_rows` (défaut **6**, comme vrillage top matrices).

**Légende sous tableau** (2 lignes max) :

- Code couleur : critique / intermédiaire / favorable (seuils couleur depuis `rapport_pdf.cpk_couleurs`).
- Rappel : « Cp/Cpk calculés au niveau {label niveau} ».

**Interdit** : 18 lignes dont 10 à n≤3 ; colonnes Cp/Cpk vides sans explication.

---

## 6. Synthèse métier attendue

**Bloc 2 — Synthèse métier** (en-tête, style vrillage p.1) :

```text
Synthèse métier — Influence de {facteur} sur {variable_libelle}
Variable analysée : {tag}   Nominal : {nominal}   Tolérance : [{lti} ; {lts}] {unité}
```

**Bloc 3 — Conclusion clé** (2–4 phrases, ≤ 120 mots) :

1. **Constat** : groupe le plus critique + % HT **ou** moyenne proche limite + Cpk si disponible.
2. **Contraste** : meilleur groupe fiable **uniquement si** seuil favorable atteint ; sinon phrase « aucun groupe de référence fiable identifié ».
3. **Prudence** : une phrase si niveau `measure` vs référence OF agrégée.

**Interdit** (leçons F2c raté) :

- NO-GO bandeau alors que pire groupe filtré montre 0,4 % HT et Cpk > 1,3.
- Cpk « favorable » sur le groupe prioritaire.
- Comparer pire groupe à M664520 n=1.
- Phrase du type « Groupe à surveiller … rang N » en boucle.

---

## 7. Lecture Cp/Cpk simple

**Contenu fixe** (template, adapté vrillage §4 ref.) :

1. Définition Cp (dispersion) et Cpk (dispersion + centrage) — **≤ 80 mots**.
2. Grille seuils : lire `rapport_pdf.cpk_couleurs` ou `recommandations.seuils_cpk` — **pas de seuils en dur dans le template**.
3. Phrase contextualisée : « Dans cette analyse, {pire_groupe} affiche un Cpk de {cpk} ; {interprétation_seuil}. »

**Interdit** : paragraphe « Comment lire le Cpk » de ½ page + redite des seuils déjà dans l’indicateur clé.

---

## 8. Fiabilité statistique

**Tableau** : uniquement groupes du tableau principal (fiables).

| Colonne | Source |
|---------|--------|
| Groupe | `group_value` |
| n | `n` |
| IC 95 % moyenne | `ci95_mean.label` |
| IC 95 % hors tol. | `ci95_out_of_tolerance_rate.label` |

**Paragraphe de synthèse** (2–3 phrases) :

- Confirme ou nuance le classement du pire groupe.
- Mentionne prudence si favorable a un n plus faible que les autres (sans le promouvoir en verdict).

**Source** : champs `ci95_*` déjà calculés en S3 — S7 ne recalcule pas.

---

## 9. Verdict métier

**Structure** :

- Titre : « Verdict métier »
- **3 paragraphes** (priorité / surveillance / référence ou absence de référence fiable)
- Hiérarchie optionnelle : **≤ 5** lignes `rank. groupe (niveau)` — groupes fiables uniquement

**Règles verdict** :

| Condition (pire groupe filtré) | Bandeau |
|--------------------------------|---------|
| `out_of_tolerance_rate` > seuil P1 YAML **ou** Cpk < `recommandations.seuils_cpk.p1_sous` | NO-GO |
| Surveillance (seuils intermédiaires YAML) | SURVEILLANCE |
| Sinon | GO |

Seuils : **YAML** `recommandations.seuils_cpk`, `rapport_pdf.verdict_*` — jamais `1.33` hardcodé en S7.

**Interdit** :

- Groupe faible ou parasite dans le verdict.
- n=1 comme « référence favorable ».
- Liste de 17 puces.
- Verdict basé sur `cp_cpk` global pooled ou priorité S6 seule.

---

## 10. Limite d’interprétation

**Texte principal** : reprendre `group_descriptive.interpretation_limits` (S3).

**Complément fixe** (template) :

- Niveau d’analyse (mesure vs unité agrégée).
- « Cette analyse met en évidence une association entre {facteur} et {variable} ; elle ne permet pas à elle seule d’affirmer une causalité directe certaine. » (PHILOSOPHY §28)

**Quality gate** : réutiliser `_apply_f2_narratif_gate` / `text_contains_abusive_causality` sur les blocs texte F2 compact.

---

## 11. Provenance des données

### 11.1 S3 / P6 (obligatoire)

| Donnée | Origine |
|--------|---------|
| Rows groupes, ranks, severity | `group_descriptive.rows[]` |
| % HT, moyennes, Cp/Cpk | idem |
| IC95 | `ci95_mean`, `ci95_out_of_tolerance_rate` |
| Niveau, aggregation | `level`, `aggregation`, `warnings` |
| Limites | `interpretation_limits` |
| Test global | `anova_kruskal` / `dunn_posthoc` dans `specialist_results` |
| p-value affichée | `format_p_value` certifié |

### 11.2 YAML / ClientContext

| Donnée | Origine |
|--------|---------|
| Tolérances LTI/LTS, nominal, unité | `pieces.*.operations.*.tags.*` |
| Libellés facteur | `entites.facteurs_analyse`, `colonnes_libelles` |
| Seuils Cpk / verdict | `recommandations.seuils_cpk`, `rapport_pdf.cpk_couleurs`, `verdict_bandeaux` |
| Seuils effectif F2 | `dataset.agregation_metier_f2`, `rapport_pdf.f2_compact.*` |
| Filtre group_value | `entites.facteurs_analyse.*.group_value_pattern` (à ajouter Phase C) |
| Plafonds | `max_table_rows`, `max_graphiques_*` |

### 11.3 S5 / S6 (optionnel, limité)

- **S7 Phase C v1** : **aucune** dépendance LLM pour le corps F2 compact.
- S6 plan d’action : **omis** ou 1 action P1 max si NO-GO certifié — pas de plan générique 4 lignes.

---

## 12. Interdictions explicites

1. Narratif long P7-F2a–c (`business_reading` × N, `how_to_read_cpk` long, 15 blocs).
2. Boucle « un paragraphe par groupe intermédiaire ».
3. Causalité abusive (PHILOSOPHY §28).
4. Chiffre absent de S3 / YAML.
5. Règle métier hardcodée (seuils n, regex LISI en Python).
6. Groupe n=1 ou parasite en tête de tableau ou verdict.
7. Double source de vérité verdict (S6 P1 vs group_descriptive).
8. Renderer custom Phase C v1 — assembler produit des blocs ; renderer existant étendu minimalement **après** validation spec + JSON blocs.
9. Réactivation `narratif_metier` par défaut.

---

## 13. Anti-patterns — PDF F2c raté (à ne plus reproduire)

| Observation F2c | Cause | Spec compact |
|-----------------|-------|--------------|
| 14 pages | Trop de blocs + 18 lignes tableau | Max 6 lignes, 11 sections denses |
| NO-GO + 0,4 % HT | Verdict S6 / Cpk global | Verdict = pire groupe **filtré** |
| Cpk 1,47 « favorable » sur critique | Template incohérent | Cpk lu avec seuils YAML + cohérence rang |
| M664520 n=1 favorable | Pas de filtre | Exclusion + pas de référence favorable |
| PAIROYS ALAIN en groupe | Pas de pattern Ref_Matrice | Filtre YAML |
| 16× « Groupe à surveiller » | Boucle template | 3 blocs lecture max |
| % mesure vs % OF ref. | Niveau measure sans mention | Contexte explicite + agrégation YAML quand dispo |

---

## 14. Critères d’acceptation Phase C

1. Run LISI RD4 vrillage × matrice : PDF **≤ 6 pages**, tableau **≤ 6 groupes fiables**, 0 parasite visible.
2. Verdict cohérent avec pire groupe filtré (bandeau + conclusion clé).
3. Aucun chiffre du PDF absent de S3/YAML (test provenance).
4. Quality gate causalité vert.
5. `f2_narratif_enabled` reste `false` ; F2 compact activé par flag dédié.
6. Tests S7 : assembler F2 compact + non-régression audit simple.

---

## 15. Validation requise

- [ ] Ahmed valide structure §2 et règles filtrage §3–5  
- [ ] Pattern `Ref_Matrice` LISI défini en YAML  
- [ ] Seuils verdict F2 alignés vrillage (% HT OF vs mesure) documentés par client  
- [ ] Go Phase C implémentation (S7 assembler only, pas S3/renderer v1)
