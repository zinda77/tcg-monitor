# TCG Monitor v2 — Pokémon & One Piece

> **Installation automatique** : ouvre ce dossier dans Claude Code et écris
> « Suis les instructions de SETUP_CLAUDE_CODE.md ». Il fera tout avec toi, étape par étape.

Alertes Discord en ~30 secondes pour les nouveautés et restocks, avec pour chaque produit :
franchise, type, image, prix boutique, revente estimée, marge nette, lien d'ajout au panier
(boutiques Shopify) et liens pour vérifier la revente (eBay vendus, Vinted, Cardmarket).

Trois façons de surveiller, toutes dans `config.yaml` :
- `watch_pages` : pages de recherche des enseignes (Fnac, Cultura, Micromania...) → nouvelles fiches produit ;
- `shopify_stores` : boutiques Shopify scannées en entier → nouveautés + restocks + ajout au panier ;
- `products` : un produit précis → alerte dès qu'il repasse en stock.

Commandes utiles : `python monitor.py --diagnose` (teste chaque site) et `python monitor.py --test-alert`.

---

## Étape 1 — Webhook Discord (2 min)
1. Dans Discord : bouton **+** → **Créer mon serveur** → « Pour moi et mes amis ».
2. Crée un salon `#alertes-tcg` → roue crantée → **Intégrations** → **Webhooks** → **Nouveau webhook** → **Copier l'URL**.
3. Sur ton téléphone : notifications du salon → **Tous les messages**.

## Étape 2 — Clés eBay pour l'estimation de revente (10 min, gratuit, optionnel)
1. Crée un compte sur **developer.ebay.com** (avec ton compte eBay habituel).
2. **Application Keys** → crée un jeu de clés **Production** : note l'**App ID (Client ID)** et le **Cert ID (Client Secret)**.
3. eBay te demandera une option sur les « notifications de suppression de compte » : choisis l'**exemption** (le script ne stocke pas de données d'utilisateurs eBay).

Sans ces clés, le script marche quand même : il utilisera tes prix de référence de `config.yaml`.

## Étape 3 — Hébergement gratuit sur GitHub (10 min, sans carte bancaire)
1. Crée un compte sur github.com puis un **nouveau dépôt public** `tcg-monitor` (public = minutes illimitées).
2. Envoie tous les fichiers du dossier, y compris `.github/workflows/monitor.yml`.
3. **Settings → Secrets and variables → Actions → New repository secret** : ajoute
   `DISCORD_WEBHOOK_URL`, et si tu les as `EBAY_CLIENT_ID` et `EBAY_CLIENT_SECRET`.
   Ces secrets restent privés même si le dépôt est public.
4. Onglet **Actions** → active les workflows → **TCG Monitor → Run workflow** pour tester.

Le script tourne alors toutes les 5 minutes environ, 24 h/24, ton Mac éteint.

**Option plus rapide, toujours gratuite** : un vieux téléphone Android branché sur secteur chez toi, avec l'app
Termux, peut faire tourner `python monitor.py --loop 30` (un passage toutes les 30 s). Dans ce cas, désactive le
workflow GitHub pour éviter les doublons. (`install_server.sh` sert uniquement si tu passes un jour sur un vrai serveur Linux.)

## Au quotidien
- **Ajouter une boutique ou un produit** : modifie `config.yaml` sur GitHub (icône crayon), même depuis ton téléphone. C'est pris en compte au passage suivant.
- **Nouvelle boutique** : au premier passage, le script mémorise le catalogue sans t'alerter. Ensuite, chaque nouveau produit ou restock déclenche une alerte.
- **Voir ce que fait le monitoring** : onglet **Actions** du dépôt, clique sur le dernier passage.

## À savoir
- **L'estimation de revente est indicative** : elle se base sur les prix demandés sur eBay.fr (on retient le quart le plus bas, plus réaliste que la moyenne), pas sur les ventes conclues. Avant d'acheter en volume, clique sur « Ventes eBay conclues » et « Cardmarket » dans l'alerte.
- **Cardmarket** bloque la lecture automatique et réserve son API aux vendeurs : c'est pour ça que l'alerte donne un lien direct plutôt qu'un prix.
- **Pokémon Center, Amazon, parfois Fnac** bloquent les robots : garde les Discords communautaires pour ces sites.
- **Délai GitHub** : 5 minutes minimum, et GitHub décale parfois les passages de quelques minutes aux heures chargées.
- **Usage de GitHub Actions** : le service est prévu pour les projets logiciels. Un petit script toutes les 5 minutes passe en général sans souci, mais n'essaie pas de le faire tourner en boucle permanente dessus.
