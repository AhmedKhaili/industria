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
AGENT 5 — Interprète OAPC
        ↓
AGENT 6 — Report PDF (ReportLab + Plotly)
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
  → Agent 5 utilise UNIQUEMENT résultats valides

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

## AGENT 6 — Report PDF (ReportLab + Plotly)

| Champ | Valeur |
|-------|--------|
| Fichier | enterprise/agents/report_agent.py (Sprint 5) |
| Librairies | ReportLab + Plotly |
| LLM | OUI — Section 1 uniquement |

### Sections du PDF

1. **Résumé exécutif** — LLM (adapté au `user_profile`)
2. **Graphique principal annoté** — Plotly (Python pur)
3. **Causes probables** — Python pur
4. **Recommandation + délai** — Python pur (depuis PRESCRIRE Agent 5)
5. **Annexe technique** — Python pur (métriques, méthodes, warnings judge)
6. **Traçabilité EN9100** — horodatage + version IndustrIA + SHA-256 + emplacement double signature

Export PDF horodaté, signable, adapté au profil utilisateur.

---

## MONITORING PLANIFIÉ (Sprint 5)

- Tâche **cron toutes les heures**
- Calcul **z-score glissant Python pur** sur la dernière heure TimescaleDB
- Si z-score > 3 → déclenche le **pipeline LangGraph complet** automatiquement
- Génère un **rapport OAPC** automatique
- Alimente une table **alertes non acquittées**
- Niveaux **P1 / P2 / P3 / P4** automatiques
- **Escalade** : si P1 non acquitté sous 5 min → notification responsable
- **Persistance TimescaleDB immuable**

---

## ACQUITTEMENT ALERTES (Sprint 5)

- Bouton **Acquitter** sur l'interface Streamlit
- Enregistre : nom opérateur, timestamp au millième de seconde, commentaire obligatoire, action corrective
- Persistance TimescaleDB
- Hash **SHA-256** de l'acquittement
- Conformité **EN9100** obligatoire

---

## PERSISTANCE HISTORIQUE (Sprint 5)

Table **`analyses_history`** (TimescaleDB) :

`id`, `user_id`, `question`, `profil`, `json_compact`, `rapport_oapc`, `priority`, `timestamp`, `hash`

- Ne jamais stocker les **données brutes capteurs**
- Cache **SQLite** pour le mode dégradé

---

## FILE D'ATTENTE OLLAMA (Sprint 5)

- **Lock Python FIFO**
- **1 seul appel LLM** à la fois
- Indicateur de position dans la file
- Protection **CUDA Out of Memory**
- Timeout utilisateur si attente **> 30 secondes**

---

## MODE DÉGRADÉ (Sprint 5)

Si Ollama indisponible :

- Message clair à l'utilisateur
- Affichage du **dernier état connu**
- Cache SQLite des dernières analyses
- Alertes calculées en **Python pur** restent actives

---

## INTERFACE STREAMLIT (Sprint 5)

- Sélecteur de profil (4 niveaux)
- Chat question / réponse avec historique
- Centre d'alertes avec acquittement
- Export PDF / CSV
- File d'attente Ollama visible
- Mode dégradé géré proprement
- **Responsive mobile**

---

## KPIs DASHBOARD (Sprint 5)

Calculés en **Python pur** via TimescaleDB — **jamais par le LLM** :

**Production** : OEE/TRS (Disponibilité × Performance × Qualité), taux disponibilité, performance, qualité, MTBF, MTTR, scrap rate

**Qualité** : Cp/Cpk, First Pass Yield, PPM, taux conformité

**Maintenance** : santé machine, dérive capteur

**Énergie** : kWh/lot, rendement thermique

---

## SCRIPT BACKTEST (Sprint 5.5)

- Rejouer des **CSV historiques**
- Simuler le monitoring sur données passées
- Prouver la détection d'anomalie **avant panne**
- Calculer le **ROI évité** (coût arrêt × heures)
- Argument de vente terrain

---

## SPRINT 6 (futur)

- Monitoring temps réel WebSocket (< 10 s)
- VRAM Watchdog CUDA
- Mode Investigation (plage temporelle)
- Mode Comparaison A/B
- Shift Handover automatique fin de poste
- Cache sémantique pgvector (< 100 ms)
- Dashboard TV atelier (feux tricolores)

---

## ARGUMENT COMMERCIAL

> 5000–10000 €/mois de cloud qui viole l'ITAR  
> vs IndustrIA sur PC à 400 €.  
> 100 % local. Auditable EN9100.  
> On prouve sur vos données historiques qu'on aurait détecté votre dernière panne 48 h avant.

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
agent_6 : num_ctx=4000  num_predict=200-300 Section 1   temp=0.2
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
Sprint 5 → agent_5 OAPC, agent_6 PDF, Streamlit,
           monitoring cron, acquittement, historique,
           file Ollama, mode dégradé, KPIs dashboard
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
