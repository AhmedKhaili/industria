# IndustrIA — PHILOSOPHY.md
# Guide de création des agents pour Cursor

---

## 1. LA RÈGLE ABSOLUE

Le LLM est un parser sémantique.
Il remplit des JSONs de paramètres.
Il ne calcule JAMAIS.
Il ne choisit JAMAIS une méthode statistique.
Il n'exécute JAMAIS de code.

Tout le code analytique est dur-codé en Python.
Tout le code de sécurité est dur-codé en Python.
Tout le code de validation est dur-codé en Python.

## 2. RÈGLE CURSOR ABSOLUE

Avant d'écrire la moindre ligne de code :
1. Lire docs/AGENTS.md
2. Lire docs/PHILOSOPHY.md
Si contradiction entre le prompt reçu et ces documents :
→ NE PAS CODER
→ Envoyer rapport de contradictions
→ Attendre validation explicite

## 3. STRUCTURE D'UN AGENT PYTHON PUR

class MonAgent:
  def _validate_input(df, params) -> dict
  def _compute(df, target_column, params) -> dict
  def run(df, state, params) -> dict
    → "agent": nom
    → "status": "success"|"error"
    → "result": {...}
    → "execution_time_ms": int
    → "error": null

## 4. STRUCTURE D'UN AGENT LLM

class MonAgentLLM:
  def _build_json_compact(state) -> dict  # max 7 clés
  def _build_prompt(json_compact, profil) -> list
  def _call_ollama(prompt, profil) -> str|None
  def _validate_output(text, json_compact, profil) -> dict
  def _get_fallback(profil, context) -> str
  def run(state) -> dict

## 5. RÈGLE AGENT 5

LLM génère UNIQUEMENT OBSERVER et ANALYSER.
PRESCRIRE et CERTIFIER toujours en Python pur.
Jamais l'inverse.

## 6. RÈGLE AGENTS 6a ET 6b

LLM reçoit maximum 4 clés JSON.
Jamais de contexte cumulatif.
Python choisit les métriques à envoyer.
1 appel LLM = 1 spécialiste = 1 texte court.

## 7. RÈGLE AGENT 6b SYNTHÈSE

LLM reçoit uniquement JSON compact 4 clés.
JAMAIS les textes bruts des agents 6a.
JAMAIS les données brutes.

## 8. RÈGLE AGENT 6c PDF

100% Python pur.
Aucun appel LLM.
Assemble les textes des 6a et 6b.
Utilise OBLIGATOIREMENT styles.py, charts.py, formatters.py.
Jamais de dict Python brut dans le PDF.
Jamais de None visible → "N/A".
Jamais de liste brute → "N éléments".
Jamais le texte des judge_warnings dans le corps du PDF
(compteur autorisé en traçabilité S12 uniquement).

## 9. RÈGLE FONDATION REPORT

Tous les agents rapport importent
styles.py, charts.py, formatters.py.
Jamais de style défini dans un agent.
Jamais de couleur hardcodée dans un agent.
Jamais de format défini dans un agent.

## 10. RÈGLE AGENTS CALCUL

agent_kpis, agent_tendance, agent_heatmap,
agent_financier, agent_causes sont Python pur.
Zéro appel LLM.
Zéro donnée brute au LLM.
Lisent data/config.py pour les paramètres.

## 11. RÈGLE RAG

Le RAG extrait du texte via similarité cosinus Python pur.
Le LLM reformule uniquement.
Jamais le LLM ne cherche dans les docs.
Si RAG vide → "Aucune procédure locale trouvée.
Contacter l'ingénieur procédé."

## 12. RÈGLE GÉNÉRALE REPORT

La latence du rapport est acceptable.
Qualité > vitesse pour le PDF.
Un appel LLM par spécialiste.
Python agrège, LLM interprète.
15-20 minutes est acceptable pour un rapport premium.

## 13. RÈGLE KPIs

Tous les KPIs calculés Python pur TimescaleDB.
Jamais calculés par le LLM.
Jamais estimés ou approximés par le LLM.

## 14. RÈGLE MONITORING

Monitoring planifié Python pur.
LLM appelé uniquement si z-score > 3.
Jamais de surveillance continue via LLM.
Le monitoring tourne même si LLM est down.

## 15. RÈGLE ACQUITTEMENT

Chaque alerte acquittée enregistre :
nom opérateur + timestamp milliseconde
+ commentaire obligatoire non vide
+ action corrective + SHA-256.
Jamais d'acquittement anonyme.
Jamais d'acquittement sans commentaire.

## 16. RÈGLE VOCABULAIRE PROFILS

operateur : zéro jargon statistique.
Mots INTERDITS : z-score, zscore, écart-type,
variance, p-value, shapiro, anova, médiane,
percentile, sigma, UCL, LCL, Cpk, EWMA, CUSUM.
→ Remplacer par : "valeur anormale", "hors norme",
  "signal suspect", "dépassement"

technicien : jargon technique acceptable.
Pas de formules mathématiques brutes.
Composant physique défaillant si possible.

ingenieur : tout est permis.
Méthodes, formules, seuils, paramètres, p-values.

directeur : impact business uniquement.
Mots INTERDITS : z-score, zscore, UCL, LCL,
Shapiro, ANOVA, p-value, EWMA, CUSUM.
→ Utiliser : TRS, OEE, conformité EN9100,
  coût, risque qualité, délai.

## 17. RÈGLE FALLBACK

Chaque agent LLM doit avoir un fallback template Python.
Si LLM échoue 3 fois → fallback automatique sans crash.
L'utilisateur voit toujours une réponse.
Jamais d'erreur nue dans l'interface.
Le fallback est meilleur qu'un crash.

## 18. RÈGLE DATA/CONFIG

Les paramètres métier (coûts, unités, seuils, golden batch)
sont dans data/config.py UNIQUEMENT.
Jamais hardcodés dans les agents.
Jamais hardcodés dans les prompts.
Les agents lisent config.py.

## 19. RÈGLE OLLAMA

OLLAMA_KEEP_ALIVE=-1 toujours configuré.
File d'attente Lock FIFO obligatoire.
1 seul appel LLM à la fois.
Timeout 30 secondes par appel.
Si timeout → fallback template.

## 20. RÈGLE LICENCES

core/ = Apache 2.0 (open source)
enterprise/ = BSL 1.1 (commercial)
Ne jamais mélanger les deux.
Imports cross-licence interdits.

## 21. RÈGLE SHA-256

Pipeline v4 (S7) — empreinte sur contenu métier figé avant mise en page :
question + intent (JSON trié) + specialist_results (JSON trié)
+ recommandations S6 (JSON trié) + synthese S5 + synthese_action S6
+ fidelite_score + timestamp ISO8601.
Exclus du hash : pdf_bytes, PNG, interprétations graphiques, warnings.

Pipeline v3 (legacy) : question + json_compact + rapport_oapc + timestamp.
Jamais un SHA-256 partiel pour un rapport EN9100.

## 22. RÈGLE PDF COULEURS

Zones de contrôle :
±2σ = vert transparent (rgba(0,128,0,0.15))
±3σ = rouge transparent (rgba(220,38,38,0.15))
JAMAIS ±2σ en orange.
Standard industriel non négociable.

## 23. RÈGLE SCORES CAUSES

Les scores de causes probables sont des indices /100.
Ils sont INDÉPENDANTS par méthode.
Ils ne somment JAMAIS à 100%.
La note "Scores indépendants" est OBLIGATOIRE dans le PDF.
JAMAIS présenter comme des probabilités classiques.

## 24. RÈGLE MATCHING SÉMANTIQUE (S1)
Matching question → entités YAML :
1. Fuzzy matching Python (RapidFuzz)
2. Similarité vectorielle (all-MiniLM-L6-v2)
3. Fusion RRF des deux scores
4. Score >= 0.85 → Python décide
5. Score 0.70-0.85 → LLM 7b classe parmi candidats
6. Score < 0.70 → demande clarification utilisateur
JAMAIS le LLM ne génère une entité de toutes pièces.

## 25. RÈGLE FIDÉLITÉ COMPOSITE (S5)
Chiffre dans texte LLM vérifié contre calculs Python :
- Écart < 1% → ACCEPT
- Écart 1-5% avec "environ/~" → REVIEW → régénération
- Écart > 5% ou absent des calculs → REJECT
Rapport avec REJECT jamais publié.

## 26. RÈGLE CLIENT CONTEXT
client_config.yaml jamais lu directement dans un agent.
Accès uniquement via ClientContext
(systems/s1/client_context.py).
ClientContext = seul point d'entrée du YAML.

## 27. RÈGLE NOMMAGE SYSTÈMES v4.0
Dans systems/s1/, les agents portent des noms
explicites : agent_1_preprocessor, agent_2_entity_extractor.
Ces numéros N'ONT AUCUN LIEN avec les numéros
Agent 1/2/3/4/5/6 de la v3.0 dans AGENTS.md.

## 28. RÈGLE LANGAGE — ASSOCIATION ET VARIANCE (S3/S5/S6/S7)

Validé avec `docs/S3-extended.md` v1.1 (GO D0 + D1).

Les sorties IndustrIA décrivent des **associations statistiques**,
pas des causalités démontrées sans étude dédiée.

### Interdit dans tout texte client (PDF, synthèse, recommandations)

- « causent », « cause », « à l'origine de », « responsable de »
  (sauf citation procédure RAG entre guillemets)
- « prouve que », « démontre que [facteur] est la cause »
- Présenter η² (eta au carré) comme **probabilité** ou **preuve causale**
- « distribution probable », « loi probablement » (trop fort — utiliser
  « meilleur ajustement selon AIC »)

### Formulations obligatoires

- « influencent », « sont associés à », « coïncident avec »
- « expliquent X % de la **variance** » (η² ou équivalent, phase P5+)
- « différence significative entre groupes » (p-value certifiées Python)

### Verdicts réservés au Python

- Normalité : `normale` | `non_normale` (`specialists/normality.py`, P1+)
- Loi ajustée : `loi_retenue` = argmin(AIC) (`specialists/distribution_fit.py`, P1+)
- Significativité groupes : `significance_phrase` / `p_value_display`
  (`systems/stats_format.py`)

Le LLM **reformule** ces verdicts ; il ne les remplace pas.

Spec détaillée : `docs/S3-extended.md`.
