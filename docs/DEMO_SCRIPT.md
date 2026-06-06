# Script de démonstration — IndustrIA

> **Statut** : **GUIDE DÉMO**  
> **Version** : 1.0 — 2026-06-02  
> **Public** : portfolio, client pilote, responsable qualité / méthodes  
> **Périmètre** : client démo aéronautique — **aucun client réel nommé**

---

## 1. Objectif de la démo

IndustrIA transforme une **question métier industrielle** en **rapport qualité exploitable** (PDF), en restant **local**, **traçable** et **config-driven**.

| Ce que la démo doit montrer | Détail |
|----------------------------|--------|
| **Chaîne complète** | S1 (question) → S2 (`df_propre`) → S3 (statistiques) → S4 (graphiques) → S5/S6 (interprétation) → S7 (PDF) |
| **F2 compact standard** | Faible cardinalité — ex. passage pastille P1 / P2 |
| **F2 high-cardinality** | Forte cardinalité — ex. niveau de retaille (top 5 + référence favorable + Autres modalités) |
| **Adaptation client** | Même moteur, vocabulaire et règles via YAML (`configs/<client>/`) |
| **Données locales** | Export CSV dans `data/` (gitignored) — **jamais versionné** |
| **PDF locaux** | Livrables dans `outputs/` (gitignored) — **jamais commités** |

```
Question métier (langage naturel)
        │
        ▼
   S1 intent ──► S2 df_propre ──► S3 ranking + tests
        │                              │
        └──────── config YAML ─────────┘
                                       ▼
                         S4 graphiques → S7 PDF F2 compact
```

---

## 2. Scénario de démo

| Élément | Valeur |
|---------|--------|
| **Pièce (modèle)** | RD4L1A1C |
| **Opération** | FILAGE |
| **Variable quantitative** | CR1 |
| **Config** | `configs/lisi_aerospace/client_config_traceability.yaml` |
| **Niveau d'analyse** | Mesure capteur (une ligne par mesure) |
| **Données** | `data/lisi_capteurs_export_complet_tracabilite.csv` (local, gitignored) |
| **Mode F2** | `f2_compact_enabled: true` **en mémoire** pour les runs démo (hors YAML commité) |

> Prérequis local : export traçabilité présent dans `data/`, cache parquet régénéré si besoin (`ensure_partitions`).

---

## 3. Questions de démo recommandées

Poser les questions **en langage naturel** (S1). Ordre suggéré : du cas simple au cas riche.

| # | Question à poser | Mode F2 attendu |
|---|----------------|-----------------|
| 1 | `Comparer CR1 selon le numéro de passage de la pastille extérieure sur RD4L1A1C au filage` | F2 compact **standard** |
| 2 | `Comparer CR1 selon le numéro de passage de la pastille intérieure sur RD4L1A1C au filage` | F2 compact **standard** |
| 3 | `Comparer CR1 selon le niveau de retaille de la pastille extérieure sur RD4L1A1C au filage` | F2 compact + **high-cardinality** |
| 4 | `Comparer CR1 selon le niveau de retaille de la pastille intérieure sur RD4L1A1C au filage` | F2 compact + **high-cardinality** |

### Question bonus — cas non exploitable

| Question | Effet attendu |
|----------|---------------|
| `Comparer CR1 par fournisseur de la pastille intérieure sur RD4L1A1C au filage` | **Une seule modalité** fournisseur sur ce périmètre → pas de comparaison inter-groupes, pas de PDF F2 comparatif |

---

## 4. Ce que chaque question démontre

| Question | `group_by` (S1) | Démo produit |
|----------|-----------------|--------------|
| Passage extérieur | `PAS_E_Numero_Passage` | F2 standard, **2 groupes** P1 / P2, tableau complet |
| Passage intérieur | `PAS_I_Numero_Passage` | F2 standard, symétrie ext/int, labels pastille via YAML |
| Retaille extérieure | `PAS_E_Niveau_Retaille` | High-cardinality : **41** modalités fiables → **7 lignes** affichées |
| Retaille intérieure | `PAS_I_Niveau_Retaille` | High-cardinality : **28** modalités (post-normalisation S2) → **7 lignes** |
| Fournisseur (bonus) | `PAS_I_Fournisseur` | Gestion **modalité unique** — honnêteté produit |

Points narratifs à souligner pendant la démo :

- **S1** : compréhension du langage métier (pastille ext/int, retaille, filage).
- **S2** : nettoyage (`retaille <= 0`), normalisation des formats (`-1.5` → `-1,5`).
- **S3** : ranking exhaustif — la vérité statistique ne dépend pas du PDF.
- **S7** : projection présentation uniquement (labels, top K, remainder).

---

## 5. Résultats attendus (validés sur `main`)

### Passage pastille — F2 standard

| Côté | Groupe prioritaire | Groupe favorable | Verdict |
|------|-------------------|------------------|---------|
| Extérieur (P1 / P2) | **P2** | **P1** | NO-GO |
| Intérieur (P1 / P2) | **P2** | **P1** | NO-GO |

### Retaille pastille — F2 high-cardinality

| Côté | Prioritaire | Modalités fiables (S3) | Lignes PDF (S7) | Verdict |
|------|-------------|------------------------|-----------------|---------|
| Extérieure | **-16** | 41 | 7 | NO-GO |
| Intérieure | **-5** | 28 | 7 | NO-GO |

**Retaille intérieure — top 5 S3** (inchangé post-normalisation S2) : **-5**, **-8**, **-1**, **-1,5**, **-3**.  
**Référence favorable** : **-0,5**.  
**Kruskal-Wallis** : significatif sur les cas retaille.

**Effectifs « Autres modalités »** (non tronqués en PDF) : **37 301** (ext.) / **26 946** (int.).

### Limites à rappeler à l'oral

- Les écarts sont des **associations statistiques**, pas une **causalité directe**.
- Niveau **mesure capteur** — pas d'agrégation OF / pièce contrôlée dans ces livrables.
- Les recommandations S6 **complètent** l'expert métier ; elles ne le remplacent pas.

Référence détaillée : [F2-PASTILLES-CAMPAIGN-RD4L1A1C.md](./F2-PASTILLES-CAMPAIGN-RD4L1A1C.md).

---

## 6. Points à montrer dans le PDF

Parcourir le PDF dans cet ordre — chaque bloc illustre une capacité produit :

| Bloc PDF | Ce qu'il prouve |
|----------|-----------------|
| **Conclusion clé** | Synthèse actionnable (verdict NO-GO / GO) |
| **Tableau des groupes** | Ranking S3 projeté (standard ou high-cardinality) |
| **Cpk** | Capabilité process par groupe |
| **% hors tolérance** | Indicateur métier prioritaire |
| **IC95** | Intervalle de confiance sur la proportion |
| **Boxplot** | Distribution visuelle ; label métier sur titre et axe X |
| **Test Kruskal-Wallis** | Comparaison non paramétrique multi-groupes |
| **Limites d'interprétation** | Garde-fou association ≠ causalité |
| **Traçabilité SHA-256** | Empreinte du livrable — reproductibilité locale |

En mode **high-cardinality**, vérifier visuellement :

- **Top 5** des groupes à risque ;
- **Référence favorable** distincte (ex. `-0,5` pour retaille int.) ;
- Ligne **« Autres modalités »** avec effectif complet (non tronqué).

---

## 7. Ce que la démo prouve côté produit

| Capacité | Illustration démo |
|----------|-------------------|
| **Moteur analytique générique** | Même pipeline S1→S7 pour passage et retaille |
| **Adaptation via config** | YAML client démo : colonnes, tolérances, synonymes S1, règles S2 |
| **Faible cardinalité** | Passage P1/P2 — tableau complet |
| **Forte cardinalité** | Retaille — projection top K sans altérer S3 |
| **Modalité unique** | Fournisseur — refus honnête de produire un faux comparatif |
| **Pipeline local** | Pas de cloud obligatoire ; données et PDF restent sur la machine |
| **Traçabilité** | SHA-256 du PDF, quality gate S7 |
| **Lisibilité métier** | Rapport compréhensible par qualité, méthodes et production |

---

## 8. Ce qu'il ne faut pas promettre

| À éviter | Formulation honnête |
|----------|---------------------|
| Causalité prouvée | « Le système **associe** des écarts à des facteurs ; l'investigation terrain reste nécessaire. » |
| Tout export sans adaptation | « Chaque nouveau format passe par l'**onboarding config** (S0/S1/S2). » |
| Remplacement de l'expert | « Le PDF **aide à prioriser** ; la décision reste humaine. » |
| PDF / données versionnés | « Livrables et exports restent **locaux** — jamais dans git. » |
| Démo = production industrialisée | « POC pilote validé ; industrialisation SI = chantier séparé. » |

---

## 9. Commandes / workflow de démo

### Script existant (référence)

Le dépôt contient `scripts/generate_rapport_lisi.py` — pipeline **S1 → S7** complet avec écriture PDF :

```bash
python scripts/generate_rapport_lisi.py outputs/mon_rapport.pdf --question "Votre question ici"
```

**Limites pour cette démo F2 pastilles** :

- Le script pointe par défaut vers `configs/lisi_aerospace/client_config.yaml` (pas la variante traçabilité).
- Le mode F2 compact requiert `f2_compact_enabled: true` **en mémoire** (non activé par défaut dans le YAML).

### À adapter selon le script local (parcours F2 pastilles)

Étapes générales validées par la campagne — à reproduire via votre wrapper local ou notebook :

| Étape | Action | Contrôle |
|-------|--------|----------|
| 1 | Poser la question (§3) | S1 : `clarification_needed: false`, bons `piece` / `operation` / `variables` / `group_by` |
| 2 | Charger `client_config_traceability.yaml` | Export présent dans `data/` |
| 3 | Exécuter S2 | `df_propre` non vide ; règles retaille `applied` ; formats normalisés |
| 4 | Exécuter S3 | Groupes fiables, Kruskal significatif (retaille), ranking cohérent |
| 5 | Activer F2 compact en mémoire | `f2_compact_enabled: true` sur la config rapport PDF |
| 6 | Exécuter S4 → S5/S6 → S7 | PDF généré localement |
| 7 | Écrire le PDF | `outputs/f2_pastilles_<cas>_RD4L1A1C.pdf` — **ne pas committer** |

Noms de fichiers PDF locaux (convention campagne) :

| Cas | Fichier suggéré |
|-----|-----------------|
| Passage extérieur | `outputs/f2_pastilles_passage_ext_RD4L1A1C.pdf` |
| Passage intérieur | `outputs/f2_pastilles_passage_int_RD4L1A1C.pdf` |
| Retaille extérieure | `outputs/f2_pastilles_retaille_ext_RD4L1A1C.pdf` |
| Retaille intérieure | `outputs/f2_pastilles_retaille_int_RD4L1A1C.pdf` |

### Vérifications post-run

```bash
git status
git ls-files "*.pdf"
git ls-files "outputs/*"
```

Attendu : **working tree clean**, aucun PDF/output tracké.

### Régression rapide (optionnel, avant une démo live)

```bash
pytest systems/s1/tests/ -q
pytest systems/s2/tests/ -q
pytest systems/s7/tests/ -q
```

---

## 10. Documentation complémentaire

| Document | Usage démo |
|----------|------------|
| [F2-PASTILLES-CAMPAIGN-RD4L1A1C.md](./F2-PASTILLES-CAMPAIGN-RD4L1A1C.md) | Résultats validés, verdicts, limites, PDF locaux |
| [CLIENT_ONBOARDING.md](./CLIENT_ONBOARDING.md) | Onboarding nouveau client, protocole POC, arbre de décision format |
| [P7-F2-HIGH-CARDINALITY.md](./P7-F2-HIGH-CARDINALITY.md) | Règles top K, favorable, remainder, disclaimer |
| [P7-F2-COMPACT-SPEC.md](./P7-F2-COMPACT-SPEC.md) | Spécification F2 compact (blocs, seuils, activation) |
| [P8-TRACEABILITE-INTEGRATION.md](./P8-TRACEABILITE-INTEGRATION.md) | Export traçabilité, `pivot_index_keys`, config traceability |

---

## Annexe — déroulé oral suggéré (15–20 min)

1. **Contexte** (2 min) : question qualité sur filage, pastilles, capteur CR1.
2. **Question simple** (3 min) : passage extérieur → PDF 2 groupes → P2 prioritaire.
3. **Symétrie** (2 min) : passage intérieur → même logique, labels YAML.
4. **Cardinalité riche** (5 min) : retaille intérieure → high-cardinality, top 5, favorable, Autres.
5. **Honnêteté produit** (2 min) : fournisseur non exploitable ; association ≠ causalité.
6. **Traçabilité** (2 min) : SHA-256, pipeline local, données non versionnées.
7. **Ouverture** (2 min) : onboarding client via [CLIENT_ONBOARDING.md](./CLIENT_ONBOARDING.md).
