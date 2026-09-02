# Pont d’accès Sostagora → ClimaFlora Plus

## Règle fonctionnelle

Tout utilisateur WordPress dont le méta `sa_sostagora_access` vaut `sostagora` ou
`sostagora_elite` reçoit ClimaFlora Plus. L’avantage Sostagora est indépendant de
Stripe : un abonnement ClimaFlora Pro actif reste prioritaire ; à sa fin, le client
Sostagora revient à Plus au lieu de repasser en Découverte.

## Connexion

1. Le client choisit « Activer ClimaFlora Plus » dans ClimaFlora ou utilise le
   shortcode WordPress `[climaflora_sostagora_link]`.
2. WordPress vérifie sa session et son accès Sostagora.
3. WordPress crée un code aléatoire à usage unique, conservé 120 secondes.
4. Le navigateur transmet le code au backend ClimaFlora.
5. Le backend consomme le code auprès de WordPress, lie l’adresse au compte
   Supabase et produit un lien de connexion Supabase à usage unique.
6. Supabase établit la session ClimaFlora et les RLS reconnaissent le droit Plus.

Aucun mot de passe WordPress, cookie WordPress, secret Supabase privilégié ou
adresse e-mail n’est transmis au navigateur par le backend. La table de liaison ne
conserve qu’un SHA-256 normalisé de l’adresse.

## Révocation

Le plugin écoute les modifications de `sa_sostagora_access`, puis synchronise les
ajouts et retraits vers le backend avec plusieurs tentatives WordPress Cron. Lors
de chaque échange, l’accès est relu depuis WordPress : un ancien code ne peut donc
pas réactiver un droit qui vient d’être retiré.

## Déploiement WordPress manuel

Téléverser `climaflora-sostagora-bridge/` dans `/wp-content/plugins/`, puis activer
« ClimaFlora — Pont Sostagora ». Le diagnostic public doit répondre sur :

`https://shugoan.com/wp-json/climaflora/v1/status`

Le plugin ne nécessite aucun secret supplémentaire.
