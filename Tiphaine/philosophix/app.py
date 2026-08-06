import gradio as gr
import random
import os
import urllib.request
import datetime
from gensim.models import KeyedVectors
import fr_core_news_md

# --- 1. CHARGEMENT DU MODÈLE (Simplifié) ---
def charger_modele():
    nom_fichier = "fr_wac.bin"
    if os.path.exists(nom_fichier):
        print("✅ Fichier modèle trouvé ! Chargement...")
        try:
            modele = KeyedVectors.load_word2vec_format(nom_fichier, binary=True, limit=500000)
            nlp = fr_core_news_md.load()
            return modele, nlp
        except Exception as e:
            print(f"⚠️ ERREUR DE LECTURE : {e}")
            return None, None
    else:
        print("⚠️ ERREUR : Fichier fr_wac.bin introuvable !")
        return None, None

modele, nlp = charger_modele()

# --- 2. DONNÉES DU JEU (PHILOSOPHIX) ---
DONNEES_JEU = {
    "ANTIQUITE": (["antique", "grec", "romain", "sagesse", "agora", "athenes", "maitre", "disciple", "stoicisme", "epicurisme", "socratique"], ["thalès", "anaximandre", "pythagore", "héraclite", "parménide", "zénon", "empédocle", "anaxagore", "démocrite", "protagoras", "gorgias", "socrate", "platon", "aristote", "diogène", "pyrrhon", "epicure", "sénèque", "epictète", "marc-aurèle", "plotin", "cicéron", "lucrèce"]),
    "MOYEN_AGE_RENAISSANCE": (["dieu", "religion", "théologie", "foi", "politique", "prince", "utopie", "scolastique", "chrétien", "église"], ["augustin", "boèce", "averroès", "avicenne", "anselme", "abélard", "thomas", "aquin", "ockham", "erasme", "machiavel", "more", "montaigne", "bodin", "bruno"]),
    "CLASSIQUES_LUMIERES": (["raison", "lumières", "doute", "cogito", "contrat", "social", "nature", "liberté", "esprit", "loi", "empirisme", "rationalisme"], ["bacon", "descartes", "hobbes", "gassendi", "pascal", "spinoza", "locke", "malebranche", "leibniz", "bayle", "berkeley", "montesquieu", "voltaire", "hume", "rousseau", "diderot", "condillac", "helvétius", "holbach", "smith", "kant", "burke"]),
    "MODERNES_XIX": (["histoire", "volonté", "dialectique", "révolution", "capitalisme", "prolétariat", "surhomme", "inconscient", "idéalisme", "nihilisme"], ["fichte", "sade", "hegel", "schelling", "schopenhauer", "comte", "feuerbach", "mill", "kierkegaard", "marx", "engels", "spencer", "nietzsche", "freud", "durkheim", "bergson", "husserl", "james", "dewey"]),
    "CONTEMPORAINS": (["existentialisme", "phénoménologie", "structure", "langage", "pouvoir", "genre", "déconstruction", "absurde", "analytique", "éthique"], ["heidegger", "sartre", "beauvoir", "camus", "merleau-ponty", "levinas", "bachelard", "canguilhem", "lacan", "althusser", "barthes", "foucault", "deleuze", "derrida", "bourdieu", "lyotard", "baudrillard", "ricoeur", "jankélévitch", "weil", "arendt", "benjamin", "adorno", "horkheimer", "habermas", "honneth", "frege", "russell", "moore", "wittgenstein", "carnap", "popper", "quine", "austin", "searle", "rawls", "rorty", "putnam", "nozick", "singer", "chomsky", "turing", "zizek", "badiou", "rancière", "onfray", "ferry", "serres", "latour", "descola", "butler"])
}

# --- 2b. BOOSTERS SPÉCIFIQUES ---
BOOSTERS_PERSO = {
    "singer": ["animal", "animaux", "utilitarisme", "éthique", "moral", "libération", "antispécisme", "souffrance"],
    "marx": ["capital", "lutte", "classe", "communisme", "prolétaire", "prolétariat", "révolution", "marxisme", "économie"],
    "freud": ["rêve", "inconscient", "psychanalyse", "sexuel", "pulsion", "libido", "moi", "ça", "surmoi", "oedipe"],
    "sartre": ["nausée", "huis", "clos", "existentialisme", "engagé", "être", "néant", "enfer", "autrui"],
    "beauvoir": ["sexe", "femme", "feminisme", "genre", "deuxième", "mémoires"],
    "platon": ["caverne", "idée", "république", "banquet", "socrate", "mythe", "athenes", "académie", "idéalisme"],
    "aristote": ["logique", "éthique", "nicomaque", "politique", "métaphysique", "lycée", "poétique", "animal"],
    "socrate": ["maïeutique", "poison", "ciguë", "connais", "toi", "dialogue", "procès"],
    "descartes": ["méthode", "doute", "cogito", "je", "pense", "suis", "raison", "dualisme", "méditations"],
    "nietzsche": ["dieu", "mort", "surhomme", "zarathoustra", "gai", "savoir", "volonté", "puissance", "morale", "nihilisme"],
    "kant": ["critique", "pure", "pratique", "impératif", "moral", "catégorique", "lumières", "raison", "idéalisme"],
    "rousseau": ["contrat", "social", "inégalité", "promeneur", "solitaire", "éducation", "emile", "nature"],
    "pascal": ["pari", "pensées", "roseau", "pensant", "coeur", "raison", "géométrie", "finesse"],
    "spinoza": ["éthique", "dieu", "nature", "joie", "tristesse", "conatus", "substance", "panthéisme"],
    "montaigne": ["essais", "sais", "scepticisme", "amitié", "boétie"],
    "machiavel": ["prince", "politique", "rusé", "lion", "renard", "florence", "pouvoir"],
    "camus": ["étranger", "peste", "sisyphe", "absurde", "révolte", "chute"],
    "foucault": ["surveiller", "punir", "histoire", "folie", "sexualité", "biopolitique", "pouvoir", "savoir"],
    "deleuze": ["rhizome", "différence", "répétition", "anti", "oedipe", "cinéma", "pli"],
    "derrida": ["déconstruction", "grammatologie", "différance", "écriture"],
    "hegel": ["dialectique", "esprit", "phénoménologie", "maître", "esclave", "histoire"],
    "leibniz": ["monade", "monadologie", "meilleur", "mondes", "théodicée", "calcul"],
    "hobbes": ["léviathan", "loup", "homme", "état", "nature", "guerre"],
    "locke": ["entendement", "humain", "tolérance", "gouvernement", "empirisme", "tabula", "rasa"],
    "hume": ["traité", "nature", "humaine", "empirisme", "causalité", "habitude"],
    "bergson": ["rire", "durée", "élan", "vital", "conscience", "temps", "mémoire"],
    "arendt": ["banalité", "mal", "totalitarisme", "condition", "moderne", "eichmann"],
    "wittgenstein": ["tractatus", "logico", "philosophicus", "jeux", "langage", "silence"],
    "popper": ["falsifiabilité", "réfutation", "société", "ouverte", "science"],
    "bourdieu": ["habitus", "capital", "culturel", "distinction", "domination", "masculine", "sociologie"],
    "épicure": ["jardin", "plaisir", "bonheur", "lettre", "ménécée", "atome"],
    "diogène": ["tonneau", "cynique", "chien", "lampe", "homme"],
    "marc-aurèle": ["pensées", "moi", "stoïcisme", "empereur"],
    "sénèque": ["vie", "brève", "lettres", "lucilius", "colère", "stoïcisme"],
    "augustin": ["confessions", "cité", "dieu", "temps", "mémoire", "mal"],
    "rawls": ["justice", "voile", "ignorance", "équité", "libéralisme", "politique"]
}

# --- 3. PRÉPARATION ---
candidats_valides = []
print("🔍 Vérification de la liste des philosophes...")
if modele:
    for cat, (boosts, noms) in DONNEES_JEU.items():
        count_cat = 0
        for nom in noms:
            nom_clean = nom.strip().lower()
            if nom_clean in modele:
                candidats_valides.append((nom, cat))
                count_cat += 1
        print(f"   -> {cat} : {count_cat} philosophes valides.")
    candidats_valides.sort(key=lambda x: x[0])
    print(f"✅ LISTE FINALE : {len(candidats_valides)} philosophes jouables.")
else:
    print("❌ MODELE NON CHARGÉ (Assurez-vous d'avoir uploadé fr_wac.bin dans Files)")

# --- 4. LOGIQUE DU JEU (AVEC HIER) ---
def get_daily_data():
    if not candidats_valides:
        return "Erreur", "Aucune", "Erreur"
        
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    paris_now = utc_now + datetime.timedelta(hours=1)
    date_today = paris_now.date()
    
    playlist = list(candidats_valides)
    rng_mix = random.Random(2025) 
    rng_mix.shuffle(playlist)
    
    date_ref = datetime.date(2024, 1, 1)
    delta_jours = (date_today - date_ref).days
    
    # Aujourd'hui
    index_du_jour = delta_jours % len(playlist)
    selection = playlist[index_du_jour]
    
    # Hier (on recule de 1)
    index_hier = (delta_jours - 1) % len(playlist)
    selection_hier = playlist[index_hier]
    
    return selection[0], selection[1], selection_hier[0]

def demarrer_partie():
    mot_du_jour, categorie_du_jour, mot_hier = get_daily_data()
    date_str = datetime.date.today().strftime("%d/%m/%Y")
    
    # Message pour l'affichage
    if mot_hier == "Erreur":
        msg_hier = ""
    else:
        msg_hier = f"📜 Le philosophe d'hier était : **{mot_hier.upper()}**"
    
    return mot_du_jour, categorie_du_jour, [], f"🦉 Philosophe du {date_str}", "JEU", msg_hier

def preparer_texte_partage(hist):
    nb_coups = len(hist)
    date_str = datetime.date.today().strftime("%d/%m/%Y")
    if hist and hist[0][2] == "1000":
        return f"🦉 Philosophix du Jour ({date_str})\nJ'ai trouvé le philosophe mystère en {nb_coups} coups !\n👉 https://huggingface.co/spaces/Tiphaine/philosophix"
    return "Pas encore trouvé ! Continue de chercher 😉"

def jouer(mot_joueur, secret_data, historique):
    mot_secret = secret_data[0]
    cat_secret = secret_data[1]
    
    texte_partage_actuel = "Continue de chercher..."

    if modele is None: return historique, "❌ Erreur modèle", "ERREUR", texte_partage_actuel
    if not mot_joueur: return historique, "❌ Écris un mot !", "ERREUR", texte_partage_actuel

    if mot_joueur.strip().lower() == "solution":
        return historique, f"🛑 La réponse est : {mot_secret}", "PERDU", texte_partage_actuel

    doc = nlp(mot_joueur)
    mots_utiles = [t for t in doc if not t.is_stop and not t.is_punct]
    
    if not mots_utiles:
        return historique, "❌ Inconnu.", "ERREUR", texte_partage_actuel
        
    clean_mot = mots_utiles[0].text.lower()
    lemme_mot = mots_utiles[0].lemma_.lower()
    
    for h in historique:
        if h[1].lower() == clean_mot:
            return historique, f"⚠️ Déjà joué : {clean_mot}", "JEU", preparer_texte_partage(historique)

    score = 0.0
    
    # VICTOIRE
    if clean_mot == mot_secret.lower():
        historique.insert(0, ["🥳", clean_mot.capitalize(), "1000"])
        return historique, f"🥳 BRAVO ! C'était {mot_secret.upper()} !", "VICTOIRE", preparer_texte_partage(historique)

    if clean_mot not in modele:
         return historique, f"❓ Inconnu : '{clean_mot}'", "ERREUR", texte_partage_actuel

    if mot_secret.lower() in modele:
        raw_score = modele.similarity(mot_secret.lower(), clean_mot)
        # Calibrage généreux
        score = raw_score * 1000 * 1.6
        if score > 990: score = 990
    
    # BOOST CATÉGORIE
    if cat_secret in DONNEES_JEU:
        mots_cles_cat = DONNEES_JEU[cat_secret][0]
        if clean_mot in mots_cles_cat or lemme_mot in mots_cles_cat:
            boost = random.uniform(800.0, 900.0)
            score = max(score, boost)

    # BOOST SPÉCIFIQUE
    secret_lower = mot_secret.lower()
    if secret_lower in BOOSTERS_PERSO:
        mots_adn = BOOSTERS_PERSO[secret_lower]
        if clean_mot in mots_adn or lemme_mot in mots_adn:
            boost_perso = random.uniform(850.0, 950.0)
            score = max(score, boost_perso)

    score_final = int(score)
    if score_final < 0: score_final = 0
    
    # BARÈME
    emoji = "❄️"
    if score_final > 100: emoji = "😎"
    if score_final > 300: emoji = "🔥"
    if score_final > 500: emoji = "🥵"
    if score_final > 900: emoji = "😱" # AJOUT DU PALIER 900
    
    historique.append([emoji, clean_mot.capitalize(), str(score_final)])
    historique = sorted(historique, key=lambda x: int(x[2]), reverse=True)
    
    # MODIFICATION ICI : Affichage score immédiat
    message_feedback = f"Ton mot : {clean_mot.capitalize()} {emoji} ({score_final})"
    
    return historique, message_feedback, "JEU", preparer_texte_partage(historique)

# --- 5. INTERFACE GRADIO ---

custom_css = """
/* 1. FOND DE L'APPLICATION */
.gradio-container { 
    background: linear-gradient(135deg, #fdfbf7 0%, #eff6ff 100%) !important; 
}

/* 2. RENDRE TRANSPARENTS TOUS LES FONDS PARASITES */
.gradio-container .prose, 
.gradio-container .markdown, 
.gradio-container .accordion, 
.gradio-container .gap,
.gradio-container div {
    background-color: transparent !important;
    background: transparent !important;
    border-color: transparent !important;
}

/* 3. FORCER LE TEXTE EN BLEU FONCÉ (Y COMPRIS LISTES & CHIFFRES) */
.gradio-container p, 
.gradio-container span, 
.gradio-container label, 
.gradio-container h2, 
.gradio-container h3, 
.gradio-container strong,
.gradio-container ul,
.gradio-container li,
#subtitle,
.accordion span,
code, pre {
    color: #1e3a8a !important; /* Bleu nuit */
    text-shadow: none !important;
    background: transparent !important;
    border: none !important;
}

/* 4. LE TITRE PRINCIPAL */
h1 { 
    font-family: 'Arial Rounded MT Bold', sans-serif; 
    color: #2563eb !important; 
    text-align: center; 
    font-size: 2.5em !important; 
    margin-bottom: 0px !important; 
}

/* 5. LA BARRE DE RECHERCHE */
.search-input textarea { 
    background-color: white !important; 
    border-radius: 50px !important; 
    border: 3px solid #3b82f6 !important; 
    box-shadow: 0 4px 10px rgba(59, 130, 246, 0.2) !important; 
    font-size: 1rem !important; 
    padding: 12px 15px !important; 
    text-align: center; 
    color: #1e3a8a !important; 
}

/* 6. LES BOUTONS */
#btn-envoyer { 
    border-radius: 50px !important; 
    background-image: linear-gradient(to right, #2563eb, #06b6d4) !important; 
    border: none !important; 
    color: white !important; 
    font-weight: bold !important; 
    font-size: 1.2rem !important; 
}
#btn-share { 
    background-color: #10b981 !important; 
    color: white !important; 
    border-radius: 15px !important; 
    font-weight: bold; 
    margin-top: 15px; 
}

/* 7. LE TABLEAU */
.dataframe { 
    background-color: white !important; 
    border-radius: 15px !important; 
    overflow: hidden !important; 
    border: 2px solid #e5e7eb !important; 
}
thead tr th { 
    background-color: #f3f4f6 !important; 
    color: #1e3a8a !important; 
    font-weight: bold !important; 
}
tbody tr td {
    background-color: white !important; 
    color: #374151 !important; 
}
"""

html_confetti_loader = """
<div id="confetti-loader" style="display:none;"></div>
<script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.6.0/dist/confetti.browser.min.js"></script>
"""

js_share = """async (text_to_share) => {
    if (!text_to_share) return;
    try {
        if (navigator.share) {
            await navigator.share({ title: 'Philosophix', text: text_to_share });
            return;
        }
    } catch (err) { console.log(err); }
    try {
        await navigator.clipboard.writeText(text_to_share);
        alert('Résultat copié dans le presse-papier ! 📋');
    } catch (err) {
        const el = document.createElement('textarea');
        el.value = text_to_share;
        document.body.appendChild(el);
        el.select();
        document.execCommand('copy');
        document.body.removeChild(el);
        alert('Résultat copié ! 📋');
    }
}"""

with gr.Blocks(title="Philosophix") as demo:
    gr.HTML(html_confetti_loader)
    
    gr.HTML("<h1 style='margin-bottom: 10px;'>🦉 Philosophix</h1>")
    gr.Markdown("**Le Défi Philo du Jour** • Un penseur unique à trouver !", elem_id="subtitle")
    
    # Affichage du mot d'hier
    lbl_hier = gr.Markdown(visible=True)
    
    with gr.Accordion("❓ Comment jouer ? (Clique ici)", open=False):
        gr.Markdown("""
        **Un seul Philosophe par jour !** (à minuit)
        
        **Les indices :** Tape un concept ou un nom pour voir s'il est proche.
        
        **Le Barème :**
        * ❄️ **Froid** : Tu es très très loin.
        * 😎 **Tiède** : Tu t'approches (> 100).
        * 🔥 **Chaud** : On supporte encore la petite laine (> 300).
        * 🥵 **Brûlant** : Tu brûles, fais gaffe ! (> 500).
        * 😱 **Incroyable** : Tu es VRAIMENT tout près (> 900) !
        * 🥳 **VICTOIRE** : Tu as trouvé ! (1000).
        
        **Astuce :** Cherche l'époque (Antique, Moderne...), le courant (Stoïcisme, Lumières...) ou des concepts clés (Liberté, Dieu...).
        """)

    secret_state = gr.State()
    history_state = gr.State([])
    status_state = gr.State("JEU")
    
    txt_share_content_hidden = gr.Textbox(visible=False, value="")
    
    with gr.Row():
        txt_input = gr.Textbox(show_label=False, placeholder="Tape un mot ou un penseur...", scale=4, elem_classes=["search-input"])
        btn_submit = gr.Button("GO !", scale=1, elem_id="btn-envoyer")
    
    lbl_message = gr.Label(value="Prêt à penser ?", show_label=False)
    
    btn_share = gr.Button("📤 Partager mon exploit", elem_id="btn-share", visible=True)

    tableau = gr.Dataframe(headers=["🌡️", "Mot", "Score"], datatype=["str", "str", "str"], value=[], interactive=False)
    gr.Markdown(f"ℹ️ *Bibliothèque : {len(candidats_valides)} philosophes chargés.*")

    def wrapper_jouer(mot, secret, hist):
        h, msg, st, share_txt = jouer(mot, secret, hist)
        return gr.update(value=""), h, msg, h, st, share_txt

    def init_game():
        mot, cat, hist, msg, st, msg_hier = demarrer_partie()
        return [mot, cat], hist, [], msg, st, "", msg_hier

    txt_input.submit(wrapper_jouer, [txt_input, secret_state, history_state], [txt_input, history_state, lbl_message, tableau, status_state, txt_share_content_hidden])
    btn_submit.click(wrapper_jouer, [txt_input, secret_state, history_state], [txt_input, history_state, lbl_message, tableau, status_state, txt_share_content_hidden])
    
    btn_share.click(None, [txt_share_content_hidden], None, js=js_share)

    demo.load(init_game, inputs=None, outputs=[secret_state, history_state, tableau, lbl_message, status_state, txt_share_content_hidden, lbl_hier])

    # --- FOOTER : LIENS VERS LES AUTRES JEUX ---
    with gr.Row():
        gr.HTML("""
        <div style="text-align:center; margin-top: 20px; color: #666; font-size: 0.9em;">
            Besoin d'une pause plus légère ?<br>
            🏠 <a href="https://huggingface.co/spaces/Tiphaine/Objetix" target="_blank" style="color: #2c3e50; text-decoration: none; font-weight: bold;">Objetix</a> (Objets cachés) 
            &nbsp;•&nbsp; 
            🧠 <a href="https://huggingface.co/spaces/Tiphaine/culturix" target="_blank" style="color: #2c3e50; text-decoration: none; font-weight: bold;">Culturix</a> (Culture G)
        </div>
        """)

demo.launch(css=custom_css)