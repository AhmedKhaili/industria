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
AGENT 5 — Interprète
        ↓
REPORT AGENT → PDF + Streamlit
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

## AGENT 5 — Interprète

| Champ | Valeur |
|-------|--------|
| Fichier | enterprise/agents/agent_5_interpreter.py |
| Modèle | qwen2.5-coder:7b |
| num_ctx | 4000 |
| num_predict | 400 |
| temperature | 0.3 |
| LLM | OUI — explication FR uniquement |

RÈGLES DUR-CODÉES (injectées dans le prompt) :
  z > 3.0     → anomalie significative
  Cp < 1.33   → process non capable
  Cpk < 1.0   → process hors contrôle
  p < 0.05    → statistiquement significatif
  MAD > 3.5   → bruit capteur probable
  R² > 0.8    → corrélation forte

RETOURNE :
  {
    "explication": "texte FR technicien",
    "recommandation": "action concrète",
    "anomaly_detected": true|false,
    "confidence": "haute|moyenne|faible",
    "error": null
  }

---

## REPORT AGENT

| Fichier | enterprise/agents/report_agent.py |
| Librairies | ReportLab + Plotly |
| LLM | NON |

CONTENU PDF :
  - Question posée
  - Méthodes utilisées
  - Graphes Plotly exportés
  - Tableaux de résultats
  - Explication Agent 5
  - Recommandation
  - Horodatage + référence EN9100

---

## CONFIGURATION OLLAMA

```bash
OLLAMA_KEEP_ALIVE=-1
OLLAMA_NUM_PARALLEL=1

# Par agent :
agent_1 : num_ctx=8000 num_predict=150 temp=0.1
agent_2 : num_ctx=4000 num_predict=300 temp=0.0
agent_4a: num_ctx=2000 num_predict=150 temp=0.1
agent_5 : num_ctx=4000 num_predict=400 temp=0.3
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
    tables: list[str]
    columns: list[str]
    target_column: str
    filters: dict
    df_raw: Any
    df_propre: Any
    df_anomalies: Any
    intention: dict
    specialist_results: list[dict]
    validated_results: list[dict]
    explanation: str
    recommendation: str
    pdf_path: str
    errors: list[str]
    warnings: list[str]
```

---

## SPRINTS

```
Sprint 1 ✅ DONE (prototype)
Sprint 2 → agent_1, agent_2, agent_3
Sprint 3 → tous les spécialistes MVP
Sprint 4 → agent_4a, agent_4b, judge,
           LangGraph complet
Sprint 5 → agent_5, report, streamlit
Sprint 6 → cache pgvector, monitoring,
           tests unitaires
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
