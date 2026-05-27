# AGENTS.md — Référence historique v3.0

> ⚠️ Ce fichier décrit l'architecture v3.0.
> Les assets réutilisables (specialists/, enterprise/report/,
> enterprise/rag/) restent valides.
> Pour l'architecture cible v4.0 → voir docs/VISION.md
> Pour la spec de chaque système → voir docs/S1.md, docs/S2.md, etc.
> La numérotation "Agent 1, Agent 2..." ci-dessous
> correspond à la v3.0. Dans systems/s1/, les agents
> portent des noms explicites (agent_1_preprocessor, etc.)
> et n'ont AUCUN lien avec les numéros v3.0.

# IndustrIA — AGENTS.md
# Architecture complète v3.0
# Référence technique v3.0

---

## PRINCIPE FONDAMENTAL (non négociable)

LLM = parser sémantique JSON uniquement
Python = tous les calculs
LLM ne calcule JAMAIS
LLM ne choisit JAMAIS une méthode statistique
LLM n'exécute JAMAIS de code
Jamais de données brutes au LLM

---

## PIPELINE COMPLET

COUCHE 0 — DONNÉES & CONFIGURATION

data/
├── config.py
│   → MACHINE_CONFIG (coûts horaires, unités, seuils LSL/USL)
│   → GOLDEN_BATCH_IDS
│   → FINANCIAL_PARAMS (cout_horaire_defaut=500)
├── manuals/
│   → PDFs manuels de maintenance
│   → fiches techniques capteurs
│   → procédures EN9100
└── schemas/
    → migrations TimescaleDB

core/database/
→ TimescaleDB connexion
→ postgres_readonly user (sandbox SQL)
→ hypertables capteurs
→ tables : analyses_history, alerts, acquittements
→ OLLAMA_KEEP_ALIVE=-1

LICENCES :
→ core/ Apache 2.0 (open source)
→ enterprise/ BSL 1.1 (commercial)

---

COUCHE 1 — PIPELINE QUESTION/RÉPONSE

QUESTION UTILISATEUR (langage naturel)
            ↓
AGENT 1 — Analyste Sémantique
  Modèle : qwen2.5-coder:7b
  → comprend la question
  → identifie tables + colonnes
  → extrait filtres temporels
  → JSON : tables, columns, target_column, filters
  → keyword matching tables pertinentes
  → pgvector en Sprint 6
            ↓
AGENT 2 — SQL Engine
  Modèle : qwen2.5-coder:7b
  → génère SQL depuis JSON
  → validation sqlglot
  → sandbox postgres_readonly
  → LIMIT 100 forcé
  → timeout SQL 1000ms max
  → blocage : UNION, UNION ALL, FULL OUTER JOIN,
              DROP, INSERT, DELETE
  → post-traitement TIME_BUCKET('hour' → time_bucket('1 hour'
  → fallback SELECT * si 3 échecs
  → si target_column absente du df_raw →
    recalage sur première colonne numérique
            ↓
AGENT 3 — Nettoyeur (Python pur)
  → filtre médian (window=3)
  → MAD z-score robuste (window=20)
  → détection plateaux
  → règles physiques (limites génériques ±1e6)
  → classification :
    normal / bruit_capteur / anomalie_process / capteur_bloqué
  → supprime colonnes booléennes
  → df_propre + df_anomalies
            ↓
AGENT 4a — Méthodologue (qwen2.5-coder:7b)
  → classifie intention en 8 goals :
    detection_anomalies, comparaison_groupes,
    correlation, capabilite, tendance,
    cross_process, simulation, resume
  → JSON : goal, target_col, group_col, time_aware
  → fallback "resume" si échec
            ↓
AGENT 4b — Dispatcher (Python pur)
  → mapping goal → spécialistes (dur-codé) :
    detection_anomalies → zscore, ewma_cusum, spc
    comparaison_groupes → anova_kruskal, pivot
    correlation         → correlation, fourier(si time_aware)
    capabilite          → cp_cpk, spc, pivot
    tendance            → mann_kendall, ewma_cusum, regression
    cross_process       → correlation, zscore, pivot
    simulation          → regression, pivot
    resume              → zscore, cp_cpk, spc, pivot
  → pre-gate :
    df < 5          → bloque tout
    df < 30         → retire cp_cpk ET anova_kruskal
    colonnes < 2    → retire correlation
    1 seul groupe   → retire anova_kruskal
  → asyncio.gather() parallèle (asyncio.to_thread)
            ↓
11 AGENTS SPÉCIALISTES (Python pur)
  ZScoreSpecialist    → anomalies MAD z-score
  CpCpkSpecialist     → capabilité EN9100
  CorrelationSpecialist → liens variables
  AnovaKruskalSpecialist → comparaison groupes
  EwmaCusumSpecialist → dérives progressives
  SpcSpecialist       → cartes Shewhart
  RegressionSpecialist → influence variables
  PivotSpecialist     → agrégations
  FourierSpecialist   → périodicités FFT
  MannKendallSpecialist → tendances non-param.
  (+ matrix_profile en Sprint 6)
            ↓
STATISTICIAN JUDGE (Python pur)
  → 6 règles validation statistique :
    1. ANOVA non normal → invalide
    2. Cpk non normal → warning
    3. n<30 → invalide ML lourd
    4. Contradictions zscore/spc :
       ZScore anomalie > 0 ET SPC sous_controle = True → contradiction
       ZScore anomalie > 0 ET SPC sous_controle = False → cohérent ✅
    5. Corrélation sur peu de points → warning
    6. Régression singulière → warning
  → judge_valid par résultat
            ↓
    ┌──────────────┴──────────────┐
    ↓                              ↓
MODE CHAT (< 30 sec)        MODE RAPPORT (15-20 min)

---

COUCHE 2A — MODE CHAT (réponse rapide)

AGENT 5 — Interpréteur OAPC
  Modèle : qwen2.5-coder:14b
  temperature=0.1, num_ctx=4096

  Python calcule :
  → priorité P1/P2/P3/P4 (règles déterministes)
    P1 : Cpk < 0.67 ou anomalies > 20%
    P2 : anomalies > 10% ou dérive significative
    P3 : anomalies > 5%
    P4 : dérive Mann-Kendall p < 0.05
  → PRESCRIRE (table de règles métier par goal+priorité)
  → CERTIFIER (template fixe + hash SHA-256)
    "IndustrIA v2.1 | cible | priorité | hash[:16] | timestamp"

  LLM génère UNIQUEMENT :
  → OBSERVER (faits en français)
  → ANALYSER (contexte + méthode)

  JSON compact envoyé au LLM (max 7 clés) :
  → goal, target_column, anomalies_count,
    pourcentage_anomalies, max_zscore,
    derive_detectee, n

  Profils + budgets tokens :
  → operateur  : 150 tokens, temp=0.1
    mots interdits : z-score, zscore, écart-type,
    variance, p-value, shapiro, anova, médiane,
    percentile, sigma, UCL, LCL, Cpk, EWMA, CUSUM
  → technicien : 250 tokens, temp=0.2
    mots interdits : (aucun)
  → ingenieur  : 350 tokens, temp=0.3
    mots interdits : (aucun)
  → directeur  : 200 tokens, temp=0.2
    mots interdits : z-score, zscore, UCL, LCL,
    Shapiro, ANOVA, p-value, EWMA, CUSUM

  Validation post-LLM Python :
  → 4 sections OAPC présentes (souple sur forme)
  → aucun chiffre inventé (tous profils, ±0.5)
    whitelist : chiffres dans target_column
  → mots interdits selon profil
  → fallback template après 3 échecs
  → JAMAIS de crash visible utilisateur

  Réponse chat → persistance TimescaleDB

---

COUCHE 2B — MODE RAPPORT PDF PREMIUM

FONDATION COMMUNE (importée par tous les agents rapport) :

enterprise/report/styles.py (à créer)
  → tous les styles ReportLab
  → couleurs industrielles :
    P1=#DC2626, P2=#EA580C, P3=#CA8A04, P4=#16A34A
    header=#1E3A5F, light_blue=#EBF4FF
  → templates tableaux
  → polices, tailles, marges

enterprise/report/charts.py (à créer)
  → thème Plotly industriel cohérent
  → build_timeseries(df, target, anomalies)
    ±2σ vert transparent, ±3σ rouge transparent
    anomalies en croix rouges
    axe Y : f"{target} (unité)"
  → build_gauge(value, title, min, max, seuils)
  → build_heatmap(corr_matrix)
  → build_waterfall(categories, values)
  → build_bar_horizontal(causes, scores)
  → build_boxplot(df, groups)
  → export PNG 1200×400px via kaleido

enterprise/report/formatters.py (à créer)
  → format_value(v) → jamais None → "N/A"
  → format_dict(d) → jamais dict brut
    {direction: "hausse", slope: 0.1} → "hausse (pente=0.10)"
  → format_list(l) → "3 éléments" pas la liste
  → format_number(n, decimals=2, unit="") → "4.70 A"
  → format_timestamp(ts) → "18/05/2026 22:44:49"
  → format_bool(b) → "Oui"/"Non"

---

AGENTS CALCUL PYTHON PUR (à créer) :

agent_kpis.py
  → requêtes TimescaleDB Python pur
  → OEE/TRS = Disponibilité × Performance × Qualité
  → MTBF = temps_total / nb_pannes
  → MTTR = temps_cumul_reparation / nb_interventions
  → First Pass Yield = pièces_conformes / total
  → Scrap Rate = pièces_rejetées / total
  → jauges Plotly (go.Indicator)
  → JAMAIS via LLM

agent_tendance.py
  → Mann-Kendall sur 30 derniers jours (pymannkendall)
  → comparaison semaine précédente
  → test Mann-Whitney (p < 0.05 → significatif)
  → évolution % des indicateurs
  → graphique tendance + droite de Sen (Plotly)
  → JAMAIS via LLM

agent_heatmap.py
  → matrice corrélations Pearson/Spearman
  → entre tous les capteurs disponibles
  → heatmap Plotly gradient rouge/bleu
  → JAMAIS via LLM

agent_financier.py
  → coût horaire depuis data/config.py
  → durée avant panne = (seuil - valeur) / pente_derive
  → coût rebuts = nb_pieces_defaut × cout_rebut_piece
  → économie = coût_évité - coût_intervention
  → waterfall chart Plotly
  → JAMAIS via LLM

agent_causes.py
  → scores normalisés /100 (indépendants)
  → max 5 causes triées par score décroissant
  → règles Python pur :
    ZScore anomalie_process > 0 → "Anomalie process"
    ZScore bruit > 0 → "Bruit capteur"
    SPC sous_controle=False → "Hors contrôle SPC" score=75
    EWMA derive=True → "Dérive EWMA/CUSUM" score=70
    CpCpk Cpk < 1.33 → "Capabilité insuffisante" score=80
    Regression r2 > 0.5 → "Corrélation avec {var}" score=r2*100
  → barres horizontales Plotly
  → NOTE obligatoire : "Scores indépendants par méthode.
    Ne se somment pas."

enterprise/rag/context_agent.py (à créer)
  → ChromaDB local
  → embeddings depuis data/manuals/ PDFs
  → similarité cosinus Python pur
  → extrait page exacte du manuel de maintenance
  → retourne : {fichier, page, texte_extrait}
  → JAMAIS le LLM ne cherche dans les docs

---

AGENTS LLM RAPPORT (texte uniquement) :

agent_6a_interpreter.py (existant)
  Modèle : qwen2.5-coder:14b
  → appelé N fois (1 par spécialiste)
  → JSON compact 3-4 clés max par spécialiste :
    ZScore → anomalies_count, max_zscore,
              pourcentage_anomalies, anomalie_process_count
    SPC    → sous_controle, hors_limites_x_count, UCL_x, LCL_x
    EWMA   → derive_detectee, tendance_direction, ewma_alertes_count
    CpCpk  → Cpk, Cp, conforme_EN9100
    Corr   → n_correlations_sig, correlation_max
    Regr   → meilleure_variable, r_squared
    MK     → tendance, p_value, sen_slope
    ANOVA  → methode_choisie, significatif, interpretation
    Pivot  → global_mean, global_std
    Fourier → signal_periodique, frequence_dominante
  → 1-3 phrases par profil
  → validation post-LLM (chiffres, mots interdits)
  → fallback template après 3 échecs

agent_6b_synthesis.py (existant)
  Modèle : qwen2.5-coder:14b
  → appelé UNE SEULE FOIS après tous les 6a
  → JSON compact 4 clés max :
    {priority, goal, target_column, n_specialistes}
  → JAMAIS les textes bruts des 6a en entrée
  → résumé exécutif 3-5 phrases adapté profil
  → validation post-LLM
  → fallback template après 3 échecs

agent_6b_tendance.py (à créer)
  Modèle : qwen2.5-coder:14b
  → appelé si tendance disponible
  → JSON 3 clés : {tendance_direction, p_value, comparaison_semaine}
  → 1 phrase de synthèse tendance
  → optionnel si agent_tendance a tourné

agent_6b_reco.py (à créer)
  Modèle : qwen2.5-coder:14b
  → reformulation recommandation RAG
  → JSON 4 clés : {action, delai, manuel, page}
  → cite explicitement fichier + page
  → JAMAIS inventer une procédure absente du RAG
  → Si RAG vide → "Aucune procédure locale trouvée.
    Contacter l'ingénieur procédé."

---

ASSEMBLEUR PDF : agent_6c_pdf.py (à refaire)
  100% Python pur — AUCUN appel LLM
  Utilise styles.py, charts.py, formatters.py

  12 SECTIONS :

  S1  — Page de garde
        → Logo "IndustrIA" 28pt
        → Titre "Rapport d'Analyse Industrielle"
        → Badge priorité coloré P1/P2/P3/P4
        → Verdict binaire :
          P1 → fond rouge "🚫 ARRÊT PRODUCTION REQUIS"
          P2 → fond orange "⚠ PRODUCTION AUTORISÉE
               avec surveillance. Intervention < 30 min"
          P3 → fond jaune "✓ PRODUCTION AUTORISÉE - Surveiller"
          P4 → fond vert "✓ PRODUCTION NORMALE"
        → Date/heure, question posée, capteur, profil
        → Contexte production :
          N° lot, opérateur, recette active
          (depuis state.get(), N/A si absent)
        → Badge confiance HAUTE/MOYENNE/FAIBLE

  S2  — Résumé exécutif
        → Texte Agent 6b
        → 4 blocs OAPC côte à côte colorés
        → Badge confiance

  S3  — Dashboard KPIs
        → OEE/TRS, Cp/Cpk, MTBF, MTTR
        → jauges Plotly (go.Indicator)
        → Calculés Python pur TimescaleDB
        → JAMAIS via LLM

  S4  — Graphique principal
        → Série temporelle capteur cible
        → Moyenne mobile fenêtre 10
        → ±2σ VERT transparent
        → ±3σ ROUGE transparent
        → Anomalies croix rouges
        → Axe Y : f"{target_column} (valeur brute)"
        → Top 3 anomalies avec timestamp
        → Taille 1200×400px

  S5  — Tendance vs historique
        → Résultats agent_tendance
        → Comparaison semaine précédente
        → Évolution % indicateurs
        → Phrase Agent 6b_tendance (optionnel)

  S6  — Interprétations par méthode
        → 1 bloc par spécialiste
        → Texte Agent 6a
        → Métriques formatées (jamais dict brut)
        → Badge judge_valid ✓ ou ✗
        → Adapté profil :
          operateur → verdict seulement
          technicien → métriques essentielles (max 3)
          ingenieur → toutes métriques
          directeur → verdict + impact

  S7  — Causes probables
        → Tableau Python pur
        → Colonnes : Cause / Indice (/100) / Agent
        → Barres colorées proportionnelles
        → NOTE : "Scores indépendants par méthode.
          Ne se somment pas."
        → Max 5 causes

  S8  — Heatmap corrélations
        → Matrice Plotly
        → Capteurs liés identifiés

  S9  — Impact financier
        → Waterfall chart Plotly
        → Coût estimé si non traité
        → Économie réalisée
        → NOTE : "Estimation indicative.
          Adapter au coût réel de l'usine."

  S10 — Recommandations + RAG
        → 3 actions max priorisées
        → Délai + responsable
        → Référence manuelle + page exacte
        → Texte Agent 6b_reco

  S11 — Annexe technique
        → ingénieur : complète (tous agents)
        → technicien : simplifiée (3 métriques max)
        → operateur : ABSENTE
        → directeur : ABSENTE

  S12 — Traçabilité EN9100
        → Version IndustrIA v2.1
        → Horodatage milliseconde
        → Question + cible + priorité + profil
        → Liste agents appelés
        → N spécialistes + N warnings
        → SHA-256 de :
          question + json_compact + rapport_oapc + timestamp
        → Double signature ReportLab propre :
          Zone 1 — Opérateur terrain
            Nom : ____________
            Date : ___________
            Signature : ______
          Zone 2 — Responsable qualité
            Nom : ____________
            Date : ___________
            Signature : ______
        → Mention : "Document non modifiable
          après signature — conservation 10 ans"

  RÈGLES PDF ABSOLUES :
  → Jamais de page vide
  → Jamais de dict Python brut affiché
  → Jamais de None visible → "N/A"
  → Jamais de liste Python brute → "N éléments"
  → Unités toujours précisées sur les axes
  → En-tête/pied de page sur chaque page :
    gauche : "IndustrIA v2.1"
    droite : date + heure
    pied centre : "Page X / Y"
    pied droite : SHA-256 (8 premiers chars)
  → Marges : 1.5cm partout
  → PageBreak uniquement si nécessaire
  → Couleurs : vert=OK, orange=surveillance, rouge=critique
  → Probabilités/scores : toujours "indices /100"
    JAMAIS présentés comme probabilités classiques
  → Texte des judge_warnings : JAMAIS affiché dans le PDF
    (compteur N warnings autorisé en traçabilité uniquement)

---

COUCHE 3 — MONITORING

monitoring/cron_monitor.py
  → orchestre tout
  → tâche cron toutes les heures
  → déclenche si z-score > 3

monitoring/agent_zscore_monitor.py (Python pur)
  → z-score glissant sur TimescaleDB
  → calcul déterministe sans LLM
  → si z-score > 3 → déclenche pipeline LangGraph complet
  → génère rapport OAPC automatique

monitoring/agent_alert_manager.py (Python pur)
  → crée alertes P1/P2/P3/P4
  → niveaux automatiques :
    P1 : z-score > 7 ou Cpk < 0.67
    P2 : z-score > 5 ou anomalies > 3 consécutives
    P3 : z-score > 3 isolé
    P4 : dérive Mann-Kendall confirmée
  → escalade P1 non acquitté sous 5min
    → notification responsable
  → persistance immuable TimescaleDB

Sprint 6 futur :
  → agent_notifier → WebSocket push < 10s, SMS P1
  → agent_alert_manager étendu

---

ACQUITTEMENT ALERTES (Sprint 5)
  → Bouton acquitter Streamlit
  → Enregistre OBLIGATOIREMENT :
    - nom opérateur
    - timestamp au millième de seconde
    - commentaire (obligatoire, non vide)
    - action corrective
    - hash_acquittement SHA-256
  → Persistance TimescaleDB immuable
  → Conformité EN9100 — jamais d'acquittement anonyme

---

PERSISTANCE HISTORIQUE

TABLE analyses_history (TimescaleDB) :
CREATE TABLE analyses_history (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL DEFAULT 'default',
  question TEXT,
  profil TEXT CHECK (profil IN (
    'operateur','technicien','ingenieur','directeur')),
  json_compact JSONB,
  rapport_oapc TEXT,
  priority TEXT CHECK (priority IN ('P1','P2','P3','P4')),
  timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  hash TEXT UNIQUE,
  acquitted BOOLEAN DEFAULT FALSE,
  acquitted_by TEXT,
  acquitted_at TIMESTAMPTZ,
  acquitted_comment TEXT,
  pdf_path TEXT
);
CREATE INDEX ON analyses_history (user_id, timestamp DESC);

TABLE alerts (TimescaleDB) :
CREATE TABLE alerts (
  id BIGSERIAL PRIMARY KEY,
  timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  target_column TEXT,
  priority TEXT CHECK (priority IN ('P1','P2','P3','P4')),
  zscore_max FLOAT,
  message TEXT,
  source TEXT DEFAULT 'cron_monitor',
  acquitted BOOLEAN DEFAULT FALSE,
  acquitted_by TEXT,
  acquitted_at TIMESTAMPTZ,
  acquitted_comment TEXT,
  hash TEXT UNIQUE
);
CREATE INDEX ON alerts (priority, acquitted, timestamp DESC);

TABLE acquittements (TimescaleDB) :
CREATE TABLE acquittements (
  id BIGSERIAL PRIMARY KEY,
  alert_id BIGINT REFERENCES alerts(id),
  analyse_id BIGINT REFERENCES analyses_history(id),
  operateur TEXT NOT NULL,
  timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  commentaire TEXT NOT NULL,
  action_corrective TEXT,
  hash_acquittement TEXT UNIQUE
);

RÈGLE : Ne jamais stocker données brutes capteurs
dans analyses_history. Elles sont déjà dans les hypertables.

---

FILE D'ATTENTE OLLAMA (Sprint 5)
  → Python Lock FIFO
  → 1 seul appel LLM à la fois
  → Indicateur position dans la file
  → Protection CUDA Out of Memory
  → Timeout 30 secondes par appel
  → Si timeout → fallback template

---

MODE DÉGRADÉ (Sprint 5)
  → Si Ollama indisponible :
    → message clair à l'utilisateur
    → afficher dernier état connu
    → cache SQLite des dernières analyses
    → alertes Python pures restent actives
    → JAMAIS de crash visible

---

INTERFACE STREAMLIT (Sprint 5)

streamlit_app.py — 4 pages :

Page 1 — Chat Q/R
  → sélecteur profil (4 niveaux)
  → champ question en français
  → historique analyses (depuis analyses_history)
  → réponse OAPC en temps réel
  → bouton "Générer rapport PDF"

Page 2 — Centre alertes
  → liste alertes P1/P2/P3/P4 non acquittées
  → bouton acquitter + formulaire :
    nom opérateur + commentaire obligatoire
  → historique acquittements

Page 3 — Dashboard KPIs live
  → OEE/TRS, Cp/Cpk, MTBF/MTTR
  → calculés Python pur TimescaleDB
  → rafraîchissement automatique

Page 4 — Historique analyses
  → filtres date/profil/priorité
  → télécharger PDF
  → rejouer une analyse

Sécurité :
  → File d'attente Ollama (Lock FIFO)
  → Mode dégradé si Ollama down
  → Cache SQLite

---

SCRIPT BACKTEST (Sprint 5.5)

scripts/backtest.py
  → charger CSV données historiques
  → identifier pannes connues (timestamps + descriptions)
  → simuler monitoring z-score glissant sur toute la période
  → vérifier si alerte aurait été déclenchée avant chaque panne
  → calculer :
    délai détection (heures avant panne)
    coût évité (FINANCIAL_PARAMS)
    taux détection (%)
  → générer rapport PDF "preuve terrain"
  → "On aurait détecté cette panne Xh avant"
  → "Économie estimée : Xk€"

---

RAG DOCUMENTAIRE (Sprint 5.5)

enterprise/rag/context_agent.py
  → ChromaDB local
  → embeddings depuis data/manuals/ PDFs
  → similarité cosinus Python pur
  → extrait page exacte du manuel
  → retourne : {fichier, page, texte_extrait}
  → JAMAIS le LLM ne cherche dans les docs
  → Le LLM reformule uniquement

---

KPIs DASHBOARD
  Tous calculés Python pur via TimescaleDB.
  JAMAIS calculés par le LLM.

  Production :
  → OEE/TRS = Disponibilité × Performance × Qualité (cible ≥ 85%)
  → Taux disponibilité (cible ≥ 90%)
  → Taux performance (cible ≥ 95%)
  → Taux qualité / First Pass Yield (cible ≥ 99%)
  → MTBF (cible ≥ 2000h)
  → MTTR (cible < 2h)
  → Scrap Rate (cible < 1%)

  Qualité :
  → Cp/Cpk (Cp ≥ 1.33, Cpk ≥ 1.0)
  → PPM
  → Taux conformité

  Maintenance :
  → Santé machine
  → Dérive capteur
  → Taux maintenance planifiée (cible ≥ 85%)

  Énergie :
  → kWh/lot
  → Rendement thermique

---

COUCHE 5 — INFRASTRUCTURE

Hardware : RTX 3060 12Go VRAM
           PC bureau standard
           Zéro cloud — ITAR compliant — Air-gapped possible

LLM :
  → Ollama localhost:11434
  → OLLAMA_KEEP_ALIVE=-1 (modèles en VRAM entre appels)
  → qwen2.5-coder:7b (agents 1-4)
  → qwen2.5-coder:14b (agents 5-6)
  → File d'attente Lock FIFO (1 seul appel à la fois)
  → Timeout 30 secondes par appel

Base de données :
  → TimescaleDB (Docker) — données capteurs + historique
  → postgres_readonly (sandbox SQL, jamais d'écriture)
  → ChromaDB (RAG local manuels maintenance)
  → SQLite (cache mode dégradé)

Orchestration :
  → LangGraph StateGraph
  → AgentState TypedDict (state/schema.py)

Licences :
  → core/ Apache 2.0 (open source)
  → enterprise/ BSL 1.1 (commercial)
  → Ne jamais mélanger les deux

---

DÉCOMPTE AGENTS (32 total)

5  → Pipeline Q/R (Agents 1, 2, 3, 4a, 4b)
12 → Spécialistes + Judge (11 + 1)
1  → Mode Chat (Agent 5 OAPC)
9  → Mode Rapport :
     agent_6a, agent_6b, agent_6b_tendance, agent_6b_reco,
     agent_6c_pdf, agent_kpis, agent_tendance,
     agent_heatmap, agent_financier, agent_causes,
     context_agent
3  → Monitoring (cron_monitor, zscore_monitor, alert_manager)
2  → Fondation (styles, charts, formatters)

---

ROADMAP SPRINTS

Sprint 1 ✅ Prototype initial
Sprint 2 ✅ Agents 1-2-3
Sprint 3 ✅ 11 spécialistes Python purs
Sprint 4 ✅ Agent 4a-4b + Judge + LangGraph pipeline
Sprint 5 🔄 En cours :
  ✅ Agent 5 OAPC
  ✅ Agent 6a interprétation générique
  ✅ Agent 6b synthèse globale
  ✅ Agent 6c PDF (version basique)
  ⏳ Fondation report (styles/charts/formatters)
  ⏳ data/config.py
  ⏳ Agents calcul (kpis/tendance/heatmap/financier/causes)
  ⏳ RAG context_agent
  ⏳ Agents LLM (6b_tendance, 6b_reco)
  ⏳ Agent 6c PDF premium 12 sections
  ⏳ Monitoring (cron/zscore/alert_manager)
  ⏳ Streamlit interface
  ⏳ File d'attente Ollama + mode dégradé
  ⏳ Acquittement + historique

Sprint 5.5 :
  ⏳ Script backtest données historiques
  ⏳ RAG documentaire ChromaDB
  ⏳ data/config.py paramètres usine complets

Sprint 6 :
  ⏳ Monitoring temps réel WebSocket < 10s
  ⏳ VRAM Watchdog CUDA
  ⏳ Mode Investigation (plage temporelle)
  ⏳ Mode Comparaison A/B
  ⏳ Shift Handover automatique fin de poste
  ⏳ Cache sémantique pgvector < 100ms
  ⏳ Dashboard TV atelier feux tricolores
  ⏳ agent_notifier WebSocket + SMS
  ⏳ Agent matrix_profile (stumpy)
  ⏳ Agent méta-analyse consolidé
  ⏳ Agent simulation what-if dédié

---

ARGUMENT COMMERCIAL

"Braincube/Sight Machine :
 5000-10000€/mois, données sur cloud,
 violation ITAR potentielle.

IndustrIA :
 PC à 400€, 100% local, air-gapped,
 auditrable EN9100 du premier coup.

Preuve terrain (script backtest Sprint 5.5) :
 On rejoue vos données historiques
 et on vous prouve qu'on aurait détecté
 votre dernière panne 48h avant.
 Économie estimée : Xk€."
