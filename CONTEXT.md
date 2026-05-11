# Fichier de Contexte Projet : IndustrIA (Code Name)

Dossier de R&D, d'Architecture, de Code et de Go-To-Market pour le développement d'une plateforme d'IA Industrielle Agentique Souveraine.

**Dernière mise à jour :** 10 mai 2026

---

## 1. CONTEXTE GLOBAL & VISION STRATÉGIQUE

### 1.1 Profil du Fondateur

- **Nom :** Ahmed Khaili, 28 ans.
- **Formation :** Ingénieur mathématicien diplômé de l'INSA Toulouse, spécialisé en mathématiques appliquées, statistiques, machine learning et traitement du signal.
- **Poste actuel :** Projet de Fin d'Études (PFE) chez LISI Aerospace (leader mondial de la fixation aéronautique).
- **Mission :** Démocratiser l'exploitation des données de capteurs en usine grâce aux architectures d'agents autonomes et aux modèles d'IA locaux (souverains).

### 1.2 Le Problème Industriel

Dans le secteur manufacturier (aéro, chimie, automobile, pharma), les usines génèrent d'immenses volumes de données temporelles via leurs capteurs. Cependant :

- **Coûts prohibitifs :** Les solutions de monitoring existantes (ex: Braincube, SCADA complexes) facturent des abonnements allant de 5 000 € à 10 000 € par mois et par site.
- **Dashboards « muets » :** Les techniciens reçoivent des courbes et des dashboards statiques complexes qu'ils comprennent à moitié. Il n'y a aucune IA réelle, pas d'interface en langage naturel, et l'analyse prédictive nécessite un profil d'ingénieur spécialisé.
- **Souveraineté et conformité compromises :** Envoyer des données de fabrication ou de conception sur des clouds américains (AWS, Azure, OpenAI) est une violation directe de la réglementation sur l'exportation d'armes ITAR (concept de Deemed Export / exportation implicite) et expose les PME à des risques majeurs de fuite de propriété intellectuelle.

### 1.3 La Solution : IndustrIA

Un copilote d'IA agentique open-source et hybride (Open Core) qui s'installe 100% en local (Air-Gapped) dans l'usine.

- **Interface :** Langage naturel en français (et anglais). Un technicien de maintenance pose une question simple : *« Le compresseur A a-t-il un comportement anormal depuis lundi ? »*
- **Analyse :** Le système interroge la base de données temporelle, exécute les algorithmes statistiques/ML appropriés, et génère un rapport explicatif détaillé avec des recommandations basées sur les manuels de maintenance de l'usine.
- **Pivot commercial :** Le nom public pour la phase de build est **IndustrIA**. Pour la commercialisation future, les noms protégés et libres de droits ciblés sont **Captris** (favori — Capteur + Matrix) ou **Vigilis** (Vigilance) afin d'éviter tout conflit de marque avec la SAS française « Industria » ou la plateforme européenne industria.tech.

---

## 2. ARCHITECTURE TECHNIQUE & PIPELINE DE DONNÉES

Le système est conçu pour remplacer l'ancienne chaîne de traitement par une boucle sémantique locale fermée.

### 2.1 Comparatif des Pipelines

**[Ancien Pipeline]**

```
Capteurs/API ──► Node-RED ──► Outil Monitoring Cloud (SaaS) ──► Dashboards Statiques ──► Analyste Humain
```

**[Pipeline IndustrIA]**

```
Capteurs/API ──► Node-RED ──► MQTT/OPC UA ──► TimescaleDB/pgai ──► Multi-Agents LangGraph (Local GPU) ──► UI Langage Naturel + Rapports PDF
```

### 2.2 La Pile Technologique (Software Stack)

| Domaine | Choix |
|--------|--------|
| **Acquisition Terrain (OT)** | Node-RED pour le routage. Protocoles : OPC UA (standard Siemens SIMATIC S7-1500) et MQTT (ingestion rapide). |
| **Base de Données** | TimescaleDB (PostgreSQL suralimenté pour les séries temporelles). |
| **Brique IA Base de Données** | Extension **pgai** de Timescale. Elle gère de manière native la création et la synchronisation des embeddings vectoriels (pgai Vectorizer) directement au sein de PostgreSQL. Les embeddings sont traités comme des données dérivées indexées (évitant la désynchronisation des données). |
| **Orchestration Multi-Agents** | LangGraph (logique cyclique et machines à états d'agents). |
| **Moteur d'Inférence local** | Ollama. |
| **Interface Utilisateur** | Streamlit (MVP rapide) → React / Next.js (production). |
| **RAG Documentaire** | LlamaIndex + base vectorielle locale ChromaDB. |
| **Rapports automatisés** | ReportLab (PDF de maintenance). |
| **Conteneurisation** | Docker (déploiement en un clic sur le serveur local de l'usine). |

---

## 3. DIMENSIONNEMENT MATÉRIEL & CHOIX DU MODÈLE

Pour garantir une souveraineté totale et respecter l'isolation réseau (Air-Gapped), les calculs d'inférence s'exécutent localement.

### 3.1 Contraintes Mémoire & Inférence (PC de Développement : RTX 3060 — 12 Go VRAM)

L'empreinte mémoire d'un grand modèle de langage s'exécutant localement est la principale contrainte opérationnelle.

- **Le Piège du CPU Offloading :** Si un modèle dépasse la capacité de la VRAM (notamment lors de l'expansion de la fenêtre de contexte), Ollama décharge les calculs sur le CPU (RAM système). Un déchargement partiel fait chuter la vitesse d'inférence de manière critique, ruinant l'expérience conversationnelle.
- **La taxe de contexte :** Une fenêtre de contexte de 19 000 tokens consomme entre 0,5 Go et 1,5 Go de VRAM supplémentaire selon le modèle.
- **Alerte RTX 3060 (12 Go) :** Sur la configuration de développement, le modèle `qwen2.5-coder:14b` requiert environ 8,7 Go de VRAM à vide. Avec le chargement des pilotes CUDA et l'expansion de la fenêtre de contexte, on approche rapidement de la limite matérielle des 12 Go.
- **Règle absolue :** Limiter la fenêtre de contexte maximale du modèle à **8 000 tokens** dans les configurations de test local pour éviter tout déchargement sur CPU.

### 3.2 Tableau d'Arbitrage des Modèles (Ollama)

| Modèle de langage (LLM) | Taille du fichier quantifié | Empreinte VRAM minimale requise | Vitesse sur RTX 4080 (16 Go) | Statut & Recommandation |
|-------------------------|-------------------------------|----------------------------------|------------------------------|-------------------------|
| Llama 3.2 8B (Q4_K_M) | ~4,9 Go | ~6 Go | ~95 tokens/s (100% GPU) | **Validé :** Laisse une immense marge pour le contexte ou des tâches parallèles sur 12 Go. |
| Qwen3 14B / Qwen 2.5 14B | ~12 Go | ~13 Go | ~61,85 tokens/s (100% GPU) | **Recommandé (Choix Principal) :** Meilleur compromis logique/vitesse. Limite stricte sur RTX 3060. |
| Ministral 3 14B | ~13 Go | ~14 Go | ~70,13 tokens/s (100% GPU) | **Validé :** Excellent modèle spécialisé pour l'Edge. |
| Mistral Small 3.2 24B | ~14 Go | ~15,5 Go | ~18,51 tokens/s (82% GPU / 18% CPU) | **Critique :** Saturation immédiate sur RTX 3060 (12 Go). |
| Qwen 2.5 32B (Q4_K_M) | ~19–20 Go | ~22 Go | < 10 tokens/s (Majorité CPU) | **Exclu :** Trop lent pour de l'interactif. Réservé aux tâches asynchrones batch. |

---

## 4. ALGORITHMES CLÉS & WORKFLOWS DE SÉCURITÉ

### 4.1 Algorithme de Détection d'Anomalie (z-score glissant)

Pour éviter de surcharger le LLM avec de l'analyse brute de séries temporelles, TimescaleDB calcule un z-score glissant en temps réel via des agrégats continus :

\[
z_t = \frac{x_t - \mu_{(t, N)}}{\sigma_{(t, N)}}
\]

Où :

- \(x_t\) représente la valeur brute mesurée par le capteur à l'instant \(t\).
- \(\mu_{(t, N)}\) désigne la moyenne mobile calculée sur une fenêtre glissante de taille \(N\).
- \(\sigma_{(t, N)}\) représente l'écart-type mobile sur cette même fenêtre de taille \(N\).

Si \(|z_t| > 3\), une alerte d'anomalie statistique est automatiquement déclenchée et transmise à l'orchestrateur d'agents.

### 4.2 Architecture du Pipeline de Validation Text-to-SQL

Le plus grand risque en production est l'exécution non contrôlée de requêtes SQL générées par l'IA sur la base de données industrielle. IndustrIA implémente un workflow sécurisé en boucle fermée :

```
[Question Utilisateur]
       │
       ▼
 ──► Identifie uniquement les tables/colonnes pertinentes via pgai semantic-catalog
       │                                                 (Évite la saturation du contexte du LLM)
       ▼
 ──► Génère la requête SQL TimescaleDB native (dialects et time-bucket respectés)
       │
       ▼
 ──► Parser abstrait (ex: sqlglot) : Interdiction de INSERT, UPDATE, DELETE, DROP
       │
       ▼
 ──► Exécution sur un réplica de base de données configuré en Read-Only
       │                                     Timeout strict < 1000ms
       │                                     Clause LIMIT 10 forcée
       │
       ├───► En cas d'Exception PG (Erreur)
       │           │
       │           ▼
       └───► [Étape 5 : Correction LLM (Max 1 itération)] ──► Réinjection de l'erreur SQL pour auto-correction
                   │
                   ▼ (Si validé)
```

Pour évaluer et fiabiliser ce pipeline, IndustrIA exploite les bibliothèques `timescale/text-to-sql-eval` et `timescale/text-to-sql-generator`.

### 4.3 Architecture Multi-Agents (LangGraph)

L’orchestration **LangGraph**, le principe « **JSON de paramètres côté LLM / code analytique en Python** », le catalogue des **28 agents**, le pipeline détaillé et les **sprints** de mise en œuvre sont documentés en **§10. Architecture multi-agents LangGraph**.

---

## 5. CADRE RÉGLEMENTAIRE & SOUVERAINETÉ (CONFORMITÉ)

Le respect des réglementations industrielles est le principal levier de vente d'IndustrIA face aux géants américains du cloud.

### 5.1 L'ITAR et la faille du « Deemed Export »

L'ITAR (International Traffic in Arms Regulations) régit de manière ultra-stricte les données techniques militaires et de l'aérospatiale aux États-Unis et en Europe.

- **La faille de l'exportation implicite :** Si des plans CAO, des tolérances de fixations ou des rapports de pannes de moteurs transitent sur un cloud public, ou s'ils sont consultés par un ressortissant de nationalité étrangère (non-US Person), la loi américaine qualifie cela d'exportation illégale d'armes.
- **La parade d'IndustrIA :** En fonctionnant dans un isolement réseau total (Air-Gapped / 100% sur site), IndustrIA garantit qu'aucune donnée ne sort physiquement de l'usine, éliminant de fait le risque juridique lié à l'ITAR.

### 5.2 Le Cyber Resilience Act (CRA) européen

Entré en vigueur en décembre 2024, le CRA impose des règles strictes de sécurité pour tous les logiciels et équipements connectés vendus en Europe.

- **11 septembre 2026 :** Obligation légale d'avoir un système de notification sous 24 heures pour signaler toute vulnérabilité activement exploitée.
- **11 décembre 2027 :** Application totale. Interdiction de commercialiser un logiciel contenant des vulnérabilités connues non corrigées.

**Impact architecture IndustrIA :**

- Génération d'un **SBOM** (Software Bill of Materials) traçant les dépendances open-source du projet.
- Période de support de sécurité minimale de **5 ans**.
- Mécanisme de mise à jour **OTA** (Over-The-Air) locale cryptographiquement signée, sans compromettre le réseau air-gapped de l'usine.

### 5.3 Tableau de Synthèse de Conformité

| Norme | Exigence Industrielle | Implémentation IndustrIA |
|-------|------------------------|---------------------------|
| **EN9100 / AS9100 D** | Traçabilité absolue, gestion de la qualité aéronautique. | Archivage automatique des contrôles d'IA visuelle, traçabilité des décisions d'agents. |
| **ITAR / EAR** | Interdiction d'accès aux données techniques par des tiers étrangers. | Serveur d'inférence local physique, 100% déconnecté d'Internet. |
| **CMMC 2.0 / NIST 800-171** | Protection des CUI. | Chiffrement local des données au repos, RBAC. |
| **Cyber Resilience Act (CRA)** | Sécurité by default, patches, signalement sous 24h. | SBOM automatisé, OTA signée localement, support patches de 5 ans. |

---

## 6. FEUILLE DE ROUTE COMMERCIALE & POSITIONNEMENT

### 6.1 Modèle de Monétisation : Open Core Hybride

Pour maximiser l'adoption tout en protégeant les revenus, IndustrIA utilise un modèle de double licence :

- **Cœur Open-Source (Apache 2.0) :** Connecteurs industriels de base (OPC UA `asyncua`, MQTT, schémas PostgreSQL de base). Intégration sans friction, pas de vendor lock-in.
- **Partie Propriétaire / Commerciale (Business Source License — BSL 1.1) :** Moteur d'orchestration multi-agents LangGraph, interface graphique de production, module d'analyse d'images par Deep Learning à 30 FPS, rapports automatiques de navigabilité EN9100, outil OTA signé localement. La licence BSL autorise l'usage gratuit hors production, mais impose l'achat d'une licence commerciale dès le déploiement en usine. Après 3 ans, le code BSL bascule automatiquement en open-source libre.

### 6.2 Bpifrance « IA Booster France 2030 » : levier de vente massif

Le programme d'État IA Booster France 2030 subventionne massivement l'adoption de l'IA par les PME de 10 à 2 000 salariés.

- **La faille d'acquisition :** Le processus individuel de référencement Bpifrance en tant qu'expert indépendant est long et complexe.
- **La stratégie « Partenaire » d'IndustrIA :** S'associer avec des cabinets de conseil déjà référencés Bpifrance (ex: Yakadata en France). Le cabinet réalise la phase d'audit financée, et intègre IndustrIA comme la solution logicielle de référence.

**Modèle financier pour le client :**

- **Diagnostic Data IA (Audit & Cadrage) :** Coût réel 13 000 € HT. Subventionné à 80% par l'État pour les PME. Reste à charge : **2 600 € HT**.
- **Choix de la solution & Intégration :** Subventionné à 50% par l'État via l'aide à l'expérimentation (jusqu'à 30 000 € de subvention directe).

### 6.3 Le Playbook « Design Partner » (Trojan Horse)

Pour signer les 3 premiers clients industriels sans produit fini :

1. **L'approche académique (PFE) :** Contacter directeurs d'usines / chefs de maintenance sur LinkedIn. Appel de 15 minutes pour valider les hypothèses de R&D (INSA + LISI Aerospace).
2. **Le test sémantique rétroactif (rétrodiction de panne) :** Demander un export `.csv` anonymisé de 3 mois de données d'une machine ayant subi une panne historique connue.
3. **La preuve par les chiffres :** Faire tourner IndustrIA localement sur ce jeu de données. Démontrer que l'algorithme (z-score glissant) aurait identifié la dérive et alerté **48 heures** avant l'arrêt, avec explication en langage naturel.

---

## 7. CHARTE ÉDITORIALE LINKEDIN (V2)

### 7.1 L'Identité de Marque

- **Qui :** Ahmed Khaili, Ingénieur mathématicien INSA, en PFE chez LISI Aerospace.
- **Positionnement :** « L'ingénieur de terrain sans filtre qui Build in Public ». Pas de jargon corporate, pas de bla-bla marketing. Faits scientifiques, technique, contraintes d'usine réelles, analyses de ROI.
- **Fréquence :** 2 publications par semaine (mardi et jeudi).

### 7.2 Les Piliers Éditoriaux

- **Mardi (Build in Public) :** « Autopsies de code » — pourquoi des choix (asyncua asynchrone, sécurisation Text-to-sql, TimescaleDB vs InfluxDB pour les LLM, etc.).
- **Jeudi (Insight Industrie) :** CRA, ITAR, deemed export, IA Booster France 2030, réalités de terrain.
- **Bi-mensuel (Personnel) :** Parcours de Grigny à l'INSA, leçons par l'arbitrage sportif de haut niveau.

### 7.3 Les 3 Règles d'Or LinkedIn

- **Règle A — Double CTA (Commentaire + DM discret) :** Les industriels évitent le commentaire public sur les pannes. Chaque post se termine par un CTA public + invitation à échanger en MP.
- **Règle B — Traduire en ROI :** Les ingénieurs achètent des fonctionnalités, les directeurs achètent du ROI. Convertir chaque explication technique en gain financier ou évitement de risque.
- **Règle C — Langue et cible :** Publications en **français** pour PME industrielles françaises, subventions Bpifrance, French Fab. Code source et dépôt GitHub en **anglais**.

---

## 8. CONSIGNES DE CODAGE POUR LES LLM (CURSOR / CLAUDE)

Lorsque vous écrivez ou modifiez du code pour le projet IndustrIA, respectez scrupuleusement :

### Asynchronisme obligatoire (OPC UA)

- Interdiction d'utiliser la bibliothèque dépréciée `python-opcua` (`opcua`).
- Utiliser exclusivement **opcua-asyncio** (import `asyncua`) pour les automates de terrain.
- Gérer l'acquisition via des context managers asynchrones (`async with Client(...) as client`).

### Optimisation Text-to-SQL (TimescaleDB)

- Utiliser l'extension **pgai** pour les requêtes adaptées aux hypertables et continuous aggregates.
- Exploiter **`time_bucket()`** pour toutes les fenêtres d'agrégation temporelle.
- Ne pas envoyer l'intégralité du DDL au LLM. **Schema Linking** via le catalogue sémantique natif pgai (**pgai semantic-catalog**).

### Défense de la sandbox SQL

- Nettoyer le Markdown (ex. blocs ` ```sql `) avant analyse.
- Utiliser regex ou parser (ex. **sqlglot**) et lever une exception si la requête contient : `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `GRANT`, `REVOKE`.
- Exécution sur pool **lecture seule**, timeout **< 1000 ms**, **`LIMIT 10`** forcé.

### Gestion locale d'Ollama

- API locale port **11434** par défaut.
- **`num_ctx` ≤ 8 000** tokens sur RTX 3060 (12 Go).
- Préférer **Pydantic** pour des réponses JSON fiables depuis Ollama.

---

## 9. ÉTAT ACTUEL DU CODE & INFRASTRUCTURE (10 mai 2026)

### 9.1 Fichiers existants sur GitHub

La structure de données de simulation et de modélisation est en place :

| Fichier | Statut |
|---------|--------|
| `data/config.py` | Configuration centralisée |
| `data/ebauche.py` | Simulation Ébauche |
| `data/filage.py` | Simulation Filage |
| `data/formage.py` | Simulation Formage / Tapis roulant |
| `data/anomaly_engine.py` | Moteur statistique / dérives physiques |
| `data/main_simulator.py` | Orchestrateur global |
| `data/ebauche.csv` | ~519 lignes |
| `data/filage.csv` | ~519 lignes |
| `data/formage.csv` | ~519 lignes |

### 9.2 Infrastructure de Développement Locale

- **Base de données :** TimescaleDB dans Docker (port **5432**, mot de passe : `industria123`).
- **Moteur d'inférence :** Ollama local, modèle `qwen2.5-coder:14b`.
- **Matériel :** NVIDIA RTX 3060, 12 Go VRAM (**rappel :** `num_ctx` max 8 000 tokens pour ~61 tokens/s sans CPU offloading).

### 9.3 Prochaine étape immédiate pour Cursor et Claude

**Priorité :** ingestion physique et structuration sémantique de la base de données.

1. **Créer `database/setup.py` :** connexion TimescaleDB port 5432.
2. **Créer les 3 tables physiques :** ébauche, filage, formage (convention actuelle du dépôt : `ebauche_data`, `filage_data`, `formage_data`).
3. **Activer l'extension :** `CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;`
4. **Hypertables :** partitionnement temporel, par ex. :

```sql
SELECT create_hypertable('ebauche_data', 'timestamp', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
SELECT create_hypertable('filage_data', 'timestamp', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
SELECT create_hypertable('formage_data', 'timestamp', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
```

5. **Script de chargement :** lire `ebauche.csv`, `filage.csv`, `formage.csv` et charger les données dans les hypertables correspondantes pour alimenter le pipeline Text-to-SQL.

---

## 10. ARCHITECTURE MULTI-AGENTS LANGGRAPH

### 10.1 Principe fondamental (règle absolue)

**Ollama / qwen2.5-coder:14b** n’est pas un générateur de code statistique. Il remplit uniquement des **JSONs de paramètres**. Le code analytique est **toujours** dur-codé en Python.

Chaque agent suit ce pattern :

- `compute_xxx()` → code Python pur, Ollama ne touche jamais
- `extract_params()` → Ollama remplit un JSON de paramètres ciblé
- `run(question)` → orchestre les deux

**Exemple `zscore_agent` :**

- Ollama reçoit : table disponible, colonnes, question (« dérive du four 3 depuis lundi »), modèle de JSON `{table, colonne, fenetre, seuil}`.
- Ollama répond uniquement, par exemple :  
  `{"table": "formage_data", "colonne": "four_3", "fenetre": 50, "seuil": 3.0}`

### 10.2 Catalogue des 28 agents

#### COUCHE 0 — Orchestration (5 agents)

**orchestrator_agent**  
Rôle : chef LangGraph. Reçoit la question, appelle le router, parallélise les agents analytiques, agrège les résultats, passe au `statistician_judge` puis au `llm_agent`. Gère retries et timeouts.

**router_agent**  
Rôle : analyse la question via Ollama (JSON uniquement). Retourne la liste des agents à appeler + ordre (séquentiel ou parallèle). Peut activer 1 à 8 agents simultanément selon la complexité.

Logique de décision (extraits) :

- « corrélation / lien / impact » → `correlation_agent` + `mutual_info_agent` + `pcmci_agent`
- « anomalie / bizarre / problème » → `zscore_agent` + `isolation_forest_agent` + `outlier_agent` + `changepoint_agent` + `matrix_profile_agent`
- « dérive / depuis / progressif » → `trend_agent` + `cusum_agent` + `ewma_agent`
- « compare / différence » → `anova_agent` + `descriptive_agent` + `distribution_agent`
- « cause / pourquoi » → `pcmci_agent` + `feature_importance_agent` + `regression_agent` + `pca_agent`
- « capable / Cp / qualité » → `capability_agent` + `spc_agent` + `distribution_agent`
- « prédit / va évoluer / futur » → `forecast_agent` + `trend_agent` + `rul_agent` + `conformal_agent`
- « résume / état général » → `descriptive_agent` + `oee_agent` + `spc_agent` + `isolation_forest_agent`
- « lien entre processus » → `cross_process_agent` + `lag_agent` + `correlation_agent` + `pcmci_agent`

**monitor_agent**  
Rôle : tourne en continu. Compare les valeurs en temps réel aux seuils LST/LTI de `data/config.py`. Déclenche une alerte proactive sans question utilisateur.

**memory_agent**  
Rôle : stocke l’historique des analyses en base. Permet les questions contextuelles (« compare avec la semaine dernière », « le problème qu’on avait trouvé mardi »).

**context_agent**  
Rôle : enrichit chaque question avec le contexte métier. Injecte modèles de pièces, nominaux, LST/LTI depuis `data/config.py`. Appelé automatiquement avant tous les agents.

#### COUCHE 1 — Données (3 agents)

**sql_agent**  
Méthodes : Text-to-SQL TimescaleDB, `time_bucket()`, sandbox read-only, validateur sqlglot.  
Ollama remplit : `{table, colonnes, filtre_temps, conditions, aggregation}` (aligné sur la cible architecture ; l’implémentation actuelle du dépôt peut générer du SQL direct selon le sprint).  
Sécurité : interdit `INSERT` / `UPDATE` / `DELETE` / `DROP` / `ALTER`. Timeout : 5 s, `LIMIT` 100 forcé.

**schema_agent**  
Rôle : introspection dynamique via `information_schema`. Retourne le schéma exact des tables. Appelé automatiquement par tous les agents.

**sampler_agent**  
Rôle : échantillonnage intelligent avant toute analyse. Évite de passer 50k lignes à un agent ML.

#### COUCHE 2 — Statistiques descriptives (5 agents)

**descriptive_agent** — moyenne, médiane, écart-type, min/max, quartiles, skewness, kurtosis — `scipy.stats`, `pandas`  
**distribution_agent** — Shapiro-Wilk, Anderson-Darling, histogramme, Q-Q plot — `scipy.stats` ; sortie criticité normalité → `statistician_judge_agent`  
**outlier_agent** — IQR, Tukey fences, z-score statique, boxplot — `scipy.stats`, `pandas`  
**trend_agent** — régression linéaire temporelle, Mann-Kendall, Sen’s slope — `pymannkendall`, `scipy`  
**seasonality_agent** — STL, FFT, périodicité — `statsmodels`, `numpy.fft`

#### COUCHE 3 — Détection d’anomalies (7 agents)

**zscore_agent** — z-score glissant, fenêtre et seuil configurables — `pandas`, `numpy` ; Ollama : `{table, colonne, fenetre, seuil}`  
**isolation_forest_agent** — Isolation Forest multivarié — `scikit-learn`  
**lof_agent** — Local Outlier Factor — `scikit-learn`  
**cusum_agent** — CUSUM — `numpy` (implémentation custom)  
**ewma_agent** — EWMA — `pandas` `ewm()`  
**changepoint_agent** — PELT — `ruptures`  
**matrix_profile_agent** *(ajout)* — Matrix Profile, motifs / formes sans entraînement ; LVDT 21 pts, vibratoires — `stumpy`

#### COUCHE 4 — Corrélations et causalité (5 agents)

**correlation_agent** — Pearson, Spearman, Kendall, heatmap, p-values — `scipy.stats`, `seaborn`  
**cross_process_agent** — jointure temporelle inter-tables, lag correlation, DTW — `pandas`, `fastdtw`  
**lag_agent** — cross-correlation décalée — `numpy.correlate`  
**pcmci_agent** *(remplace `granger_agent`)* — causalité non linéaire, systèmes bouclés / bruités — `tigramite`  
**mutual_info_agent** — information mutuelle — `sklearn` `mutual_info_regression`

#### COUCHE 5 — Analyse multifactorielle (6 agents)

**anova_agent** — ANOVA one/two-way, Tukey HSD — **ne s’exécute que si** `distribution_agent` + validation `statistician_judge` ; sinon fallback `kruskal_agent` — `scipy.stats`, `statsmodels`  
**kruskal_agent** — Kruskal-Wallis, Mann-Whitney — `scipy.stats`  
**regression_agent** — OLS multiple, Ridge, Lasso — `scikit-learn`  
**feature_importance_agent** — RF importance, SHAP — `scikit-learn`, `shap`  
**pca_agent** — PCA, variance expliquée, biplot — `scikit-learn`  
**clustering_agent** — K-Means, DBSCAN — `scikit-learn`

#### COUCHE 6 — Capabilité process SPC (4 agents)

**capability_agent** — Cp, Cpk, Pp, Ppk ; LST/LTI depuis `data/config.py`  
**spc_agent** — cartes Shewhart (X-bar, R, S, p, np, c, u) — `pandas`, `numpy`  
**msa_agent** — Gauge R&R — `numpy`, `scipy`  
**oee_agent** — OEE = disponibilité × performance × qualité — `pandas`

#### COUCHE 7 — Prédiction (4 agents)

**forecast_agent** — Prophet, ARIMA, SARIMA — `prophet`, `statsmodels`  
**rul_agent** — RUL ; couplé à `conformal_agent`  
**conformal_agent** *(ajout)* — prédictions conformes, intervalles garantis — `MAPIE` ; usage type EN9100  
**maintenance_agent** — maintenance prédictive seuils + ML ; date d’intervention recommandée

#### COUCHE 8 — Validation & output (4 agents)

**statistician_judge_agent** *(ajout — critique)*  
Valide la cohérence mathématique des méthodes choisies par le router **avant** exécution. Règles : non-normalité → bloque ANOVA → `kruskal_agent` ; moins de 30 points → bloque ML lourd ; non-stationnaire → différenciation avant ARIMA ; corrélation spurieuse → avertissement. Placement : après router, avant exécution.

**llm_agent** — agrège les résultats, explication français technicien ; Ollama sur JSON fourni ; `num_ctx` ≤ 8000 (RTX 3060).

**report_agent** — PDF ReportLab, graphes, EN9100 — `reportlab`, `matplotlib`

**viz_agent** — graphes Plotly / Streamlit — `plotly`

### 10.3 Pipeline complet

```
Question utilisateur
        ↓
context_agent  (injecte nominaux/LST/LTI)
        ↓
router_agent   (choisit 1 à N agents)
        ↓
statistician_judge_agent  (valide cohérence math)
        ↓
schema_agent + sampler_agent  (données propres)
        ↓
sql_agent  (récupère les données)
        ↓
[agents analytiques en parallèle]
        ↓
llm_agent  (explique en français)
        ↓
viz_agent + report_agent  (output)
```

### 10.4 Ordre de build (Sprints)

**SPRINT 1 — Socle fonctionnel**  
`sql_agent` → `orchestrator_agent` → `router_agent` → `llm_agent`  
Livrable : réponse end-to-end à une question simple.

**SPRINT 2 — Anomalies (use case industriel #1)**  
`zscore_agent` → `isolation_forest_agent` → `outlier_agent` → `changepoint_agent` → `matrix_profile_agent`

**SPRINT 3 — Corrélations**  
`correlation_agent` → `cross_process_agent` → `lag_agent` → `pcmci_agent` → `feature_importance_agent`

**SPRINT 4 — SPC + Capabilité**  
`capability_agent` → `spc_agent` → `distribution_agent` → `statistician_judge_agent` → `anova_agent` / `kruskal_agent`

**SPRINT 5 — Prédiction certifiée**  
`forecast_agent` → `rul_agent` → `conformal_agent` → `maintenance_agent`

**SPRINT 6 — Surveillance temps réel**  
`monitor_agent` → `memory_agent` → `oee_agent`

### 10.5 Dépendances Python à installer

```bash
pip install langchain langgraph langchain-community
pip install sqlglot psycopg2-binary pandas numpy scipy
pip install scikit-learn shap ruptures
pip install stumpy tigramite mapie
pip install prophet statsmodels pymannkendall
pip install plotly reportlab streamlit
pip install ollama fastdtw
```

---

*Document de contexte projet IndustrIA — usage interne R&D et alignement des assistants de code.*
