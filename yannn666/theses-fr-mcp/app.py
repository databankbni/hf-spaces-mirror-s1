"""Interface Gradio + MCP pour interroger l'API Solr de theses.fr."""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import requests
import gradio as gr

API_URL = "https://theses.fr/api/v1/theses/recherche/"

TRI_CHOICES = [
    "pertinence",
    "dateAsc",
    "dateDesc",
    "auteursAsc",
    "auteursDesc",
    "disciplineAsc",
    "disciplineDesc",
]

STATUT_CHOICES = ["Tous", "soutenue", "enCours"]


def _personnes(liste):
    if not liste:
        return "-"
    return ", ".join(f"{p.get('prenom') or ''} {p.get('nom') or ''}".strip() for p in liste if p.get("nom"))


def search_theses(
    q: str,
    nombre: int = 10,
    debut: int = 0,
    tri: str = "pertinence",
    statut: str = "Tous",
) -> str:
    """Recherche des theses sur theses.fr via l'API officielle (moteur Solr).

    Args:
        q: Termes de recherche (titre, auteur, discipline, mots-cles...). Supporte AND, OR, AND NOT.
        nombre: Nombre de resultats a retourner (max recommande: 50).
        debut: Index du premier resultat (pour la pagination).
        tri: Ordre de tri des resultats. Valeurs possibles: pertinence, dateAsc, dateDesc,
            auteursAsc, auteursDesc, disciplineAsc, disciplineDesc.
        statut: Filtrer par statut de la these: "Tous", "soutenue" (deja soutenue) ou "enCours".

    Returns:
        Un texte Markdown listant les theses trouvees (titre, auteur, directeur, etablissement,
        discipline, statut, date de soutenance, lien vers la fiche theses.fr).
    """
    if not q or not q.strip():
        return "Merci de saisir une requete de recherche."

    query = q.strip()
    if statut and statut != "Tous":
        query = f"{query} AND status:({statut})"

    params = {
        "q": query,
        "nombre": max(1, min(int(nombre or 10), 50)),
        "debut": max(0, int(debut or 0)),
        "tri": tri or "pertinence",
    }

    try:
        resp = requests.get(API_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        return f"Erreur lors de l'appel a l'API theses.fr : {e}"
    except ValueError:
        return "Erreur : reponse de l'API illisible (JSON invalide)."

    total = data.get("totalHits", 0)
    theses = data.get("theses", [])

    if not theses:
        return f"Aucun resultat pour la requete `{q}` (0 / {total})."

    lines = [f"**{total} resultat(s)** pour `{q}` — affichage de {len(theses)} (a partir de #{params['debut']})\n"]

    for t in theses:
        titre = t.get("titrePrincipal") or t.get("titreEN") or "(titre inconnu)"
        auteurs = _personnes(t.get("auteurs"))
        directeurs = _personnes(t.get("directeurs"))
        etab = t.get("etabSoutenanceN") or "-"
        discipline = t.get("discipline") or "-"
        statut_t = t.get("status") or "-"
        date_soutenance = t.get("dateSoutenance") or "-"
        these_id = t.get("id")
        lien = f"https://theses.fr/{these_id}" if these_id else None

        lines.append(f"### {titre}")
        lines.append(f"- **Auteur·e** : {auteurs}")
        lines.append(f"- **Directeur·rice(s)** : {directeurs}")
        lines.append(f"- **Etablissement** : {etab}")
        lines.append(f"- **Discipline** : {discipline}")
        lines.append(f"- **Statut** : {statut_t} — **Soutenance** : {date_soutenance}")
        if lien:
            lines.append(f"- **Fiche** : {lien}")
        lines.append("")

    return "\n".join(lines)


demo = gr.Interface(
    fn=search_theses,
    inputs=[
        gr.Textbox(label="Recherche", placeholder="ex: intelligence artificielle AND discipline:(informatique)"),
        gr.Slider(label="Nombre de resultats", minimum=1, maximum=50, value=10, step=1),
        gr.Number(label="Debut (pagination)", value=0, precision=0),
        gr.Dropdown(label="Tri", choices=TRI_CHOICES, value="pertinence"),
        gr.Dropdown(label="Statut", choices=STATUT_CHOICES, value="Tous"),
    ],
    outputs=gr.Markdown(label="Resultats"),
    title="theses.fr — recherche",
    description=(
        "Interroge l'API officielle de theses.fr (moteur Solr) : "
        "https://theses.fr/api/v1/theses/recherche/"
    ),
    api_name="search_theses",
)

if __name__ == "__main__":
    demo.launch(mcp_server=True)
