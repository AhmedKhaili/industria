# AGENTS.md — IndustrIA Architecture v2.1
# Source de vérité absolue — issu de validation 4 LLMs

---

## PRINCIPE FONDAMENTAL (non négociable)

LLM = parser sémantique JSON uniquement
Code analytique = Python dur-codé TOUJOURS
LLM ne calcule jamais
LLM ne choisit jamais une méthode statistique
LLM n'exécute jamais de code

---

## PIPELINE COMPLET

```
QUESTION UTILISATEUR
        ↓
AGENT 1 — Analyste Sémantique
        ↓
AGENT 2 — SQL Engine
        ↓
AGENT 3 — Nettoyeur (Python pur)
        ↓
AGENT 4a — Méthodologue (intention JSON)
        ↓
AGENT 4b — Dispatcher (Python pur)
        ↓
SPÉCIALISTES (Python pur, asyncio parallèle)
        ↓
STATISTICIAN JUDGE (Python pur)
        ↓
AGENT 5 — OAPC (priorité, prescrire, certifier — Python pur)
        ↓
AGENT 6a — Interprète générique (LLM × N, 1 par spécialiste)
        ↓
AGENT 6b — Synthèse globale (LLM × 1)
        ↓
AGENT 6c — Constructeur PDF (Python pur — ReportLab + Plotly)
        ↓
STREAMLIT + monitoring planifié (Sprint 5)
```

---

## AGENT 1 — Analyste Sémantique

| Champ | Valeur |
|-------|--------|
| Fichier | enterprise/agents/agent_1_analyst.py |
| Modèle | qwen2.5-coder:7b |
| num_ctx | 8000 |
| num_predict | 150 |
| temperature | 0.1 |
| LLM | OUI — extraction JSON uniquement |

REÇOIT :
  question: str
  schema_catalog: dict (via pgvector similarity)

FAIT :
  1. Requête pgvector dans TimescaleDB
     → récupère 2-3 tables les plus proches
     → cosine similarity sur descriptions
  2. Envoie au LLM : question + schéma réduit
  3. LLM retourne JSON :
     {
       "relevant_tables": ["formage_data"],
       "relevant_columns": ["four_3", "timestamp"],
       "filters": {"time_filter_hours": 72}
     }
  4. Validation Python (0 LLM) :
     → vérifie que colonnes existent en base
     → 3 tentatives max si hallucination
  5. Inscrit dans LangGraph State :
     state["target_column"] = "four_3"
     state["tables"] = ["formage_data"]

RETOURNE :
  {
    "tables": [...],
    "columns": [...],
    "filters": {...},
    "target_column": "...",
    "confidence": 0.95,
    "attempts": 1,
    "error": null
  }

FALLBACK :
  3 échecs → prompt simplifié → 3 échecs
  → stop + demande clarification utilisateur

---

## AGENT 2 — SQL Engine

| Champ | Valeur |
|-------|--------|
| Fichier | enterprise/agents/agent_2_sql.py |
| Modèle | qwen2.5-coder:7b |
| num_ctx | 4000 |
| num_predict | 300 |
| temperature | 0.0 |
| LLM | OUI — génération SQL uniquement |

REÇOIT :
  state["tables"], state["columns"],
  state["filters"], state["target_column"]

FAIT :
  1. LLM génère requête SQL TimescaleDB
  2. Validation sqlglot :
     → bloque INSERT/UPDATE/DELETE/
       DROP/ALTER/CREATE/TRUNCATE
  3. Nettoyage markdown (```sql```)
  4. Injection LIMIT 100 si absent
  5. Exécution sur user PostgreSQL READ-ONLY
     timeout 2000ms strict
  6. Retourne DataFrame pandas

RETOURNE :
  {
    "df": DataFrame,
    "sql": "SELECT ...",
    "row_count": 526,
    "execution_time_ms": 45,
    "error": null
  }

SÉCURITÉ ABSOLUE :
  Utilisateur PostgreSQL dédié read-only
  Timeout session 2000ms
  LIMIT 100 forcé par code Python
  sqlglot AST parser (pas regex)

---

## AGENT 3 — Nettoyeur

| Champ | Valeur |
|-------|--------|
| Fichier | enterprise/agents/agent_3_cleaner.py |
| Modèle | AUCUN (Python pur, 0ms overhead LLM) |
| LLM | NON |

REÇOIT :
  state["df"] : DataFrame brut
  state["target_column"] : colonne cible

ALGORITHMES (dans l'ordre) :

  1. FILTRE MÉDIAN (spikes isolés)
     fenêtre = 3 ou 5 points
     → élimine pics haute fréquence

  2. MAD Z-SCORE ROBUSTE
     MAD = médiane(|x_t - médiane_glissante|)
     z_t = 0.6745 × (x_t - médiane) / MAD
     seuil = 3.5

     1 point isolé |z| > 3.5
       → BRUIT CAPTEUR
       → remplacé par médiane locale dans df_propre

     ≥ 5 points consécutifs |z| > 3.5
       → ANOMALIE PROCESS
       → conservé dans df_anomalies_conservees
         avec colonne type_anomalie="process"

  3. DÉTECTION PLATEAUX
     même valeur décimale > 5 minutes
     → type_anomalie="capteur_bloque"
     → conservé dans df_anomalies_conservees

  4. RÈGLES PHYSIQUES
     température < -50°C ou > 250°C → bruit
     débit négatif → bruit
     valeur = NaN → bruit

RETOURNE :
  {
    "df_propre": DataFrame,
    "df_anomalies_conservees": DataFrame,
    "stats": {
      "total_points": 526,
      "bruit_capteur_count": 3,
      "anomalie_process_count": 12,
      "capteur_bloque_count": 0
    },
    "error": null
  }

RÈGLE D'OR : jamais supprimer → toujours annoter

---

## AGENT 4a — Méthodologue (intention)

| Champ | Valeur |
|-------|--------|
| Fichier | enterprise/agents/agent_4a_methodologist.py |
| Modèle | qwen2.5-coder:7b |
| num_ctx | 2000 |
| num_predict | 150 |
| temperature | 0.1 |
| LLM | OUI — intention JSON uniquement |

REÇOIT :
  question: str
  df_propre.columns: list

LLM RETOURNE UNIQUEMENT :
  {
    "goal": "detection_anomalies" |
            "comparaison_groupes" |
            "correlation" |
            "capabilite" |
            "tendance" |
            "cross_process" |
            "simulation" |
            "resume",
    "target_col": "four_3",
    "group_col": "modele" | null,
    "time_aware": true | false
  }

---

## AGENT 4b — Dispatcher

| Champ | Valeur |
|-------|--------|
| Fichier | enterprise/agents/agent_4b_dispatcher.py |
| Modèle | AUCUN (Python pur) |
| LLM | NON |

REÇOIT :
  state["intention"] : JSON de 4a
  state["df_propre"] : DataFrame

PRE-GATE (bloque si) :
  df.shape[0] < 5  → bloque ML lourd
  df.shape[0] < 30 → bloque ANOVA/PCA
  colonnes = 1     → bloque corrélation

ARBRE DE DÉCISION :

  goal=detection_anomalies
    → zscore + isolation_forest +
      changepoint + ewma_cusum

  goal=comparaison_groupes
    → Shapiro-Wilk sur résidus
    → p < 0.05 : kruskal_wallis
    → p ≥ 0.05 : Levene
      → variances égales : anova
      → inégales : anova_welch

  goal=correlation
    → pearson + spearman + mutual_info
    → si time_aware : + fourier

  goal=capabilite
    → cp_cpk + spc + distribution

  goal=tendance
    → mann_kendall + ewma_cusum

  goal=cross_process
    → lag_correlation + jointure temporelle

  goal=simulation
    → regression

  goal=resume
    → zscore + cp_cpk + spc + pivot

LANCE :
  results = await asyncio.gather(*tasks,
              return_exceptions=True)

---

## AGENTS SPÉCIALISTES MVP

Tous Python pur, 0 LLM.
Tous reçoivent : df + state["target_column"]
Tous retournent :
{
  "agent": "nom",
  "status": "success"|"error",
  "result": {...},
  "execution_time_ms": int
}

| Agent | Fichier | Librairie |
|-------|---------|-----------|
| zscore | specialists/zscore.py | scipy + numpy |
| isolation_forest | specialists/isolation_forest.py | sklearn |
| correlation | specialists/correlation.py | scipy + pandas |
| cp_cpk | specialists/cp_cpk.py | code maison |
| anova_kruskal | specialists/anova_kruskal.py | scipy.stats |
| ewma_cusum | specialists/ewma_cusum.py | code maison |
| spc | specialists/spc.py | code maison |
| regression | specialists/regression.py | statsmodels |
| spectral | specialists/spectral.py | scipy.fft |
| pivot | specialists/pivot.py | pandas |
| mann_kendall | specialists/mann_kendall.py | pymannkendall |
| pca | specialists/pca.py | sklearn |
| fourier | specialists/fourier.py | scipy.fft |
| changepoint | specialists/changepoint.py | ruptures |

---

## STATISTICIAN JUDGE

| Champ | Valeur |
|-------|--------|
| Fichier | enterprise/agents/statistician_judge.py |
| Modèle | AUCUN (Python pur) |
| Position | APRÈS les spécialistes |
| LLM | NON |

RÈGLES DE VALIDATION :
  données non-normales + ANOVA
    → invalide + warning + suggère Kruskal

  n < 30 + modèle ML lourd
    → invalide + warning "données insuffisantes"

  série non-stationnaire + ARIMA direct
    → invalide + force différenciation

  corrélation sur 2 variables identiques
    → invalide + warning "tautologie"

RETOURNE :
  résultats filtrés + warnings méthodologiques
  → Agents 5 et 6a utilisent UNIQUEMENT résultats valides

---

## AGENT 5 — Interpréteur OAPC

| Champ | Valeur |
|-------|--------|
| Fichier | enterprise/agents/agent_5_interpreter.py |
| Modèle | qwen2.5-coder:14b |
| num_ctx | 4096 |
| LLM | OUI — OBSERVER et ANALYSER uniquement |

### Structure OAPC

| Étape | Moteur | Rôle |
|-------|--------|------|
| **OBSERVER** | LLM | Une phrase factuelle (JSON compact uniquement) |
| **ANALYSER** | LLM | Une phrase de contexte (JSON compact uniquement) |
| **PRESCRIRE** | Python pur | Table `REGLES_PRESCRIRE` par goal + priorité |
| **CERTIFIER** | Python pur | Template fixe + hash SHA-256 du JSON compact |

### Profils utilisateur (`user_profile`)

`operateur` | `technicien` | `ingenieur` | `directeur` (défaut : `technicien`)

### Budgets tokens par profil

| Profil | num_predict | temperature |
|--------|-------------|-------------|
| operateur | 150 | 0.1 |
| technicien | 250 | 0.2 |
| ingenieur | 350 | 0.3 |
| directeur | 200 | 0.2 |

### Mots interdits par profil

- **operateur** : z-score, zscore, écart-type, variance, p-value, shapiro, anova, médiane, percentile
- **directeur** : z-score, zscore, écart-type, shapiro, anova
- **technicien / ingenieur** : aucune liste (jargon autorisé)

### Validation post-LLM

- **Souple sur la forme** : variantes `OBSERVER:` / `OBSERVER :` / casse mixte / deux-points optionnels
- **Stricte sur le fond** :
  - chiffres inventés rejetés (**tous les profils**, tolérance ±0,5)
  - mots interdits rejetés selon le profil
- **Fallback** : template déterministe après 3 échecs LLM

### Niveaux d'alerte (Python pur)

`P1` > `P2` > `P3` > `P4` — déterminés par `_determine_priority()` selon le `goal` et les `validated_results` (Cpk, % anomalies, dérive, etc.)

REÇOIT :
  `state["validated_results"]`, `state["intention"]`, `state["target_column"]`, `state["user_profile"]`

RETOURNE :
  ```python
  {
    "agent": "agent_5_interpreter",
    "status": "success"|"error",
    "rapport": {
      "observer": str,
      "analyser": str,
      "prescrire": str,
      "certifier": str,
      "priority": "P1"|"P2"|"P3"|"P4",
      "user_profile": str,
      "goal": str
    },
    "execution_time_ms": int,
    "error": null
  }
  ```

MET À JOUR LE STATE :
  `explanation`, `recommendation`, `anomaly_detected`, `confidence`, `rapport_oapc`, `priority`

RÈGLES : jamais de DataFrame ni données brutes capteurs dans le prompt LLM. JSON compact ≤ 7 clés.

---

## AGENT 6a — Interpréteur Générique

| Champ | Valeur |
|-------|--------|
| Rôle | Interpréter **un** résultat statistique en français, adapté au profil |
| Appels | **N fois** via LangGraph — une fois par spécialiste avec résultat valide |
| Modèle | qwen2.5-coder:14b |
| temperature | 0.1 |
| num_predict | 150 max |
| LLM | OUI — texte court uniquement |

### Règle absolue

Le LLM reçoit uniquement les **métriques clés** pré-sélectionnées par Python (3–4 clés max, jamais de données brutes). Python choisit les métriques selon le type de spécialiste.

### Métriques envoyées par spécialiste

| Spécialiste | Clés JSON (max 4) |
|-------------|-------------------|
| ZScoreSpecialist | `anomalies_count`, `max_zscore`, `pourcentage_anomalies`, `anomalie_process_count` |
| SpcSpecialist | `sous_controle`, `hors_limites_x_count`, `UCL_x`, `LCL_x` |
| EwmaCusumSpecialist | `derive_detectee`, `tendance_direction`, `ewma_alertes_count` |
| CpCpkSpecialist | `Cpk`, `Cp`, `conforme_EN9100`, `interpretation_Cpk` |
| CorrelationSpecialist | `n_correlations_significatives`, `correlation_max_colonne`, `correlation_max_r` |
| RegressionSpecialist | `meilleure_variable`, `r_squared`, `interpretation` |
| MannKendallSpecialist | `tendance`, `p_value`, `sen_slope` |
| AnovaKruskalSpecialist | `methode_choisie`, `significatif`, `interpretation` |
| PivotSpecialist | `global_mean`, `global_std`, `global_min`, `global_max` |
| FourierSpecialist | `signal_periodique`, `frequence_dominante`, `interpretation` |

### Sortie

- Texte **1–3 phrases** en français, adapté à `user_profile`
- Jamais de chiffre inventé
- Validation post-génération Python
- Fallback template après 3 échecs

MET À JOUR LE STATE : `state["interpretations"][nom_specialiste] = texte`

---

## AGENT 6b — Synthèse Globale

| Champ | Valeur |
|-------|--------|
| Rôle | Synthétiser les interprétations en **résumé exécutif** |
| Appels | **1 seule fois**, après tous les 6a |
| Modèle | qwen2.5-coder:14b |
| temperature | 0.1 |
| num_predict | 250 max |
| LLM | OUI — résumé exécutif uniquement |

### JSON entrant (compact, ≤ 4 clés)

`priority`, `goal`, `target_column`, `n_specialistes`, `n_anomalies_total` (agrégats Python — **jamais** les textes bruts des 6a, pour limiter le contexte).

### Sortie

- Résumé exécutif **3–5 phrases**, adapté au `user_profile`
- Validation post-génération Python
- Fallback template après 3 échecs

MET À JOUR LE STATE : `state["resume_executif"]`

---

## AGENT 6c — Constructeur PDF

| Champ | Valeur |
|-------|--------|
| Fichier | `enterprise/agents/report_agent.py` (refactor cible) |
| Librairies | ReportLab + Plotly |
| LLM | **NON** — 100 % Python pur |

Assemble le PDF à partir des sorties Agent 5 (`rapport_oapc`), 6a (`interpretations`), 6b (`resume_executif`) et des `validated_results`.

### Structure du PDF (7 sections logiques)

**Page de garde** : logo IndustrIA, titre, date/heure, badge priorité P1–P4, question, profil.

**Section 1 — Résumé exécutif** : texte Agent 6b ; verdict OAPC en 4 blocs colorés (OBSERVER, ANALYSER, PRESCRIRE, CERTIFIER depuis Agent 5).

**Section 2 — Graphique principal** : série temporelle cible, moyenne mobile (fenêtre 10), bandes ±2σ (vert) et ±3σ (rouge), anomalies en croix rouges ; axe Y : `nom_capteur (unité)` ou `(valeur brute)` si unité inconnue.

**Section 3 — Interprétations** : un bloc par spécialiste ; texte 6a + tableau métriques compact ; visibilité selon profil :
- **operateur** → verdict final seulement
- **technicien** → métriques essentielles
- **ingenieur** → tout
- **directeur** → verdict + impact

**Section 4 — Causes probables** : tableau Python (Cause / Probabilité / Agent), note « Probabilités indépendantes, ne somment pas à 100 % », max 5 causes triées.

**Section 5 — Recommandation** : PRESCRIRE (Agent 5) en grand ; délais :
- P1 → arrêt immédiat
- P2 → < 30 minutes
- P3 → < 4 heures
- P4 → prochaine maintenance

Responsable selon profil + priorité :
- P1 → toujours chef d'atelier
- P2 + technicien → technicien maintenance
- P2 + ingenieur → ingénieur process
- directeur → directeur production

**Section 6 — Annexe technique** (selon profil) :
- **ingenieur** → complète (tous agents)
- **technicien** → simplifiée (`anomalies_count`, `max_zscore`, `sous_controle`)
- **operateur** / **directeur** → absente

**Section 7 — Traçabilité EN9100** : version IndustrIA, horodatage milliseconde, question, cible, priorité, profil, agents appelés, n spécialistes, n warnings judge ; SHA-256 de `question` + `json_compact` + `rapport_oapc` + `timestamp` ; double signature (opérateur terrain / responsable qualité).

### Règles PDF

- Pas de page vide, pas de `Spacer` inutile
- Contenu dense et professionnel
- Sections masquées selon `user_profile`

MET À JOUR LE STATE : `state["pdf_path"]`

---

## MONITORING PLANIFIÉ

- Tâche **cron toutes les heures**
- **Python pur** — z-score glissant sur l'heure écoulée (TimescaleDB)
- Si z-score > 3 :
  - déclenche le pipeline LangGraph complet
  - génère rapport OAPC automatique
  - alimente table **alertes non acquittées**
  - niveaux P1/P2/P3/P4 automatiques
  - escalade si P1 non acquitté sous **5 min**
  - persistance TimescaleDB **immuable**

---

## ACQUITTEMENT ALERTES

- Bouton **Acquitter** (Streamlit)
- Enregistre : nom opérateur, timestamp **milliseconde**, commentaire obligatoire, action corrective
- Persistance TimescaleDB
- Hash SHA-256 de l'acquittement
- Conformité EN9100

---

## PERSISTANCE HISTORIQUE

Table **`analyses_history`** (TimescaleDB) :

| Colonne | Type |
|---------|------|
| id | BIGSERIAL PRIMARY KEY |
| user_id | TEXT NOT NULL |
| question | TEXT |
| profil | TEXT |
| json_compact | JSONB |
| rapport_oapc | TEXT |
| priority | TEXT (P1/P2/P3/P4) |
| timestamp | TIMESTAMPTZ DEFAULT NOW() |
| hash | TEXT UNIQUE |
| acquitted | BOOLEAN DEFAULT FALSE |
| acquitted_by | TEXT |
| acquitted_at | TIMESTAMPTZ |
| acquitted_comment | TEXT |

- Ne jamais stocker les **données brutes capteurs**
- Cache **SQLite** pour le mode dégradé

---

## FILE D'ATTENTE OLLAMA

- Lock Python **FIFO**
- **1 seul** appel LLM à la fois
- Indicateur de position dans la file
- Protection CUDA Out of Memory
- Timeout **30 secondes**

---

## MODE DÉGRADÉ

Si Ollama indisponible :

- message clair à l'utilisateur
- dernier état connu affiché
- cache SQLite des dernières analyses
- alertes calculées en Python pur restent actives

---

## INTERFACE STREAMLIT

- Sélecteur profil (4 niveaux)
- Chat question/réponse + historique
- Centre alertes + acquittement (nom + timestamp + commentaire)
- Export PDF/CSV
- File d'attente Ollama visible
- Mode dégradé géré
- **Responsive mobile**

---

## KPIs DASHBOARD

Tous calculés en **Python pur** via TimescaleDB. **JAMAIS** par le LLM.

**Production** : OEE/TRS = Disponibilité × Performance × Qualité ; MTBF, MTTR, scrap rate

**Qualité** : Cp/Cpk, First Pass Yield, PPM, taux conformité

**Maintenance** : santé machine, dérive capteur

**Énergie** : kWh/lot, rendement thermique

---

## SCRIPT BACKTEST (Sprint 5.5)

- Rejouer données CSV historiques
- Simuler monitoring sur données passées
- Prouver détection **avant panne**
- Calculer ROI évité (coût arrêt × heures)
- Argument de vente terrain

---

## SPRINT 6 (futur)

- Monitoring temps réel WebSocket **< 10 s**
- VRAM Watchdog CUDA
- Mode Investigation (plage temporelle)
- Mode Comparaison A/B
- Shift Handover fin de poste
- Cache sémantique pgvector **< 100 ms**
- Dashboard TV atelier (feux tricolores)

---

## ARGUMENT COMMERCIAL

> 5000–10000 €/mois de cloud viole l'ITAR.  
> IndustrIA tourne sur PC à 400 €.  
> 100 % local. Auditable EN9100.  
> Preuve sur données historiques : détection panne **48 h avant**.

---

## CONFIGURATION OLLAMA

```bash
OLLAMA_KEEP_ALIVE=-1
OLLAMA_NUM_PARALLEL=1   # file FIFO applicative en plus

# Par agent :
agent_1 : num_ctx=8000 num_predict=150 temp=0.1
agent_2 : num_ctx=4000 num_predict=300 temp=0.0
agent_4a: num_ctx=2000 num_predict=150 temp=0.1
agent_5 : num_ctx=4096  num_predict=150-350 selon profil  temp=0.1-0.3  model=14b
agent_6a: num_ctx=4096  num_predict=150  temp=0.1  model=14b  (×N spécialistes)
agent_6b: num_ctx=4096  num_predict=250  temp=0.1  model=14b  (×1 synthèse)
agent_6c: aucun LLM
```

---

## SÉCURITÉ SQL

```
Utilisateur PostgreSQL dédié read-only
Timeout session : 2000ms
LIMIT 100 forcé par code Python
sqlglot AST : bloque INSERT/UPDATE/
              DELETE/DROP/ALTER/CREATE/TRUNCATE
```

---

## GESTION ERREURS

```python
# Pattern tenacity sur tous les agents LLM
@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(min=1, max=10))
def appel_ollama():
    ...

# Log des échecs
failed_agents.jsonl
```

---

## ÉTAT LANGGRAPH (state/schema.py)

```python
class AgentState(TypedDict):
    question: str
    user_profile: str          # operateur|technicien|ingenieur|directeur
    tables: list[str]
    columns: list[str]
    target_column: str
    filters: dict
    df_raw: Any
    df_propre: Any
    df_anomalies: Any
    cleaning_stats: dict
    intention: dict
    specialist_tasks: list[dict]
    specialist_results: list[dict]
    validated_results: list[dict]
    judge_warnings: list[str]
    explanation: str
    recommendation: str
    rapport_oapc: dict
    priority: str              # P1|P2|P3|P4
    anomaly_detected: bool
    confidence: str
    interpretations: dict      # nom spécialiste -> texte Agent 6a
    resume_executif: str        # texte Agent 6b
    pdf_path: str
    analyses_history: list[dict]
    errors: list[str]
    warnings: list[str]
    pipeline_start_time: float
    agents_called: list[str]
```

---

## SPRINTS

```
Sprint 1 ✅ DONE (prototype)
Sprint 2 ✅ agent_1, agent_2, agent_3
Sprint 3 ✅ spécialistes MVP
Sprint 4 ✅ agent_4a, agent_4b, judge, LangGraph
Sprint 5 → agent_5 OAPC, agents 6a/6b/6c (rapport),
           Streamlit, monitoring cron, acquittement,
           historique, file Ollama, mode dégradé, KPIs
Sprint 5.5 → script backtest CSV / ROI
Sprint 6 → WebSocket, pgvector, dashboard TV, …
```

---

## LICENCE

```
core/        Apache 2.0 (open source)
enterprise/  BSL 1.1 (commercial)
```

---

*IndustrIA — moteur d'investigation statistique
industrielle assisté par IA locale souveraine*
*Version 2.1 — validé par 4 LLMs*
