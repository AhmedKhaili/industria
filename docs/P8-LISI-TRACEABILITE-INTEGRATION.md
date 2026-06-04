# P8 — Intégration export complet traçabilité LISI

> **Statut** : Phase I0–I1 livrée (`e053e11`) — plan tests `df_propre` intégré avant I2  
> **Branche** : `feat/lisi-traceability-export-integration`  
> **Prérequis** : `docs/VISION.md`, `docs/P6-CARTOGRAPHIE-ANALYTIQUE.md`, `docs/P7-F2-COMPACT-SPEC.md`, `docs/PHILOSOPHY.md`

---

## 1. Contexte

### Ancien export (`data/lisi_capteurs.csv`)

| Attribut | Valeur |
|----------|--------|
| Colonnes | **9** |
| Format | LONG (`Tag`, `Value`) |
| Traçabilité | `Designation Reference` = **modèle** (ex. RD4L1A1C) uniquement |
| Pastilles | Colonnes `PAS_*` **absentes** → règles S2 `skipped` |
| OF / pièce contrôlée | **Absents** |
| Usage actuel | `dataset.fichier` par défaut ; tests S2 LISI ; campagne F2 compact v1 validée |

### Nouvel export (`data/lisi_capteurs_export_complet_tracabilite.csv`)

| Attribut | Valeur |
|----------|--------|
| Colonnes | **18** |
| Format | LONG (`Tag`, `Value`) |
| Taille / volume | ~494 Mo, ~4,66 M lignes (périmètre différent de l’ancien ~8,5 M lignes) |
| Traçabilité | `Numero OF MAR`, `Numero Piece Contrôlée` |
| Pastilles | Colonnes physiques `PAS_E_*`, `PAS_I_*` renseignées (FILAGE) |
| `Nominal` | Colonne physique présente |

**Fichier copié dans le dépôt** : `C:\Dev\industria\data\lisi_capteurs_export_complet_tracabilite.csv`  
**Conservation** : `data/lisi_capteurs.csv` **non supprimé**.

### Principe d’intégration

- **Un seul pipeline** S1→S7 (PHILOSOPHY, P6).
- Extension **S0 (YAML)** puis **S2 générique** (`pivot_index_keys`) — pas de pipeline parallèle.
- **Pas de F3**, pas de PDF, pas de modification S7 / F2 compact dans ce chantier initial.

---

## 2. Colonnes nouvelles (mapping YAML)

| Clé YAML | Colonne CSV | Rôle |
|----------|-------------|------|
| `numero_of` | `Numero OF MAR` | Ordre de fabrication / regroupement OF |
| `numero_piece` | `Numero Piece Contrôlée` | Pièce contrôlée (unité de mesure) |
| `nominal` | `Nominal` | Valeur nominale (déjà mappé) |
| `piece` | `Designation Reference` | **Modèle produit** — clé inchangée |
| `pas_*` | `PAS_E_*`, `PAS_I_*` | Pastilles FILAGE (mappings existants) |

Tags LONG `PAS_E` / `PAS_I` : `Value` toujours vide ; **l’info pastille est dans les colonnes physiques**.

---

## 3. Risques

| Risque | Impact | Mitigation |
|--------|--------|------------|
| **Cache parquet legacy** (9 cols) | Parquets sans OF/pièce si rebuild oublié | Checklist rebuild §6 ; fingerprint manifeste (Phase I3) |
| **Pivot non indexé** (Phase I1) | `pivot_index_keys` en YAML mais **S2 non branché** → OF/pièce pas dans `df_propre` | Phase I2 obligatoire avant F3 / pastilles F2 |
| **Virgule décimale retaille** (`-18,5`) | `pd.to_numeric` peut échouer → règles retaille fausses | Test Phase I4 ; normalisation cleaner Phase I2 si besoin |
| **Bascule `dataset.fichier`** | Tests S2 / CI cassés | Garder ancien fichier actif jusqu’à Phase I3 ; `fichier_tracabilite` documenté |
| **Confusion `piece` YAML** | `piece` = modèle, pas pièce contrôlée | Clés distinctes `numero_piece` / `piece` |
| **Ops hors scope** | CSV contient EBAUCHEBULBE, FORMAGE | `operations_actives` reste FILAGE + EQUATOR |

---

## 4. Phases I0 à I5

| Phase | Contenu | Statut |
|-------|---------|--------|
| **I0** | Ce document | ✅ |
| **I1** | YAML : mappings, `pivot_index_keys`, `agregation_metier_f2` (disabled), `fichier_tracabilite` | ✅ |
| **I2** | `pivotter.py` lit `dataset.pivot_index_keys` ; option normalisation retaille ; **prérequis** : cas §11 verts | ⏳ |
| **I3** | Bascule `dataset.fichier` + rebuild cache forcé + manifeste enrichi | ⏳ |
| **I4** | Tests automatisés §11 sur **sortie réelle** `intent` + `df_propre` (S1→S2) | ⏳ |
| **I5** | Doc VISION / P7 §18 ; entités S1 OF / pièce contrôlée | ⏳ |

---

## 5. Configuration YAML (Phase I1)

### Fichier actif vs traçabilité

| Champ | Valeur Phase I1 | Lecture S2 |
|-------|-----------------|------------|
| `dataset.fichier` | `data/lisi_capteurs.csv` | **Oui** — inchangé pour ne pas casser les tests |
| `dataset.fichier_tracabilite` | `data/lisi_capteurs_export_complet_tracabilite.csv` | **Non** (documenté ; bascule Phase I3) |
| `dataset.fichier_legacy` | commentaire / référence | Documentation |

Config manuelle pour essais (Phase I3, sans toucher la config par défaut) :  
`configs/lisi_aerospace/client_config_traceability.yaml` — copie UTF-8 de la config LISI avec `dataset.fichier` pointant vers l’export traçabilité.

### `pivot_index_keys` (préparation — effet après I2)

Ordre proposé :

1. `temps`
2. `numero_piece`
3. `numero_of`
4. `piece` (modèle)
5. `operation`
6. `machine`
7. `matrice`

Phase **I2** doit aussi garantir que les colonnes `PAS_*` physiques restent dans l’index pivot (logique `pas_*` actuelle du pivotter + inclusion explicite via `pivot_index_keys` si harmonisation).

### `agregation_metier_f2`

- `enabled: false` en Phase I1.
- Unité `of_mar` → `Numero OF MAR` préconfigurée.
- Unité `piece_controlee` → disabled.

---

## 6. Checklist rebuild cache (Phase I3)

À exécuter **une seule fois** lors de la bascule vers l’export traçabilité :

1. [ ] Valider que `data/lisi_capteurs_export_complet_tracabilite.csv` est présent (~494 Mo).
2. [ ] Mettre à jour `dataset.fichier` vers l’export traçabilité (ou utiliser `client_config_traceability.yaml`).
3. [ ] Supprimer ou archiver `data/cache/lisi_aerospace/_manifest.json` et les parquets sous `FILAGE/` et `EQUATOR/` **ou** appeler `ensure_partitions(..., force=True)`.
4. [ ] Vérifier `_manifest.json` : `csv_path` pointe vers le nouveau fichier.
5. [ ] Ouvrir un parquet test (ex. `FILAGE/RD4L1A1C.parquet`) : **18 colonnes**, présence de `Numero OF MAR`, `Numero Piece Contrôlée`, `PAS_E_Numero_Passage`.
6. [ ] Run S2 léger : intent FILAGE CR1+CR2 → `df_propre` contient clés traçabilité (**après Phase I2**).
7. [ ] Ne pas mélanger ancien et nouveau cache sans rebuild complet.

---

## 7. Limites — pas de F3 avant clés dans `df_propre`

Tant que **Phase I2** n’est pas livrée :

- `Numero Piece Contrôlée` et `Numero OF MAR` ne sont **pas** dans l’index du pivot.
- F3 « propre » (corrélation sur même pièce), F2 pastilles exploitables, agrégation OF : **bloqués côté pipeline** malgré la présence des colonnes dans le CSV.
- Les colonnes existent en parquet **après rebuild** sur le bon fichier, mais disparaissent du wide si l’index pivot ne les inclut pas.

**Critère de déblocage F3** : cas **TC-01** et **TC-02** (§11) verts après I2 + I3.

---

## 8. Tests d’acceptation pipeline — `df_propre` réel (I2 / I4)

> **Principe** : l’intégration traçabilité n’est validée que si, pour une **question métier donnée**, la chaîne **S1 → S2** produit un `intent` correct et un `df_propre` contenant les **bonnes variables** et les **bonnes colonnes de traçabilité** après pivot.  
> Vérifier uniquement le YAML ou les colonnes du parquet **ne suffit pas**.

### Prérequis d’exécution (tous les cas TC-01 à TC-04)

| Prérequis | Détail |
|-----------|--------|
| Config | `configs/lisi_aerospace/client_config_traceability.yaml` (`dataset.fichier` → export 18 cols) |
| Données | `data/lisi_capteurs_export_complet_tracabilite.csv` présent localement |
| Cache | Rebuild complet `data/cache/lisi_aerospace/` (checklist §6) |
| Code | Phase **I2** livrée (`pivot_index_keys` + `pas_*` dans l’index pivot) |
| Hors scope exécution | Pas de PDF, pas de S3/S7, pas de `f2_compact_enabled` |

**Méthode de vérification** (manuelle ou pytest Phase I4) :

1. `intent = S1Pipeline(yaml_traceability).run(question)` — assertions sur `variables`, `operation`, `piece`, `group_by`.
2. `result = S2Pipeline(yaml_traceability).run(intent)` — `result["error"] is None`.
3. `df = result["df_propre"]` — assertions sur **noms de colonnes** et, si pertinent, `cleaning_stats` / `df_anomalies`.

---

### TC-01 — F3 intra-opération FILAGE (corrélation future)

**Question** :

```text
Analyser la relation entre CR1 et CR2 sur RD4L1A1C au filage
```

| Contrôle | Attendu |
|----------|---------|
| **S1 — variables** | `CR1`, `CR2` (ordre indifférent) |
| **S1 — operation** | `FILAGE` |
| **S1 — piece (modèle)** | `RD4L1A1C` |
| **S1 — intention** | compatible F3 / association (ex. `comparaison_groupes` ou intention dédiée F3 à trancher en I5) |
| **df_propre — variables** | colonnes `CR1`, `CR2` présentes |
| **df_propre — traçabilité** | `Numero Piece Contrôlée`, `Numero OF MAR`, `Date`, `Numero Machine` |
| **df_propre — modèle** | `Designation Reference` = `RD4L1A1C` sur toutes les lignes |
| **Pivot** | pas de `Tag` / `Value` ; clés traçabilité **non perdues** |
| **Appariement** | pour une même `Numero Piece Contrôlée`, `CR1` et `CR2` non null sur la **même ligne** (≥ 95 % des pièces avec les deux mesures ; doublons timestamp documentés) |

---

### TC-02 — F3 intra-opération EQUATOR

**Question** :

```text
Analyser la relation entre CR50_INTRADOS_VRILLAGE et CR70_INTRADOS_VRILLAGE sur RD4L1A1C EQUATOR
```

| Contrôle | Attendu |
|----------|---------|
| **S1 — variables** | `CR50_INTRADOS_VRILLAGE`, `CR70_INTRADOS_VRILLAGE` |
| **S1 — operation** | `EQUATOR` |
| **S1 — piece (modèle)** | `RD4L1A1C` |
| **df_propre — variables** | les deux colonnes CR50 / CR70 |
| **df_propre — traçabilité** | `Numero Piece Contrôlée`, `Numero OF MAR`, `Ref_Matrice`, `Numero Machine`, `Date` |
| **Pivot** | pas de perte des clés de traçabilité au pivot |
| **Appariement** | même logique TC-01 sur `Numero Piece Contrôlée` |

---

### TC-03 — F2 FILAGE × passage pastille extérieure

**Question** :

```text
Comparer CR1 selon le numéro de passage de la pastille extérieure sur RD4L1A1C au filage
```

| Contrôle | Attendu |
|----------|---------|
| **S1 — variable** | `CR1` |
| **S1 — group_by** | `PAS_E_Numero_Passage` |
| **S1 — operation** | `FILAGE` |
| **S1 — piece** | `RD4L1A1C` |
| **S2 — nettoyage** | `cleaning_stats.rules.PAS_E_Numero_Passage.status` = **`applied`** (plus `colonne_absente`) |
| **S2 — valeurs passage** | uniquement `P1` / `P2` dans `df_propre` ; hors {P1,P2} dans `df_anomalies` ou absents |
| **df_propre — colonnes** | `CR1`, `PAS_E_Numero_Passage`, `Numero Piece Contrôlée`, `Numero OF MAR` (+ index usuels `Date`, `Numero Machine`, `Designation Reference`) |

---

### TC-04 — F2 FILAGE × niveau retaille extérieur

**Question** :

```text
Comparer CR1 selon le niveau retaillé de la pastille extérieure sur RD4L1A1C au filage
```

| Contrôle | Attendu |
|----------|---------|
| **S1 — variable** | `CR1` |
| **S1 — group_by** | `PAS_E_Niveau_Retaille` |
| **S1 — operation** | `FILAGE` |
| **S2 — nettoyage** | `cleaning_stats.rules.PAS_E_Niveau_Retaille.status` = **`applied`** |
| **Règle métier** | valeurs dans `df_propre` : retaille **≤ 0** (après parsing numérique, virgule décimale incluse) |
| **Anomalies** | valeurs strictement positives dans `df_anomalies` ou absentes de `df_propre` |
| **df_propre — colonnes** | `CR1`, `PAS_E_Niveau_Retaille`, `Numero Piece Contrôlée`, `Numero OF MAR` |

---

### TC-05 — Agrégation OF (test futur — hors I2/I4 immédiat)

**Question** :

```text
Comparer CR1 selon la presse par OF sur RD4L1A1C au filage
```

| Contrôle | Attendu (futur) |
|----------|-----------------|
| **S1 — variable** | `CR1` |
| **S1 — group_by** | `Numero Machine` (presse) |
| **S3 — unité** | agrégation par `Numero OF MAR` via `agregation_metier_f2` (`enabled: true`, unité `of_mar`) |
| **Phase** | après activation explicite `agregation_metier_f2` + routage S3 ; **documenter seulement** en I4 |

---

## 9. Plan tests automatisés (Phase I4)

Fichier cible : `systems/s2/tests/test_s2_traceability_pipeline.py` (et/ou `systems/s1/tests/test_s1_traceability_intent.py`).

| ID | Test pytest (proposé) | Chaîne | Skip si |
|----|------------------------|--------|---------|
| TC-01 | `test_tc01_filage_cr1_cr2_df_propre_columns_and_pairing` | S1→S2 | export ou cache absent |
| TC-02 | `test_tc02_equator_cr50_cr70_df_propre_columns` | S1→S2 | idem |
| TC-03 | `test_tc03_filage_passage_pastille_applied_and_columns` | S1→S2 | idem |
| TC-04 | `test_tc04_filage_retaille_rule_applied_and_non_positive` | S1→S2 | idem |
| TC-05 | `test_tc05_of_aggregation_skipped_until_enabled` | — | `@pytest.mark.skip` jusqu’à Phase agrégation |

**Assertions obligatoires dans chaque test** :

- `assert col in df.columns` pour chaque colonne attendue (noms **physiques** CSV, pas clés YAML abstraites).
- `assert "Tag" not in df.columns` et `assert "Value" not in df.columns`.
- Pour TC-03/04 : parcours `result["cleaning_stats"]["rules"]`.
- Pour TC-01/02 : sous-ensemble de lignes où les deux variables sont non null, grouper par `Numero Piece Contrôlée`, vérifier une ligne par pièce (ou quota documenté).

**Fixture** : option petit CSV d’extrait (~2k lignes) pour CI sans 500 Mo — sinon `@pytest.mark.integration` + skip si fichier manquant.

**Critère de sortie I4** : TC-01 à TC-04 verts sur `client_config_traceability.yaml` ; tests legacy (`client_config.yaml` + ancien CSV) restent verts en parallèle.

---

## 10. Faisabilité post-intégration complète (rappel)

| Capacité | Après I1 seul | Après I2 + I3 |
|----------|---------------|---------------|
| F3 intra-opération | ❌ | ✅ (si appariement pièce validé) |
| F3 inter-opérations | ❌ | ⚠️ si même `numero_piece` ou OF sur FILAGE+EQUATOR |
| F2 × passage / fournisseur / retaille pastille | ❌ pivot | ✅ |
| Agrégation OF (S3) | ❌ (`enabled: false`) | ✅ après activation explicite |

---

## 11. Hors scope chantier global

- PDF, F2 compact, `f2_compact_enabled: true`
- Code F3, S7, modification S3/S4
- Suppression `data/lisi_capteurs.csv`
- Activation `agregation_metier_f2.enabled: true` en Phase I1

---

## 12. Références

- Audit traçabilité (conversation) : export 18 cols, tags pastille vides en LONG.
- `systems/s2/pivotter.py` : `meta_keys` figées — à généraliser Phase I2.
- `configs/test_generic/client_config.yaml` : modèle `agregation_metier_f2`.
