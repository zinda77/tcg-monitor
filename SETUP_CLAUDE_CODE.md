# Mission Claude Code : installer le TCG Monitor de Romain

Tu es dans le dossier du projet `tcg-monitor` sur le MacBook de Romain. Objectif : un monitoring qui tourne
24 h/24 gratuitement via GitHub Actions (toutes les 5 min, sans carte bancaire) et envoie ses alertes sur son Discord.
Lis `README.md` et `monitor.py` avant de commencer. Parle en français, explique chaque étape simplement,
et demande confirmation avant toute action qui crée, publie ou envoie quelque chose.

## Règles
- Ne demande JAMAIS de mot de passe, de code de carte bancaire ou de code 2FA. Romain crée lui-même ses comptes
  (GitHub, eBay Developers) et s'authentifie lui-même (ex. `gh auth login` dans le navigateur).
- Le webhook Discord et les clés eBay ne doivent jamais être commités : ils vont uniquement dans `.env`
  (déjà dans `.gitignore`) sur le Mac pour les tests, puis dans les secrets GitHub.
- Pas de contournement des protections anti-robots (captchas, proxies résidentiels, etc.) : si un site bloque,
  on le note et on passe à autre chose.
- Intervalle minimum entre deux passages : 30 s.

## Étapes
1. **Prérequis Mac** : vérifie `python3`, `git`, et installe `gh` (GitHub CLI) via Homebrew si besoin (demande avant).
2. **Environnement local** : `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
3. **Discord** : guide Romain pour créer un serveur privé + webhook (README étape 1). Il te colle l'URL ;
   écris-la dans `.env` (`DISCORD_WEBHOOK_URL=...`), puis lance
   `set -a; source .env; set +a; .venv/bin/python monitor.py --test-alert` et fais-lui confirmer la réception.
4. **eBay (optionnel)** : guide-le pour obtenir ses clés Production (README étape 2) et ajoute-les dans `.env`.
5. **Valider les sites** : lance `.venv/bin/python monitor.py --diagnose`.
   - Pour chaque ⚠️ : ouvre le site, trouve la bonne URL de page de recherche, corrige `watch_pages` dans
     `config.yaml`, relance le diagnostic.
   - Pour chaque 🛒 Shopify : déplace la boutique dans `shopify_stores`.
   - Les ❌ (bloqués) : laisse-les commentés avec la mention « bloqué », sans chercher à contourner.
   - Fais un récapitulatif clair à Romain : ce qui marche, ce qui ne marche pas.
6. **GitHub** : après `gh auth login` fait par Romain, crée un dépôt public `tcg-monitor`, commit et push
   (y compris `.github/workflows/monitor.yml`). Vérifie qu'aucun secret n'est dans le dépôt.
7. **Secrets** : ajoute les valeurs de `.env` avec `gh secret set DISCORD_WEBHOOK_URL` (et les clés eBay si présentes),
   sans les afficher dans le terminal ni dans tes messages.
8. **Vérification** : `gh workflow run "TCG Monitor"`, puis `gh run watch` et lis les logs. Les sites qui passent
   depuis le Mac peuvent être bloqués depuis les serveurs GitHub : désactive dans `config.yaml` ce qui échoue,
   push, et relance un passage. Rappelle à Romain que le premier passage initialise sans alerter.
9. **Fin** : résume à Romain ce qui tourne, comment ajouter un produit (modifier `config.yaml` sur GitHub),
   et comment consulter les logs (onglet Actions).
