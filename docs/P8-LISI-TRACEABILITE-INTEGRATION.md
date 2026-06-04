# P8 — Intégration export complet traçabilité LISI

> **Statut** : en cours — Phase I0–I1 (spec + YAML préparatoire)  
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
| **I2** | `pivotter.py` lit `dataset.pivot_index_keys` ; option normalisation retaille | ⏳ |
| **I3** | Bascule `dataset.fichier` + rebuild cache forcé + manifeste enrichi | ⏳ |
| **I4** | Tests S2 traçabilité (+ fixture CSV léger CI) | ⏳ |
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

Les clés `pas_*` restent gérées par la logique actuelle du pivotter jusqu’à harmonisation Phase I2.

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

**Critère de déblocage F3** : test T5/T6 (appariement CRx par `Numero Piece Contrôlée`) vert après I2 + I3.

---

## 8. Faisabilité post-intégration complète (rappel)

| Capacité | Après I1 seul | Après I2 + I3 |
|----------|---------------|---------------|
| F3 intra-opération | ❌ | ✅ (si appariement pièce validé) |
| F3 inter-opérations | ❌ | ⚠️ si même `numero_piece` ou OF sur FILAGE+EQUATOR |
| F2 × passage / fournisseur / retaille pastille | ❌ pivot | ✅ |
| Agrégation OF (S3) | ❌ (`enabled: false`) | ✅ après activation explicite |

---

## 9. Hors scope chantier global

- PDF, F2 compact, `f2_compact_enabled: true`
- Code F3, S7, modification S3/S4
- Suppression `data/lisi_capteurs.csv`
- Activation `agregation_metier_f2.enabled: true` en Phase I1

---

## 10. Références

- Audit traçabilité (conversation) : export 18 cols, tags pastille vides en LONG.
- `systems/s2/pivotter.py` : `meta_keys` figées — à généraliser Phase I2.
- `configs/test_generic/client_config.yaml` : modèle `agregation_metier_f2`.
