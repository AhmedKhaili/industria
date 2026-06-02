# P7 — Rapport métier premium

> **Statut** : **P7-F2 narratif gelé** (2026-06-02) — `rapport_pdf.f2_narratif_enabled: false` par défaut.  
> Le tunnel `render_mode: narratif_metier` (9+ blocs longs) reste en code dormant pour tests expérimentaux uniquement.  
> **Prochaine cible validée** : **F2 compact façon vrillage** — spec formelle : [`P7-F2-COMPACT-SPEC.md`](P7-F2-COMPACT-SPEC.md) (Phase B ; implémentation Phase C après validation).  
> **Version doc** : 1.1 — 2026-06-02  
> **Dépend de** : `docs/P6-CARTOGRAPHIE-ANALYTIQUE.md` (sorties structurées par famille)  
> **Prérequis** : `docs/PHILOSOPHY.md`, `docs/S7.md`, layout P4 existant (`systems/s7/`)  
> **Ne pas confondre** : **P5** = extensions statistiques (η²) — voir `docs/S3-extended.md`

---

## 1. Objectif du chantier P7

Transformer les analyses certifiées (S3–S6, familles P6) en **livrable PDF lisible par un responsable qualité ou un directeur d’atelier**, au niveau du **rapport vrillage de référence** : conclusion immédiate, contexte, pédagogie, hiérarchisation, actions atelier, limites d’interprétation — **en conservant** les forces IndustrIA (graphiques, SHA-256, quality gate, annexes Dunn).

**Hors périmètre P7** : nouveaux calculs statistiques (→ P6/P5), monitoring S8, TimescaleDB.

**Succès P7** : un lecteur non-statisticien comprend en **2 minutes** le problème, la gravité, où agir, et ce que l’analyse ne prouve pas — sans jargon non filtré ni placeholders.

---

## 2. Problème actuel des rapports IndustrIA

| Force actuelle | Limite perçue |
|----------------|---------------|
| Bandeau GO/NO-GO, traçabilité SHA-256 | Ouverture **technique**, pas **narrative** (conclusion clé absente) |
| Tableau portrait 20 indicateurs | Peu d’encadrés « Comment lire… » |
| Graphiques histo / box / QQ | Légendes + fallback `key = value` sous les graphiques |
| Plan d’action S6 | Formulations génériques (« investiguer », « causes racines ») |
| Layout complet P4 / simple v5c | Deux ordres non unifiés ; `diagnostic_causal` parfois en layout simple par erreur de question |
| Profils YAML | Filtrage mots interdits, pas **structure** PDF différente |

**Référence** : rapport vrillage (~4 p.) — synthèse métier, tableau matrices commenté, grille Cpk, IC95, lecture par niveau (critique / intermédiaire / favorable), § limites causalité.

---

## 3. Principes non négociables

1. **S7 zéro LLM** : assemblage et mise en page 100 % Python (`a1_assembler`, `renderer_stub`, `report_port`).
2. **Contenu métier** : blocs alimentés par **templates Python certifiés** (priorité) + reformulation S5 **courte** optionnelle (fidélité R2).
3. **PHILOSOPHY §28** : pas de causalité abusive ; bloc **limites** obligatoire en mode narratif.
4. **Un moteur `ReportDocument`**, pas trois pipelines PDF.
5. **Deux ordres de rendu** (voir §5), sélection par config ou `intent.rapport_mode`.
6. **Profils = visibilité des sections**, pas duplication de code renderer.
7. **Réutiliser P4** : ne pas jeter `portrait_statistique`, `facteurs_influents`, `GRAPHIQUES`, quality gate client.

---

## 4. Bibliothèque de blocs `ReportDocument`

Extension des `block_type` S7 (`systems/s7/document.py`).

| `block_type` | Source données | Rôle |
|--------------|----------------|------|
| `cover` | intent, ClientContext, meta | Identité, question, date, profil |
| `conclusion_key` | P6 summary + S3 verdicts | **3–5 phrases** : problème, gravité, priorité |
| `business_context` | intent, YAML tolérances, P6 | Nominal, LTI/LTS, définitions (OF, hors tol) |
| `verdict` | portrait_verdict / S6 priorité | Bandeau GO/NO-GO + puces (existant, enrichi) |
| `key_indicators` | P6 `summary`, S3 | Tableau synthèse (3–6 lignes max) |
| `simple_explanation` | templates Python | Encadrés « Comment lire le Cpk ? », QQ-plot, etc. |
| `portrait_statistique` | build_portrait_variables | Tableau détaillé (existant P4) |
| `metrics_table` | S3/S4 tables | Cpk, ANOVA, Dunn (existant) |
| `facteurs_influents` | group_ranking, η² P5 | Facteurs / matrices (existant) |
| `visual_reading` | S4 + légendes | Titre section preuves + intro une phrase |
| `charts` | S4 png + interp | Graphiques + texte sous graphique (existant) |
| `business_reading` | templates + S5 | Paragraphes critique / surveillance / favorable |
| `action_plan_detailed` | S6 recommandations | Tableau P1–P4 **verbes d’atelier** |
| `final_verdict` | Python | Reformulation hiérarchie avant traçabilité |
| `interpretation_limits` | template fixe + P6 | Association ≠ causalité ; prudence effectifs |
| `executive` | S5 + S6 synthèses | Mode simple / audit (existant) |
| `interpretations` | S5 par spécialiste | Mode audit (existant) |
| `annexe_dunn` | S3 dunn_posthoc | Existant |
| `traceability` | A3 signer | SHA-256, fidélité, version |

**Règle** : chaque bloc a un schéma `data` documenté ; `None` / vide → bloc **omis**, jamais « N/A » dans le corps (PHILOSOPHY §8).

---

## 5. Deux modes de rendu

> **Note** : §5.1 narratif_metier est **gelé** tant que `rapport_pdf.f2_narratif_enabled` est `false` (défaut produit). Voir §5.4 pour la cible F2 compact.

### 5.1 `render_mode: narratif_metier` (expérimental — gelé)

Ordre des sections :

```text
1. cover
2. conclusion_key
3. business_context
4. key_indicators
5. simple_explanation (encadrés pédagogiques regroupés ou intercalés)
6. visual_reading + charts (+ metrics_table si comparaison groupes)
7. portrait_statistique (si F1 présent)
8. business_reading
9. action_plan_detailed
10. final_verdict
11. interpretation_limits
12. annexe_dunn (si applicable, profil ingénieur+)
13. traceability
```

**Public** : technicien, responsable qualité, atelier.

### 5.2 `render_mode: audit_en9100` (existant P4 / S7 spec)

Ordre conservé pour traçabilité formelle :

```text
1. cover
2. verdict
3. executive (résumé S5/S6)
4. action_plan / recommendations
5. charts (preuves visuelles)
6. metrics_table + portrait_statistique + interpretations
7. annexe_dunn
8. traceability
```

**Public** : audit, archivage, directeur (version courte possible).

### 5.3 Sélection du mode

| Critère | Mode |
|---------|------|
| `intent.rapport_mode` explicite | prioritaire |
| `rapport_pdf.default_mode` dans YAML | défaut client |
| `intention` ∈ {portrait, analyse_complete, diagnostic_causal} + profil technicien | `narratif_metier` **si** `f2_narratif_enabled: true` |
| Demande audit / directeur | `audit_en9100` |
| `comparaison_groupes` + `rapport_mode: narratif_metier` | **audit** si `f2_narratif_enabled: false` (défaut) |

**Implémentation** : `prep.resolve_render_mode(intent, cfg)` + `prep.is_f2_narratif_enabled(cfg)` → `a1_assembler` ordonne les blocs.

### 5.4 F2 compact façon vrillage (cible Phase C)

Spec formelle Phase B : **[`P7-F2-COMPACT-SPEC.md`](P7-F2-COMPACT-SPEC.md)** (structure, filtrage, verdict, interdictions).

Résumé :

1. Synthèse métier  
2. Conclusion clé  
3. Contexte de l'analyse  
4. Indicateurs clés  
5. Tableau groupes/matrices **fiables** (filtré)  
6. Lecture Cp/Cpk simple  
7. Fiabilité statistique  
8. Lecture métier (synthèse, sans boucle groupe par groupe)  
9. Verdict métier  
10. Limite d'interprétation  
11. Traçabilité  

**Règles** : chiffres uniquement depuis S3 / `group_descriptive` ; filtrage effectif insuffisant et valeurs parasites avant verdict ; seuils YAML ; pas de n=1 en référence favorable ; pas de causalité abusive.

**Activation narratif expérimental (déconseillé prod)** :

```yaml
rapport_pdf:
  f2_narratif_enabled: true   # défaut false — narratif long P7-F2a–c
```

---

## 6. Mapping par intention (assemblage blocs)

| Intention | Familles P6 | Blocs narratif prioritaires |
|-----------|-------------|------------------------------|
| `portrait_statistique` | F1 | conclusion_key, context, key_indicators (1 var), simple_explanation (Cpk, QQ), charts×3, limits |
| `comparaison_groupes` | F2 | conclusion_key (pire/best group), key_indicators tableau matrices, business_reading×3, charts boxplot, actions matrice/OF |
| `diagnostic_causal` | F2 (+F5) | idem F2 + facteurs_influents + η² si P5 |
| `analyse_complete` | F1+F2+F3 | union contrôlée par plafond pages YAML |
| `conformite` / `tendance` / `anomalie` | F1/F7 | narratif raccourci + focus temporel |

**Layout `rapport_type`** (existant) : `complet` vs `simple` reste orthogonal au `render_mode` (matrice 2×2 possible ; défaut : complet + narratif pour portrait/causal/analyse).

---

## 7. Règles de contenu — `conclusion_key`

### 7.1 Structure obligatoire (3 parties)

1. **Constat** : variable / groupe critique + chiffre certifié (% hors tol, Cpk, p-value si comparaison).
2. **Gravité** : marge de sécurité, proximité limite, dispersion.
3. **Orientation** : que faire en premier (sans liste d’actions détaillée — réservée au plan).

### 7.2 Génération

| Étape | Responsable |
|-------|-------------|
| 1. Slots remplis depuis S3/P6 | Python `prep.build_conclusion_key()` |
| 2. Phrase fluide | Template Jinja-like **ou** S5 passe dédiée (≤80 mots, chiffres en entrée) |
| 3. Validation | R2 : tous les nombres ∈ specialist_results |

**Exemple portrait CR90** (slots certifiés) :

```text
Conclusion clé : CR90_INTRADOS_FORME est le point critique de l’intrados sur M2L1A1C (EQUATOR).
4,8 % des mesures dépassent les tolérances [0 ; 0,2] mm, avec un Cpk ajusté de 0,39 (log-normale).
La dispersion et la queue haute du QQ-plot indiquent un risque réel sur la limite haute.
Une analyse immédiate par matrice et période de production est recommandée.
```

---

## 8. Templates pédagogiques Python (`simple_explanation`)

Fichier cible : `systems/s7/templates_pedagogiques.py` (ou `systems/stats/pedagogy.py`).

| ID template | Déclencheur | Contenu |
|-------------|-------------|---------|
| `pedagogy_cpk` | Cpk présent | Définition + lecture seuils + phrase « dans ce cas » |
| `pedagogy_pct_hors_tol` | % hors tol | Définition LTI/LTS + lecture du % |
| `pedagogy_qqplot` | qqplot + verdict normalité | Queue, normalité, risque limite |
| `pedagogy_boxplot` | boxplot groupes | Médiane, outliers IQR, comparaison groupes |
| `pedagogy_histogram` | histogramme | Forme, nominal, densité loi |
| `pedagogy_pvalue` | Kruskal/ANOVA sig. | « différence significative entre groupes », pas causalité |
| `pedagogy_ic95` | IC présents F2 | Incertitude, prudence petits n |

**Interdit** : `non_normale`, `log_normale` bruts côté client → libellés `stats_format` / `_LOI_CLIENT_LABELS`.

S5 peut **alléger** la phrase, pas changer les chiffres.

---

## 9. `business_reading` (lecture métier hiérarchisée)

Structure fixe pour **F2** (comparaison) :

```text
### Priorité principale — {pire_groupe}
{paragraphe certifié : moyenne, % hors tol, Cpk, risque limite}

### Groupes à surveiller — {liste intermédiaire}
{1 paragraphe synthétique}

### Référence favorable — {meilleur_groupe}
{paragraphe + prudence effectif si n faible}
```

Pour **F1** (portrait seul) : un seul bloc « Lecture métier » sur la variable.

Source : `group_ranking`, `group_descriptive` (P6), pas invention LLM.

---

## 10. Règles S6 — plan d’action atelier (amont P7)

P7 **affiche** ; S6 **produit**. Spec comportementale S6 (à implémenter avec P7) :

### 10.1 Signaux → actions types

| Signal S3 | Actions Python (templates) |
|-----------|---------------------------|
| `% hors tol > 0` | Isoler OF / séries hors tol ; identifier dates ; ventiler par `group_by` |
| `Cpk < 1.0` | Réduire dispersion ; recentrer vs nominal ; côté LTI ou LTS le plus proche |
| `Cpk < 1.33` | Surveillance renforcée ; plan correction P2 |
| Kruskal/ANOVA p &lt; seuil | Classer groupes ; contrôle renforcé groupe critique ; confirmer Dunn |
| `non_normale` | Ne pas conclure sur moyenne seule ; utiliser médiane, IQR, P95 |
| `pire_groupe` défini | Nommer matrice/machine ; comparer aux 2e et 3e groupes |

### 10.2 Formulations interdites sans suite concrète

- « analyser les causes racines »
- « mettre en œuvre des mesures correctives »
- « procéder à une étude approfondie »
- « amélioration continue » seul

**Remplacement** : action + objet + responsable YAML + délai.

### 10.3 Priorités

- **P1** : jamais supprimées (déjà S6).
- **P2–P3** : agrégation par cause.
- **P4** : surveillance si GO global.

---

## 11. Graphiques et textes sous graphiques

| Exigence | Détail |
|----------|--------|
| Conserver PNG S4 | Preuve visuelle = différenciateur vs vrillage |
| Texte sous graphique | `portrait_chart_text_for_render` (P4) → templates P7 pédagogiques |
| Pas de doublon | Filtrer légendes vides et `Graphique : …` seul |
| Une phrase métier minimum | Relier forme graphique à risque tolérance |

---

## 12. Gestion des profils (visibilité, pas pipelines)

| Section | opérateur | technicien | ingénieur | directeur |
|---------|-----------|------------|-----------|-----------|
| conclusion_key | ✅ court | ✅ | ✅ | ✅ très court |
| business_context | ⚠️ simplifié | ✅ | ✅ | ⚠️ résumé |
| key_indicators | ✅ 3 lignes | ✅ | ✅ | ✅ |
| simple_explanation | ❌ | ✅ | ✅ | ❌ |
| charts | max 2 | max 8 | max 12 | max 3 |
| portrait_statistique | ❌ | ✅ | ✅ | ❌ |
| metrics_table détaillé | ❌ | ✅ | ✅ | ⚠️ synthèse |
| business_reading | ✅ 1 bloc | ✅ | ✅ | ✅ |
| interpretation_limits | ❌ | ✅ | ✅ | ⚠️ 1 phrase |
| annexe_dunn | ❌ | ⚠️ | ✅ | ❌ |
| p-values / Cpk bruts | masqués | affichés | affichés | masqués / reformulés |

Config : `rapport_pdf.sections_par_profil` dans YAML (à ajouter en P7).

---

## 13. Quality gate P7 (extension)

Contrôles additionnels (`systems/s7/quality_gate.py`) :

- [ ] `conclusion_key` non vide en mode narratif
- [ ] Au moins une action P1 si % hors tol &gt; 0 ou Cpk &lt; 1.33
- [ ] `interpretation_limits` présent si F2/F5
- [ ] Pas de termes `forbidden_words` profil
- [ ] Pas de placeholder « pièce A », « causes racines » non qualifié
- [ ] Graphiques : ≥1 si `charts` prévu par intention

Violations → **warning** (PDF généré), sauf mode strict client optionnel.

---

## 14. Checklist d’acceptation « niveau vrillage »

Pour **portrait NO-GO** (CR90) et **comparaison matrices** (M2L1A1C) :

- [ ] Lecture sans ouvrir les annexes : problème + gravité + priorité en &lt;30 s
- [ ] Contexte : nominal, tolérances, définition hors tol
- [ ] Tableau indicateurs clés (pas seulement 20 lignes portrait)
- [ ] Encadré « Comment lire le Cpk » (ou équivalent)
- [ ] Hiérarchie métier (critique / surveillance / favorable) si groupes
- [ ] Plan d’action avec verbes atelier (OF, matrice, machine, période)
- [ ] § limites d’interprétation visible
- [ ] Graphiques **avec** phrase métier sous chaque figure
- [ ] Pas de N/A, AIC brut, `non_normale` visible
- [ ] SHA-256 et traçabilité conservés
- [ ] Mode audit toujours disponible pour même run

---

## 15. Plan d’implémentation recommandé

**Prérequis** : P6 Phase 1–2 (sorties F2 structurées) pour comparaison matrices premium.

| Étape | Composant | Livrable |
|-------|-----------|----------|
| 1 | S6 | Règles actions §10 (templates) |
| 2 | `templates_pedagogiques.py` + `build_conclusion_key` | Contenu certifié |
| 3 | S7 `prep.resolve_render_mode` + A1 ordre blocs | Deux modes PDF |
| 4 | `renderer_stub` sections nouveaux blocs | Mise en page |
| 5 | S5 | Passe optionnelle reformulation `conclusion_key` / `business_reading` |
| 6 | YAML + quality gate | Profils sections |
| 7 | Tests `test_s7_rapport_metier.py` | Non-régression + checklist §14 |

**Ne pas** implémenter P7 complet avant P6 F2 enrichi si l’objectif est le **niveau vrillage comparaison** ; le portrait peut démarrer plus tôt (F1 déjà riche).

---

## 16. Relation avec le travail P4 déjà livré

| Élément P4 | Sort P7 |
|------------|---------|
| Layout `complet` / `simple` | Conservé ; enrichi par `render_mode` |
| `portrait_statistique`, GRAPHIQUES | Intégrés au mode narratif |
| `portrait_chart_text_for_render` | Remplacé progressivement par templates §8 |
| Quality gate client | Étendu §13 |
| PR `feat/p4-pdf-portrait-complet` | Base technique, pas fin P7 |

---

## 17. Documents liés

| Fichier | Lien |
|---------|------|
| `docs/P6-CARTOGRAPHIE-ANALYTIQUE.md` | Familles, sorties `summary` |
| `docs/S7.md` | Agents A1–A4, SHA-256 |
| `docs/PHILOSOPHY.md` | §8 PDF, §28 langage |
| `configs/lisi_aerospace/client_config.yaml` | `rapport_pdf`, `contrat_rapport` |

---

*Chantier P7 — rapport métier premium. Implémentation après validation conjointe P6 + P7 et choix de l’ordre des phases (§15 vs P6 §12).*
