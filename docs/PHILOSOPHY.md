# PHILOSOPHY.md — IndustrIA
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

---

## 2. STRUCTURE OBLIGATOIRE DE CHAQUE AGENT LLM

Chaque agent qui utilise Ollama doit avoir
exactement cette structure :

MÉTHODE 1 — _build_prompt()
  Construit le prompt système et utilisateur.
  Fournit au LLM UNIQUEMENT ce dont il a besoin.
  Jamais plus de 2000 tokens de contexte
  pour les agents JSON simples.
  Toujours donner un exemple de sortie attendue
  dans le prompt.

MÉTHODE 2 — _call_ollama()
  Appelle Ollama avec les paramètres stricts.
  num_predict limité (150 pour JSON, 400 pour texte).
  temperature basse (0.0 à 0.1 pour JSON).
  format="json" si sortie JSON.
  Gère le timeout et les erreurs réseau.

MÉTHODE 3 — _validate_output()
  Validation Python pure (0 LLM).
  Vérifie que le JSON est valide.
  Vérifie que les valeurs existent en base.
  Corrige ou rejette si invalide.
  Maximum 3 tentatives.

MÉTHODE 4 — run(input) -> dict
  Orchestre les 3 méthodes dans l'ordre.
  Met à jour le LangGraph State.
  Retourne toujours un dict structuré.
  Ne plante JAMAIS — gère toutes les erreurs.

---

## 3. STRUCTURE OBLIGATOIRE DE CHAQUE AGENT PYTHON PUR

Chaque agent sans LLM doit avoir
exactement cette structure :

MÉTHODE 1 — _validate_input()
  Vérifie que le DataFrame n'est pas vide.
  Vérifie que les colonnes nécessaires existent.
  Vérifie que le nombre de lignes est suffisant.
  Retourne False + message d'erreur si invalide.

MÉTHODE 2 — _compute()
  Le calcul pur.
  Toujours sur des copies du DataFrame
  (jamais modifier l'original).
  Arrondir les floats à 3 décimales.
  Gérer les NaN et les infinis.

MÉTHODE 3 — run(df, params) -> dict
  Appelle _validate_input puis _compute.
  Mesure le temps d'exécution.
  Retourne toujours :
  {
    "agent": "nom_agent",
    "status": "success"|"error",
    "result": {...},
    "execution_time_ms": int,
    "error": null|"message"
  }

---

## 4. RÈGLES DE PROMPT OLLAMA

Toujours inclure dans le prompt système :
  - Ce que l'agent DOIT faire (1 phrase)
  - Ce qu'il NE DOIT PAS faire (1 phrase)
  - Le format JSON EXACT attendu avec exemple
  - Les valeurs possibles pour chaque champ

Toujours terminer le prompt utilisateur par :
  "Réponds UNIQUEMENT avec le JSON.
   Pas de markdown. Pas d'explication.
   Pas de texte avant ou après le JSON."

Toujours nettoyer la réponse avant parsing :
  - Supprimer les blocs ```json``` et ```
  - Extraire entre le premier { et le dernier }
  - json.loads() dans un try/except

---

## 5. RÈGLES DE SÉCURITÉ SQL

Toujours utiliser un utilisateur PostgreSQL
read-only dédié.
Toujours injecter LIMIT 100 avant exécution.
Toujours timeout 2000ms.
Toujours valider avec sqlglot AST.
Jamais construire du SQL par concaténation
de strings — utiliser des paramètres.

---

## 6. RÈGLES LANGGRAPH STATE

Chaque agent doit :
  - Lire depuis state ce dont il a besoin
  - Écrire dans state ce qu'il produit
  - Ne jamais modifier ce qu'un autre agent
    a écrit dans state
  - Toujours ajouter les erreurs dans
    state["errors"] sans planter

Colonnes dynamiques :
  Toujours utiliser state["target_column"]
  pour indexer les DataFrames.
  Jamais de noms de colonnes hardcodés
  dans les spécialistes.

---

## 7. RÈGLES DE QUALITÉ CODE

PEP 8 obligatoire.
Type hints sur toutes les fonctions.
Docstring sur chaque méthode.
Logging sur chaque étape importante.
  (pas print — utiliser logging.info)
Try/except sur chaque appel externe.
  (Ollama, PostgreSQL, calculs)
Mesurer le temps d'exécution de chaque agent.

---

## 8. EXEMPLE DE BON PROMPT OLLAMA

Voici un exemple de prompt système
bien construit pour un agent JSON :

  "Tu es un extracteur de paramètres.
   Tu analyses une question industrielle
   et tu identifies les variables pertinentes.
   Tu ne fais AUCUN calcul.
   Tu retournes UNIQUEMENT ce JSON :
   {
     'table': 'ebauche_data' ou
              'filage_data' ou
              'formage_data',
     'colonne': 'nom_exact_colonne',
     'fenetre': entier entre 10 et 100,
     'seuil': décimal entre 2.0 et 4.0
   }
   Exemple pour 'anomalie four 3 cette semaine' :
   {
     'table': 'formage_data',
     'colonne': 'four_3',
     'fenetre': 20,
     'seuil': 3.0
   }
   Réponds UNIQUEMENT avec le JSON.
   Pas de markdown. Pas d'explication."

---

## 9. CHECKLIST AVANT DE VALIDER UN AGENT

□ Le LLM retourne uniquement un JSON ?
□ La validation Python vérifie les colonnes ?
□ Le DataFrame original n'est jamais modifié ?
□ Les erreurs sont catchées partout ?
□ Le State LangGraph est mis à jour ?
□ state["target_column"] est utilisé
  (pas de colonne hardcodée) ?
□ Le temps d'exécution est mesuré ?
□ Le format de retour est correct ?
□ Les NaN et infinis sont gérés ?
□ Le timeout Ollama est configuré ?

---

*Ce document doit être lu par Cursor
avant de générer chaque agent IndustrIA.*
