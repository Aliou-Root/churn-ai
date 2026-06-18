# Contribuer à ChurnAI

Merci de votre intérêt ! Ce document décrit comment proposer des changements.

## Workflow

1. **Forkez** le dépôt et créez une branche depuis `main` :
   ```bash
   git checkout -b feat/ma-fonctionnalite
   ```
2. Faites vos modifications en respectant le style existant.
3. Vérifiez que le backend démarre et que le pipeline tourne (`POST /api/v1/act` avec `dry_run: true`).
4. Committez avec un message clair, puis ouvrez une **pull request** vers `main`.

> Le dépôt est public en lecture seule : seuls les mainteneurs peuvent pousser sur `main`.
> Toute contribution passe par une pull request depuis un fork ou une branche.

## Style de code

- **Python** : suivez les conventions de la base (type hints, docstrings, logging structuré). `ruff` est recommandé.
- **Frontend** : HTML/CSS/JS vanilla, single-file, fidèle au design system existant (variables CSS, polices Syne + JetBrains Mono).

## Signaler un bug

Ouvrez une *issue* en décrivant :
- le comportement attendu vs observé,
- les étapes de reproduction,
- l'environnement (OS, version de Python, Docker ou local).

## Sécurité

Ne committez jamais de secrets. Si vous découvrez une vulnérabilité, ouvrez une issue **sans** divulguer de détails exploitables publiquement, ou contactez directement le mainteneur.
