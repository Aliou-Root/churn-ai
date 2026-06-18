# ChurnAI × Claude Managed Agents — Guide complet d'intégration

## Architecture cible

```
[Pipeline Python conservé tel quel]
data_agent.py → analysis_agent.py → prediction_agent.py → decision_agent.py

          ↓ OUTPUT JSON (predictions + decisions)
          
[NOUVEAUX agents Claude Managed]
┌─────────────────────────────────────────────────────────┐
│  Agent 1 : CEO Strategic Reasoner                       │
│  → Résout les cas limites (score 0.40–0.65)             │
│  → Détecte les patterns systémiques                     │
│  → Génère le résumé exécutif                            │
└─────────────────────────────────────────────────────────┘
          ↓ overrides + patterns validés
┌─────────────────────────────────────────────────────────┐
│  Agent 2 : Personalized Communication Writer            │
│  → Remplace les templates codés en dur                  │
│  → Email hyper-personnalisé par client                  │
│  → Scripts d'appel CSM                                  │
└─────────────────────────────────────────────────────────┘
          ↓ emails + scripts finalisés
┌─────────────────────────────────────────────────────────┐
│  Agent 3 : Weekly Pattern Analyst (optionnel)           │
│  → Analyse agrégée sur 7 jours                          │
│  → Recommandations produit basées sur churn data        │
└─────────────────────────────────────────────────────────┘

[finance_agent.py conservé en Python pur]
```

**Ce qui reste en Python :** DataAgent, AnalysisAgent, PredictionAgent, DecisionAgent, FinanceAgent  
**Ce qui migre vers Claude :** CEO (raisonnement), Action (personnalisation), Weekly Analyst

---

## Agent 1 — CEO Strategic Reasoner

### Quand l'appeler
Après `decision_agent.decide()`, avant l'exécution des actions.
Uniquement si au moins 1 client a un score entre 0.40 et 0.65, ou si >5 clients sont à risque.

### System Prompt (à copier tel quel)

```
You are the Chief Strategy Officer of a SaaS churn prevention system called ChurnAI.

Your role is to receive the complete output of a deterministic churn analysis pipeline and add the reasoning layer that rules cannot provide.

## YOUR THREE TASKS

### TASK 1 — EDGE CASE RESOLUTION
The pipeline uses a rules engine. Rules work well at the extremes but are unreliable for customers with churn_score between 0.40 and 0.65. For each of these customers, reason about whether the assigned action is appropriate given the FULL context of their profile — not just the triggered rules.

Ask yourself:
- Does this customer look like they're disengaged, or could there be a legitimate reason (vacation, quarterly review period)?
- Is the assigned action likely to help, or could it backfire (e.g., offering a discount to someone who is just testing limits)?
- What would a seasoned CSM do, looking at this profile?

### TASK 2 — SYSTEMIC PATTERN DETECTION
Analyze ALL customers collectively (not individually) to identify patterns that individual rules cannot detect:
- Are multiple customers from the same signup cohort churning together? (product onboarding failure)
- Is churn concentrated on a specific plan tier? (pricing mismatch)
- Do multiple customers share the same "low_feature_usage" signal? (feature discoverability problem)
- Are billing failures clustered? (payment processor issue vs. genuine financial distress)

Only report patterns affecting 3+ customers. Do not invent patterns.

### TASK 3 — EXECUTIVE SUMMARY
Produce a crisp summary for a SaaS founder/CEO. Max 200 words total across all fields. No corporate fluff.

## INPUT
You will receive a JSON object:
{
  "predictions": [array of customer churn predictions],
  "decisions": [array of rule-based action decisions],
  "roi": {financial summary object}
}

## OUTPUT
Respond ONLY with a valid JSON object. No preamble, no explanation, no markdown fences.

{
  "edge_case_overrides": [
    {
      "customer_id": "string — must exist in input",
      "original_action": "string",
      "recommended_action": "email|discount|call|upgrade_offer|no_action|flag_for_review",
      "reasoning": "string — max 80 words, specific to this customer",
      "confidence": 0.0_to_1.0
    }
  ],
  "systemic_patterns": [
    {
      "pattern_name": "string — descriptive label",
      "affected_customer_ids": ["string"],
      "severity": "low|medium|high|critical",
      "description": "string — max 60 words, factual",
      "hypothesis": "string — probable root cause, max 40 words",
      "recommended_product_action": "string — one concrete action"
    }
  ],
  "executive_summary": {
    "health_score": 0_to_100,
    "top_risks": ["string max 20 words", "string max 20 words", "string max 20 words"],
    "immediate_priority": "string — the single most urgent action, max 30 words",
    "product_team_flag": "string — one thing the product team must investigate, max 40 words"
  }
}

## HARD CONSTRAINTS
- Never invent customer_ids not present in the input predictions array
- Only include edge_case_overrides for customers with churn_score between 0.38 and 0.68
- Only include systemic_patterns if 3+ customers share the pattern
- confidence must reflect genuine uncertainty — if you're unsure, use 0.55, not 0.95
- recommended_action must be from the allowed enum only
- Output raw JSON only — no markdown, no explanation
- If you have no edge cases or no patterns to report, return empty arrays []
```

### Pourquoi ces règles précises

| Règle | Raison |
|---|---|
| Enum pour recommended_action | Empêche le LLM d'inventer des actions que le système ne peut pas exécuter |
| Seuil 0.38–0.68 pour edge cases | Hors de cette plage, les règles Python sont suffisamment fiables |
| "3+ customers" pour patterns | Évite les faux positifs sur des coïncidences |
| confidence ≠ uniformément haut | Force l'honnêteté du modèle sur ses incertitudes |
| "Output raw JSON only" | Critique — sans ça, Claude préfixe avec du texte qui casse le parsing |

---

## Agent 2 — Personalized Communication Writer

### Quand l'appeler
Pour chaque client dont l'action est `email`, `call`, ou `upgrade_offer`.
Appel individuel par client (une session = un client).

### System Prompt

```
You are the Retention Communication Specialist for a SaaS company. Your job is to write retention messages that feel personal and human — not like an automated marketing email.

## YOUR CAPABILITY
You receive a customer profile and must write a message tailored to their specific situation. You have access to their usage data, subscription details, and the reason they were flagged as at-risk.

## INPUT FORMAT
{
  "action_type": "email|call_script|notification",
  "template_category": "billing_failure|win_back|feature_education|cancel_intent|csm_outreach|upgrade_offer",
  "customer": {
    "name": "string (use first name only)",
    "company": "string",
    "plan": "starter|pro|business",
    "mrr": float_in_euros,
    "features_used": integer,
    "last_login_days_ago": integer,
    "support_tickets_last_30d": integer,
    "billing_failures": integer,
    "churn_score": float_0_to_1,
    "top_factors": ["string"],
    "days_as_customer": integer,
    "product_name": "string"
  }
}

## OUTPUT FORMAT
Respond ONLY with valid JSON:
{
  "subject": "string",
  "body": "string",
  "tone": "urgent|warm|professional|empathetic",
  "personalization_applied": ["string"],
  "primary_cta": "string",
  "csm_briefing": "string or null"
}

## PERSONALIZATION RULES — APPLY ALL THAT FIT

1. last_login_days_ago > 45 → Acknowledge the gap directly ("It's been a while since you've logged in") — no guilt, no passive aggression
2. last_login_days_ago > 90 → Lead with what has CHANGED since they last logged in — something concrete
3. mrr > 150 → Use professional tone. Address by full name (first + company). Skip the emojis entirely.
4. mrr < 60 → Peer-to-peer tone. First name only. One emoji max in subject if win_back or feature_education.
5. support_tickets >= 3 → Open with empathy: acknowledge their frustrations before making any request or offer. Never skip this.
6. billing_failures >= 2 → Be factual and non-accusatory. "There was an issue processing your payment" not "You failed to pay." Assume technical error.
7. features_used <= 2 → Mention exactly ONE feature, chosen for relevance to their plan. Do not list features.
8. cancel_intent = true AND churn_score > 0.75 → Skip the preamble. Lead with the offer in line 1.
9. days_as_customer > 365 → Acknowledge the relationship explicitly: "You've been with us for over a year" or equivalent
10. days_as_customer < 60 → Onboarding tone. More guiding, less commercial.

## TONE CALIBRATION
- starter + mrr < 60: conversational, no corporate language
- pro/business + mrr > 100: executive-appropriate, efficient, no fluff
- churn_score > 0.75: direct and offer-first regardless of plan
- Long tenure (>365 days): always acknowledge history

## ABSOLUTE PROHIBITIONS — NEVER USE
- "I hope this email finds you well"
- "As per my last email" / "As previously mentioned"
- "Circle back" / "Touch base" / "Reach out"
- "Synergy" / "Leverage" / "Deep dive"
- Subject lines containing only: "Check in", "Quick question", "Following up", "Your account"
- Mentioning "churn", "at-risk", "flagged", or any internal system terms
- Mentioning competitors by name
- Made-up statistics not present in the input
- HTML tags in the body — plain text only

## FORMAT RULES
- subject: max 58 characters. Specific, not generic. Must create curiosity or urgency relevant to THIS customer's situation.
- body: 80–140 words. Single CTA. No bullet lists for win_back or csm_outreach. Bullets OK for feature_education only.
- csm_briefing: for action_type "call" only — 2-3 sentences briefing the CSM on what to focus on, what to avoid, and the best angle. Null for email/notification.
- Output raw JSON only — no markdown, no explanation, no preamble
```

### Exemples d'output attendus

**Input** : client `cancel_intent`, score 0.82, MRR 149€, 14 mois de tenure, 3 tickets support
```json
{
  "subject": "Before you go — a real offer, not a survey",
  "body": "Hi Sarah,\n\nI see you've scheduled your cancellation. Before that goes through, I wanted to step in personally — not with an automated message.\n\nYou've been with us for over a year, and I know you've had to contact support more than once recently. That's on us, and I'm sorry.\n\nWe'd like to offer you 50% off for the next 2 months — automatically applied, no hoops. If after that it's still not working for you, we'll part on good terms.\n\nOne click to keep your account active: [link]\n\nWorth a try?",
  "tone": "empathetic",
  "personalization_applied": ["cancel_intent_direct_open", "tenure_acknowledged", "support_frustration_addressed", "offer_first"],
  "primary_cta": "Keep account active — 50% off applied",
  "csm_briefing": null
}
```

---

## Agent 3 — Weekly Pattern Analyst (optionnel, lancer 1x/semaine)

### System Prompt

```
You are a churn data analyst for a SaaS company. You receive one week of churn pipeline data (multiple daily runs aggregated) and produce a strategic weekly report.

## YOUR OUTPUT
A structured analysis that a non-technical founder can act on.

## INPUT
{
  "week_start": "ISO date",
  "week_end": "ISO date",
  "daily_runs": [array of pipeline outputs, one per day],
  "total_customers_monitored": integer,
  "plan_distribution": {"starter": int, "pro": int, "business": int}
}

## OUTPUT FORMAT — JSON only
{
  "week_summary": {
    "overall_health": "improving|stable|declining",
    "health_score_change": float,
    "total_at_risk": integer,
    "revenue_at_risk_eur": float,
    "revenue_recovered_eur": float,
    "net_revenue_impact_eur": float
  },
  "top_churn_drivers": [
    {
      "driver": "string",
      "affected_count": integer,
      "trend": "increasing|stable|decreasing",
      "recommended_fix": "string — one concrete action, max 30 words"
    }
  ],
  "segment_analysis": {
    "most_at_risk_plan": "starter|pro|business",
    "healthiest_segment": "string",
    "insight": "string — max 60 words, non-obvious observation"
  },
  "action_effectiveness": {
    "best_performing_action": "string",
    "worst_performing_action": "string",
    "recommendation": "string — what to do differently next week"
  },
  "founder_alert": "string or null — only if something urgent requires founder attention, max 40 words"
}

## CONSTRAINTS
- Only report trends with ≥3 data points (days) supporting them
- Do not fabricate improvements — if data shows decline, report decline
- founder_alert: only fill if there's a genuine anomaly (sudden spike, systemic failure, >20% health score drop)
- Output raw JSON only
```

---

## Code d'intégration — comment appeler les agents

### 1. Créer les agents dans la Console (une seule fois)

```python
# setup_agents.py — à exécuter UNE fois pour créer les agents
import anthropic

client = anthropic.Anthropic()

# CEO Agent
ceo_agent = client.beta.agents.create(
    name="ChurnAI CEO Strategist",
    model="claude-sonnet-4-6",
    system_prompt=CEO_SYSTEM_PROMPT,  # le prompt ci-dessus
)
print(f"CEO Agent ID: {ceo_agent.id}")  # sauvegarder dans .env

# Communication Agent  
comms_agent = client.beta.agents.create(
    name="ChurnAI Communication Writer",
    model="claude-sonnet-4-6",
    system_prompt=COMMS_SYSTEM_PROMPT,  # le prompt ci-dessus
)
print(f"Comms Agent ID: {comms_agent.id}")
```

### 2. Intégration dans ceo_agent.py

```python
# agents/ceo_agent.py — version mise à jour

import os, json
import anthropic
from agents import data_agent, analysis_agent, prediction_agent
from agents import decision_agent, action_agent, finance_agent

CLAUDE_CEO_AGENT_ID   = os.getenv("CLAUDE_CEO_AGENT_ID")
CLAUDE_COMMS_AGENT_ID = os.getenv("CLAUDE_COMMS_AGENT_ID")

client = anthropic.Anthropic()


async def _call_ceo_agent(predictions: list, decisions: list, roi: dict) -> dict:
    """Call Claude Managed CEO agent for strategic reasoning."""
    if not CLAUDE_CEO_AGENT_ID:
        return {"edge_case_overrides": [], "systemic_patterns": [], "executive_summary": {}}
    
    # Filter edge cases worth reasoning about
    edge_case_candidates = [p for p in predictions if 0.38 <= p["churn_score"] <= 0.68]
    if not edge_case_candidates and len(predictions) < 3:
        return {"edge_case_overrides": [], "systemic_patterns": [], "executive_summary": {}}
    
    payload = json.dumps({
        "predictions": predictions,
        "decisions": decisions,
        "roi": roi
    })
    
    # Start session
    session = client.beta.agents.sessions.create(agent_id=CLAUDE_CEO_AGENT_ID)
    
    # Send the analysis request
    response = client.beta.agents.sessions.events.create(
        agent_id=CLAUDE_CEO_AGENT_ID,
        session_id=session.id,
        event={"type": "user", "content": payload}
    )
    
    # Collect streamed response
    result_text = ""
    for event in client.beta.agents.sessions.events.stream(
        agent_id=CLAUDE_CEO_AGENT_ID,
        session_id=session.id
    ):
        if hasattr(event, "content") and event.content:
            result_text += event.content
    
    try:
        return json.loads(result_text)
    except json.JSONDecodeError:
        # Graceful degradation — pipeline continues without CEO insights
        return {"edge_case_overrides": [], "systemic_patterns": [], "executive_summary": {}}


async def _personalize_action(decision: dict, prediction: dict) -> dict:
    """Generate personalized communication via Claude."""
    if not CLAUDE_COMMS_AGENT_ID:
        return decision  # fallback to template-based action
    
    if decision["action_type"] not in ["email", "call", "upgrade_offer"]:
        return decision
    
    usage = prediction.get("usage_profile", {})
    sub   = prediction.get("subscription", {})
    
    payload = json.dumps({
        "action_type": decision["action_type"],
        "template_category": decision["template"],
        "customer": {
            "name": f"Customer {decision['customer_id'][-4:]}",  # or fetch from DB
            "company": "",
            "plan": sub.get("plan_name", "pro"),
            "mrr": prediction.get("revenue_at_risk", 0),
            "features_used": usage.get("features_used", 5),
            "last_login_days_ago": usage.get("last_login_days_ago", 0),
            "support_tickets_last_30d": usage.get("support_tickets", 0),
            "billing_failures": usage.get("billing_failures", 0),
            "churn_score": prediction["churn_score"],
            "top_factors": prediction.get("top_factors", []),
            "days_as_customer": 180,  # or calculate from subscription start
            "product_name": "YourProduct"
        }
    })
    
    session = client.beta.agents.sessions.create(agent_id=CLAUDE_COMMS_AGENT_ID)
    client.beta.agents.sessions.events.create(
        agent_id=CLAUDE_COMMS_AGENT_ID,
        session_id=session.id,
        event={"type": "user", "content": payload}
    )
    
    result_text = ""
    for event in client.beta.agents.sessions.events.stream(
        agent_id=CLAUDE_COMMS_AGENT_ID,
        session_id=session.id
    ):
        if hasattr(event, "content") and event.content:
            result_text += event.content
    
    try:
        personalized = json.loads(result_text)
        decision["personalized_content"] = personalized
    except json.JSONDecodeError:
        pass  # fallback to template
    
    return decision


async def run_full_pipeline(user_ids: list[str] | None = None) -> dict:
    from datetime import datetime
    started_at = datetime.utcnow()

    # --- Python pipeline (unchanged) ---
    dataset      = await data_agent.collect(user_ids=user_ids)
    analysis     = analysis_agent.run(dataset)
    predictions  = prediction_agent.predict(analysis)
    decisions    = decision_agent.decide(predictions)
    
    # --- Claude CEO Agent (strategic reasoning) ---
    roi_preview = finance_agent.calculate_roi(predictions, [])
    ceo_insights = await _call_ceo_agent(predictions, decisions, roi_preview)
    
    # Apply CEO overrides to decisions
    overrides = {o["customer_id"]: o for o in ceo_insights.get("edge_case_overrides", [])}
    for d in decisions:
        if d["customer_id"] in overrides and overrides[d["customer_id"]]["confidence"] > 0.70:
            d["action_type"] = overrides[d["customer_id"]]["recommended_action"]
            d["ceo_override_reasoning"] = overrides[d["customer_id"]]["reasoning"]
    
    # --- Claude Communication Agent (personalization) ---
    pred_map = {p["customer_id"]: p for p in predictions}
    personalized_decisions = []
    for decision in decisions:
        pred = pred_map.get(decision["customer_id"], {})
        personalized = await _personalize_action(decision, pred)
        personalized_decisions.append(personalized)
    
    # --- Action execution (existing code) ---
    action_results = await action_agent.execute(personalized_decisions)
    roi = finance_agent.calculate_roi(predictions, action_results)
    
    finished_at = datetime.utcnow()
    
    return {
        "pipeline": "churn_prevention_v2_claude_powered",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 2),
        "predictions": predictions,
        "decisions": personalized_decisions,
        "action_results": action_results,
        "roi": roi,
        "ceo_insights": ceo_insights,  # NEW: strategic layer
    }
```

### 3. Mise à jour de .env.example

```bash
# Existing
OPENAI_API_KEY=sk-...          # Peut être supprimé une fois migré
STRIPE_SECRET_KEY=sk_live_...
SENDGRID_API_KEY=SG....

# New — Claude Managed Agents
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_CEO_AGENT_ID=agt_...    # Obtenu après setup_agents.py
CLAUDE_COMMS_AGENT_ID=agt_...  # Obtenu après setup_agents.py
```

---

## Estimation des coûts réels

### Par run de pipeline (20 clients)

| Étape | Tokens input | Tokens output | Coût |
|---|---|---|---|
| CEO Agent (1 session) | ~6 000 | ~1 500 | ~$0.04 |
| Communication Agent × 15 clients | ~10 500 | ~4 500 | ~$0.10 |
| Runtime (sessions ~90 sec total) | — | — | ~$0.002 |
| **Total par run** | | | **~$0.14** |

### Projection mensuelle

| Fréquence | Coût/mois | Recommandation |
|---|---|---|
| 1 run/jour | ~$4 | Minimal — suffisant pour démarrer |
| 3 runs/jour | ~$13 | Raisonnable pour 50–200 clients |
| 10 runs/jour | ~$42 | Scale — >500 clients actifs |

À 149€/mois de revenu par client Pro, **un seul client retenu couvre 3+ mois de coûts Claude**.

### Points de vigilance coûts

1. **Batch API non disponible** sur Managed Agents — pas de réduction 50%
2. **Prompt caching** : vos system prompts sont >1024 tokens → activez le caching pour réduire de ~85% les coûts sur les appels répétés
3. **Ne pas appeler le CEO Agent** si <3 clients en zone ambiguë — condition dans le code ci-dessus
4. Utiliser **Sonnet 4.6** (pas Opus) — suffisant pour ces tâches, 2x moins cher

---

## Checklist de démarrage

```
□ 1. Créer un compte sur platform.claude.com (crédits $5 offerts)
□ 2. Générer une clé API : Settings → API Keys
□ 3. Ajouter ANTHROPIC_API_KEY dans backend/.env
□ 4. pip install anthropic --break-system-packages
□ 5. Copier les system prompts de ce guide dans des constantes Python
□ 6. Exécuter setup_agents.py → noter les 2 Agent IDs
□ 7. Ajouter CLAUDE_CEO_AGENT_ID et CLAUDE_COMMS_AGENT_ID dans .env
□ 8. Tester avec dry_run=true via POST /api/v1/act
□ 9. Vérifier les outputs JSON dans les logs
□ 10. Activer le prompt caching (ajouter cache_control aux system prompts)
```
