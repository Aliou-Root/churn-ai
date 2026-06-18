<div align="center">

# 🛡️ ChurnAI

### Prévention autonome du churn SaaS par système multi-agents, propulsée par Claude

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776ab.svg)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688.svg)](https://fastapi.tiangolo.com)
[![Claude](https://img.shields.io/badge/Claude-Sonnet%204.6-d97757.svg)](https://www.anthropic.com)

*Du signal brut à l'action de rétention — sans intervention humaine.*

[Démo](#-démarrage-rapide) · [Architecture](#-architecture) · [API](#-api) · [Déploiement](#-déploiement)

</div>

---

## ✨ Aperçu

**ChurnAI** surveille en continu vos clients SaaS, prédit lesquels sont sur le point de partir, et déclenche automatiquement la meilleure action de rétention. C'est un pipeline orchestré de **six agents** : les étapes déterministes (collecte, scoring, finance) tournent en Python pur pour la vitesse et la fiabilité ; le raisonnement stratégique et la rédaction des messages sont délégués à **Claude**.

```
📡 Data  ›  🔍 Analyse  ›  🎯 Prédiction  ›  🧠 Décision  ›  ⚡ Action  ›  📈 ROI
```

Le système fonctionne **end-to-end sans aucune clé API** grâce à des données de démonstration et des templates de repli — branchez Stripe, SendGrid et Claude quand vous êtes prêt.

---

## 🧠 Les agents

| Agent | Rôle | Moteur |
|-------|------|--------|
| **📡 Data Agent** | Collecte et normalise les abonnements Stripe + logs d'usage produit | Python |
| **🔍 Analysis Agent** | Détecte les signaux comportementaux (connexions, adoption, paiement…) | Python |
| **🎯 Prediction Agent** | Score de churn 0→1 + niveau de risque + jours restants | Python (heuristique, remplaçable par ML) |
| **🧠 CEO Strategist** | Arbitre les cas limites, détecte les patterns systémiques, résumé exécutif | Claude Sonnet 4.6 |
| **✉️ Communication Writer** | Emails / scripts d'appel personnalisés par client | Claude Sonnet 4.6 |
| **📊 Weekly Analyst** | Rapport hebdomadaire de tendances et alertes fondateurs | Claude Sonnet 4.6 |
| **💰 Finance Agent** | Revenus à risque, revenus sauvés, ROI | Python |

> Sans `ANTHROPIC_API_KEY`, les agents Claude sont désactivés proprement (*graceful degradation*) et le pipeline déterministe continue de tourner.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (nginx)                                            │
│  • index.html  → landing page                                │
│  • app.html    → dashboard temps réel                        │
└───────────────────────────┬─────────────────────────────────┘
                            │  /api/v1  (REST)
┌───────────────────────────▼─────────────────────────────────┐
│  Backend (FastAPI)                                           │
│  ceo_agent.run_full_pipeline()                               │
│   data → analysis → prediction → decision → action → finance │
│  • APScheduler (rapport hebdo)                               │
│  • Auth par X-API-Key (optionnelle)                          │
└──────────────┬───────────────────────────┬──────────────────┘
              │                           │
       ┌───────▼──────┐            ┌───────▼──────┐
       │ PostgreSQL   │            │ Redis        │
       │ (historique) │            │ (cache 30min)│
       └──────────────┘            └──────────────┘
```

**Stack :** FastAPI · SQLAlchemy (async) · PostgreSQL · Redis · APScheduler · Anthropic SDK · Docker Compose · nginx

---

## 🚀 Démarrage rapide

### Avec Docker (recommandé)

```bash
git clone https://github.com/Aliou-Root/churn-ai.git
cd churn-ai

# Configurez vos variables (optionnel — la démo tourne sans clés)
cp backend/.env.example backend/.env

# Lancez toute la stack
docker compose up --build
```

| Service | URL |
|---------|-----|
| 🖥️ Landing + Dashboard | http://localhost:3000 |
| ⚙️ API (FastAPI) | http://localhost:8001 |
| 📚 Docs interactives | http://localhost:8001/docs |

### En local (backend seul)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload
```

Ouvrez ensuite `frontend/index.html` dans votre navigateur.

---

## 🔌 API

Toutes les routes sont préfixées par `/api/v1`. Si `API_KEY` est défini, ajoutez l'en-tête `X-API-Key`.

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET`  | `/health` | Health check public |
| `POST` | `/analyze` | Collecte + analyse comportementale |
| `POST` | `/predict` | Analyse + prédictions de churn |
| `POST` | `/act` | Pipeline complet (`dry_run: true` pour simuler) |
| `POST` | `/pipeline/run` | Déclencheur explicite du pipeline |
| `GET`  | `/dashboard` | Données complètes du dashboard (cache Redis 30 min) |
| `POST` | `/dashboard/refresh` | Force le recalcul sans cache |
| `GET`  | `/insights` | Insights CEO seuls (léger) |
| `GET`  | `/users/{customer_id}/risk` | Profil de risque d'un client |

Exemple :

```bash
curl -X POST http://localhost:8001/api/v1/act \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'
```

---

## ⚙️ Configuration

Toutes les variables sont documentées dans [`backend/.env.example`](backend/.env.example). Aucune n'est obligatoire pour la démo, sauf `DATABASE_URL` (fournie automatiquement par Docker Compose).

| Variable | Effet si absente |
|----------|------------------|
| `ANTHROPIC_API_KEY` | Agents Claude désactivés — pipeline déterministe seul |
| `STRIPE_SECRET_KEY` | Données Stripe simulées (mock) |
| `SENDGRID_API_KEY` | Emails simulés dans les logs |
| `API_KEY` | API ouverte (mode dev) |

> ⚠️ **Sécurité** — ne committez jamais votre fichier `.env`. Il est exclu par `.gitignore`. Si une clé a fuité, **révoquez-la et régénérez-la** immédiatement.

---

## 🛠️ Déploiement

Le `docker-compose.yml` orchestre quatre services : `postgres`, `redis`, `backend` (FastAPI) et `frontend` (nginx avec proxy `/api`). Pour la production :

1. Renseignez les vraies clés dans `backend/.env`.
2. Définissez `API_KEY` pour protéger les endpoints.
3. Restreignez `allow_origins` dans `backend/main.py` à votre domaine.
4. Passez nginx derrière HTTPS (reverse proxy / Caddy / Traefik).

---

## 📁 Structure du projet

```
churn-ai/
├── backend/
│   ├── agents/          # Les 7 agents (data, analysis, prediction, decision, action, finance, ceo)
│   ├── api/routes.py    # Endpoints FastAPI
│   ├── db/              # Modèles SQLAlchemy + helpers
│   ├── auth.py          # Authentification X-API-Key
│   ├── scheduler.py     # Rapport hebdomadaire (APScheduler)
│   └── main.py          # Point d'entrée FastAPI
├── frontend/
│   ├── index.html       # Landing page
│   └── app.html         # Dashboard multi-agents
├── docker/nginx.conf
├── docker-compose.yml
└── setup_agents.py      # Provisionne les Managed Agents Claude
```

---

## 🤝 Contribuer

Les contributions sont les bienvenues — voir [CONTRIBUTING.md](CONTRIBUTING.md). Ouvrez une *issue* pour discuter d'un changement majeur avant de soumettre une *pull request*.

## 📄 Licence

Distribué sous licence **MIT**. Voir [LICENSE](LICENSE).
