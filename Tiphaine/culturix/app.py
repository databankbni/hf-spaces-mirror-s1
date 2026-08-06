import gradio as gr
import random
import os
import urllib.request
import datetime
from gensim.models import KeyedVectors
import fr_core_news_md

# --- 1. CHARGEMENT DU MODÈLE ---
def charger_modele():
    nom_fichier = "fr_wac.bin"
    if os.path.exists(nom_fichier):
        print("✅ Fichier modèle trouvé localement !")
    else:
        print("⚠️ Fichier non trouvé. Tentative de téléchargement...")
        url_modele = "https://embeddings.net/embeddings/frWac_no_postag_phrase_500_cbow_cut100.bin"
        try:
            opener = urllib.request.build_opener()
            opener.addheaders = [('User-agent', 'Mozilla/5.0')]
            urllib.request.install_opener(opener)
            urllib.request.urlretrieve(url_modele, nom_fichier)
            print("Téléchargement réussi !")
        except Exception as e:
            print(f"⚠️ ERREUR : {e}")
            return None, None

    print("Chargement des vecteurs... (Patientez)")
    try:
        modele = KeyedVectors.load_word2vec_format(nom_fichier, binary=True, limit=500000)
        nlp = fr_core_news_md.load()
        return modele, nlp
    except Exception as e:
        print(f"⚠️ ERREUR DE CHARGEMENT : {e}")
        return None, None

modele, nlp = charger_modele()

# --- 2. DONNÉES DU JEU (CULTURIX) ---
DONNEES_JEU = {
    "MYTHO_GRECO": (["olympe", "antique", "grec", "mythologie", "temple", "foudre", "troie", "héros", "tragédie", "dieu"], ["zeus", "jupiter", "apollon", "vénus", "aphrodite", "hercule", "ulysse", "achille", "poséidon", "hades", "athena", "artémis", "icare", "oedipe", "antigone", "prométhée", "atlas"]),
    "MYTHO_NORD": (["nord", "viking", "asgard", "valhalla", "marteau", "mythologie", "scandinave", "froid", "dieu"], ["thor", "odin", "loki"]),
    "MYTHO_EGYPT": (["égypte", "pharaon", "pyramide", "nil", "mythologie", "tombeau", "momie", "sarcophage", "sphinx", "divinité"], ["anubis", "osiris", "horus"]),
    "LEGENDES": (["graal", "table", "ronde", "chevalier", "épée", "excalibur", "légende", "moyen", "âge", "magie", "enchanteur"], ["merlin", "arthur", "lancelot"]),
    "BD_FRANCO_BELGE": (["bande", "dessinée", "bd", "album", "bulle", "planche", "belge", "franco", "humour", "ligne", "claire"], ["tintin", "astérix", "obélix", "milou", "haddock", "schtroumpf", "spirou", "gaston", "titeuf"]),
    "MANGA_ANIME": (["manga", "japon", "anime", "shonen", "otaku", "japonais", "série", "héros", "combat"], ["naruto", "goku", "luffy", "pikachu", "totoro"]),
    "JEUX_VIDEO": (["jeu", "vidéo", "console", "manette", "gamer", "nintendo", "arcade", "pixel", "virtuel", "héros"], ["mario", "luigi", "sonic", "zelda", "pacman"]),
    "DISNEY_PIXAR": (["dessin", "animé", "disney", "princesse", "prince", "château", "magie", "pixar", "pixar", "film", "enfance", "conte"], ["mickey", "minnie", "donald", "dingo", "picsou", "bambi", "simba", "aladin", "mulan", "elsa", "shrek", "nemo", "dory", "buzz", "woody", "cendrillon", "pinocchio", "crochet", "mowgli", "poppins"]),
    "CARTOONS_POP": (["cartoon", "américain", "série", "télé", "humour", "cartoon"], ["simpson", "homer", "bart", "lisa", "popeye", "garfield", "snoopy", "barbie", "ken"]),
    "SUPER_HEROS": (["comics", "super", "héros", "pouvoir", "masque", "costume", "justicier", "marvel", "avengers", "vilain"], ["batman", "joker", "superman", "spiderman", "hulk", "thor", "thanos"]),
    "STAR_WARS": (["force", "jedi", "empire", "sabre", "laser", "espace", "galaxie", "vaisseau", "étoile", "wars", "star", "obscur"], ["vador", "yoda", "luke", "leia", "chewbacca", "skywalker", "kenobi", "palpatine"]),
    "FANTASY_MAGIC": (["magie", "sorcier", "baguette", "anneau", "épée", "elfe", "fantasy", "poudlard", "magie", "milieu", "fantaisie"], ["potter", "weasley", "hermione", "dumbledore", "voldemort", "hagrid", "frodon", "gandalf", "gollum", "aragorn", "legolas", "sauron"]),
    "ACTION_CULTES": (["action", "robot", "futur", "agent", "espion", "boxe", "combat", "matrice", "machine", "voyage", "temps"], ["terminator", "rocky", "rambo", "neo", "morpheus"]),
    "MONSTRES_HORREUR": (["monstre", "géant", "vampire", "créature", "horreur", "gothique", "effrayant", "bête", "horreur", "laboratoire"], ["dracula", "frankenstein", "godzilla"]),
    "HEROS_CLASSIQUES": (["aventurier", "justicier", "masque", "épée", "jungle", "enquête", "détective", "élémentaire", "légende"], ["zorro", "tarzan", "sherlock", "watson"]),
    "RAP_FR": (["rap", "français", "urbain", "cité", "musique", "chanson", "chanteur","banlieue", "rapeur", "marseille", "paname", "feat", "album"], ["booba", "kaaris", "orelsan", "gims", "soprano", "iam", "akhenaton", "Jul", "ntm", "damso", "passi", "oxmo"]),
    "RAP_US": (["rap", "us", "américain", "hiphop", "musique", "chanson", "chanteur", "flow", "feat", "east", "coast", "gangsta", "beat", "mc"], ["eminem", "tupac", "snoop", "dre", "kanye", "drake", "rihanna", "cardi", "biggie"]),
    "POP_STAR": (["pop", "star", "danse", "show", "tube", "américain", "musique", "chanson", "US", "clip", "mode", "icône"], ["jackson", "madonna", "beyoncé", "gaga", "shakira", "britney", "swift", "houston", "carey", "minogue", "iglesias", "timberlake"]),
    "ROCK_LEGENDS": (["rock", "groupe", "guitare", "électrique", "légende", "musique", "chanson", "stade", "batteur", "riff", "solo", "anglais"], ["bowie", "mercury", "elvis", "lennon", "mccartney", "jagger", "bono", "hendrix", "cobain", "sting", "collins", "turner", "springsteen", "dylan", "joplin"]),
    "CHANSON_FR": (["chanson", "française", "français", "variété","musique","texte", "poète", "voix", "populaire", "scène", "émotion"], ["piaf", "brel", "aznavour", "gainsbourg", "hallyday", "goldman", "cabrel", "farmer", "pagny", "bruel", "stromae", "dalida", "sardou", "renaud", "brassens", "ferré", "voisine", "obispo", "mitchell"]),
    "JAZZ_SOUL": (["jazz", "soul", "blues", "trompette", "musique", "chanson","piano", "voix", "improvisation", "swing", "groove"], ["sinatra", "armstrong", "davis", "coltrane", "aretha"]),
    "CLASSIQUE": (["classique", "compositeur", "musique", "chanson","symphonie", "opéra", "piano", "orchestre", "maestro", "violon", "concerto", "sonate"], ["mozart", "beethoven", "bach", "chopin", "vivaldi", "verdi", "wagner"]),
    "LITT_POESIE": (["poésie", "poète", "vers", "rimes", "recueil", "sonnet", "strophe","français", "alexandrin", "lyrisme", "poétique"], ["baudelaire", "rimbaud", "verlaine", "prévert", "apollinaire", "musset"]),
    "LITT_FR_PROSE": (["roman", "théâtre", "classique", "français", "française","littérature", "académie", "siècle", "dramaturge", "écrivain", "lettres"], ["hugo", "zola", "molière", "voltaire", "rousseau", "proust", "camus", "sartre", "flaubert", "maupassant", "colette", "sand", "duras", "pagnol", "racine", "corneille", "balzac", "stendhal", "beaumarchais"]),
    "LITT_ANGLO": (["roman", "américain", "anglais", "littérature", "classique", "écriture", "pullitzer", "états-unis"], ["shakespeare", "orwell", "hemingway", "steinbeck", "faulkner", "woolf", "austen", "brontë", "twain", "melville", "fitzgerald", "london"]),
    "LITT_EUROPE": (["roman", "étranger"], ["kafka", "goethe", "homère", "virgile", "ovide", "dante", "cervantes", "tolstoï", "dostoïevski", "nabokov"]),
    "LITT_POLAR": (["polar", "enquête", "meurtre", "détective", "crime", "mystère", "suspect", "police", "thriller", "coupable"], ["christie", "simenon", "doyle", "leblanc"]),
    "LITT_IMAGINAIRE": (["fantastique", "sf", "science-fiction", "magie", "futur", "sorcier", "anneau", "monstre", "horreur", "vampire", "robot"], ["rowling", "tolkien", "lovecraft", "asimov", "bradbury", "verne", "wells"]),
    "LITT_POP": (["roman", "best-seller", "succès", "lecture", "été", "populaire", "moderne", "histoire", "page"], ["levy", "musso", "pennac", "dumas", "grisham"]),
    "PHILO_ANTIQUE": (["antique", "grec", "sagesse", "agora", "maître", "disciple", "athènes", "dialogue"], ["socrate", "platon", "aristote"]),
    "PHILO_CLASSIQUE": (["raison", "doute", "cogito", "dieu", "pensée", "éthique", "métaphysique", "critique", "esprit", "classique"], ["descartes", "kant", "hegel", "spinoza", "pascal", "montaigne", "machiavel"]),
    "PHILO_FREUD": (["inconscient", "psychanalyse", "rêve", "psychologie", "névrose", "pulsion", "sofa", "libido"], ["freud"]),
    "PHILO_MARX": (["capital", "lutte", "classe", "communisme", "prolétariat", "ouvrier", "économie", "révolution", "socialisme"], ["marx"]),
    "PHILO_NIETZSCHE": (["volonté", "surhomme", "nihilisme", "crépuscule", "bien", "mal", "moral", "marteau", "dieu"], ["nietzsche"]),
    "HISTOIRE_ROIS": (["roi", "reine", "empereur", "trône", "couronne", "conquête", "épée", "château", "siècle", "empire", "pharaon", "césar"], ["napoléon", "charlemagne", "clovis", "césar", "cléopâtre", "alexandre", "spartacus", "néron", "toutankhamon", "victoria", "elizabeth", "auguste", "trajan", "hadrien", "constantin", "justinien", "soliman", "ramses", "akhenaton", "nefertiti", "attila"]),
    "POLITIQUE_FR": (["président", "ministre", "état", "république", "élection", "parti", "élysée", "gouvernement", "révolution", "français", "citoyen", "politique"], ["chirac", "sarkozy", "hollande", "mitterrand", "pompidou", "jaurès", "clemenceau", "robespierre", "danton", "giscard"]),
    "POLITIQUE_MONDE": (["président", "chef", "monde", "guerre", "paix", "union", "pouvoir", "international", "crise", "histoire", "politique"], ["churchill", "kennedy", "obama", "trump", "poutine", "mandela", "gandhi", "mao", "lénine", "staline", "lincoln", "washington", "roosevelt", "reagan", "bush", "clinton", "thatcher", "gorbatchev", "eltsine", "krouchtchev", "brejnev"]),
    "SCIENCES_DURES": (["science", "physique", "chimie", "mathématiques", "génie", "laboratoire", "théorie", "formule", "savant", "recherche", "invention"], ["einstein", "newton", "darwin", "curie", "pasteur", "hawking", "copernic", "galilée", "kepler", "heisenberg", "schrödinger", "oppenheimer", "turing", "lovelace", "pythagore", "thalès", "euclide", "archimède", "hippocrate", "lavoisier"]),
    "TECH_INNOV": (["technologie", "invention", "internet", "ordinateur", "réseau", "silicon", "milliardaire", "web", "machine", "futur", "innovation"], ["jobs", "gates", "bezos", "edison", "tesla", "gutenberg"]),
    "ESPACE": (["espace", "lune", "fusée", "orbite", "mars", "iss", "astronaute", "cosmonaute", "univers", "étoile"], ["pesquet", "armstrong", "gagarine", "aldrin"]),
    "ARTS_PEINTURE": (["peinture", "art", "tableau", "toile", "musée", "pinceau", "couleur", "galerie", "artiste", "sculpture"], ["picasso", "dali", "monet", "manet", "renoir", "cézanne", "matisse", "rodin", "warhol", "banksy", "goya", "rembrandt", "vermeer", "klimt", "munch", "kandinsky", "magritte", "duchamp", "basquiat", "kahlo", "rubens", "raphael", "titien", "courbet", "gauguin", "degas", "miro", "pollock", "hopper", "botticelli", "caravage", "delacroix", "david", "ingres", "turner", "constable", "bacon", "klein", "soulages", "koons", "haring", "vinci", "michelange"]),
    "CINEMA_ACTEURS": (["acteur", "actrice", "star", "vedette", "rôle", "cinéma", "glamour", "hollywood", "comédien"], ["chaplin", "monroe", "bardot", "delon", "belmondo", "gabin", "bourvil", "fernandel", "funès", "depardieu", "deneuve", "adjani", "marceau", "reno", "cotillard", "cassel", "dujardin", "pitt", "clooney", "dicaprio", "roberts", "streep", "hanks", "cruise", "ford", "johansson", "schwarzenegger", "stallone", "willis", "norris", "chan", "brando", "pacino", "deniro", "nicholson", "hepburn", "taylor", "wayne", "bogart", "gable", "kelly", "garland", "signoret", "montand", "noiret", "rochefort", "marielle", "auteuil", "clavier", "balasko", "chabat", "foster", "kidman", "gibson"]),
    "CINEMA_REAL": (["réalisateur", "caméra", "tournage", "scénario", "film", "mise", "scène", "clap", "action", "cinéma"], ["spielberg", "tarantino", "nolan", "lucas", "disney", "hitchcock", "kubrick", "cameron", "burton", "allen", "eastwood", "coppola", "scorsese", "godard", "truffaut", "besson"]),
    "SPORT_FOOT": (["football", "ballon", "but", "stade", "match", "coupe", "monde", "équipe", "joueur", "arbitre", "goal", "sport"], ["zidane", "pelé", "maradona", "messi", "ronaldo", "platini", "cantona", "deschamps", "henry", "benzema", "kopa", "fontaine", "cruyff", "beckenbauer", "zico", "romario", "rivaldo", "ronaldinho", "buffon"]),
    "SPORT_TENNIS": (["tennis", "raquette", "balle", "set", "match", "roland", "garros", "grand", "chelem", "court", "filet", "sport"], ["federer", "nadal", "djokovic", "williams", "agassi", "sampras", "borg", "mcenroe", "connors", "noah"]),
    "SPORT_MECA": (["formule", "voiture", "course", "pilote", "circuit", "vitesse", "grand", "prix", "rallye", "moteur", "piste", "sport"], ["hamilton", "schumacher", "senna", "prost", "loeb", "vettel", "alonso", "alesi"]),
    "SPORT_DIVERS": (["sport", "athlète", "olympique", "médaille", "or", "record", "physique", "champion", "ring", "panier", "sport"], ["jordan", "lebron", "kobe", "tyson", "bolt", "woods", "riner", "douillet", "manaudou", "lewis", "powell", "bubka", "merckx", "hinault", "indurain", "armstrong"])
}

# --- 2b. BOOSTERS SPÉCIFIQUES ---
BOOSTERS_PERSO = {}

# --- 3. PRÉPARATION ---
candidats_valides = []
print("🔍 Vérification de la liste des personnalités...")
if modele:
    for cat, (boosts, noms) in DONNEES_JEU.items():
        count_cat = 0
        for nom in noms:
            nom_clean = nom.strip().lower()
            if nom_clean in modele:
                candidats_valides.append((nom, cat))
                count_cat += 1
        print(f"   -> {cat} : {count_cat} valides.")
    candidats_valides.sort(key=lambda x: x[0])
    print(f"✅ LISTE FINALE : {len(candidats_valides)} personnalités jouables.")
else:
    print("❌ MODELE NON CHARGÉ.")

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
    
    # Hier
    index_hier = (delta_jours - 1) % len(playlist)
    selection_hier = playlist[index_hier]
    
    return selection[0], selection[1], selection_hier[0]

def demarrer_partie():
    mot_du_jour, categorie_du_jour, mot_hier = get_daily_data()
    date_str = datetime.date.today().strftime("%d/%m/%Y")
    
    msg_hier = f"📜 La personnalité d'hier était : **{mot_hier.upper()}**"
    
    return mot_du_jour, categorie_du_jour, [], f"🏛️ Culturix du {date_str}", "JEU", msg_hier

def preparer_texte_partage(hist):
    nb_coups = len(hist)
    date_str = datetime.date.today().strftime("%d/%m/%Y")
    if hist and hist[0][2] == "1000":
        return f"🏛️ Culturix du Jour ({date_str})\nJ'ai trouvé la personnalité mystère en {nb_coups} coups !\n👉 https://huggingface.co/spaces/Tiphaine/culturix"
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
    secret_lower = mot_secret.lower()
    
    # VICTOIRE
    if clean_mot == secret_lower:
        historique.insert(0, ["🥳", clean_mot.capitalize(), "1000"])
        return historique, f"🥳 BRAVO ! C'était {mot_secret.upper()} !", "VICTOIRE", preparer_texte_partage(historique)

    if clean_mot not in modele:
         return historique, f"❓ Inconnu : '{clean_mot}'", "ERREUR", texte_partage_actuel

    if secret_lower in modele:
        raw_score = modele.similarity(secret_lower, clean_mot)
        # Calibrage généreux
        score = raw_score * 1000 * 1.6
        if score > 990: score = 990
    
    # BOOST CATÉGORIE (Ultra-Précis)
    if cat_secret in DONNEES_JEU:
        mots_cles_cat = DONNEES_JEU[cat_secret][0]
        # Si le mot joué (ou sa racine) est dans les mots-clés de la catégorie
        if clean_mot in mots_cles_cat or lemme_mot in mots_cles_cat:
            boost = random.uniform(850.0, 950.0)
            score = max(score, boost)

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
    
    # MODIFICATION ICI : Affiche le score et l'émoji dans le message de retour
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

/* 3. FORCER LE TEXTE EN VIOLET FONCÉ (Y COMPRIS LISTES & CHIFFRES) */
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
    color: #4c1d95 !important; /* Violet foncé */
    text-shadow: none !important;
    background: transparent !important;
    border: none !important;
}

/* 4. LE TITRE PRINCIPAL */
h1 { 
    font-family: 'Arial Rounded MT Bold', sans-serif; 
    color: #8b5cf6 !important; 
    text-align: center; 
    font-size: 2.5em !important; 
    margin-bottom: 0px !important; 
}

/* 5. LA BARRE DE RECHERCHE */
.search-input textarea { 
    background-color: white !important; 
    border-radius: 50px !important; 
    border: 3px solid #ec4899 !important; 
    box-shadow: 0 4px 10px rgba(236, 72, 153, 0.2) !important; 
    font-size: 1rem !important; 
    padding: 12px 15px !important; 
    text-align: center; 
    color: #4c1d95 !important; 
}

/* 6. LES BOUTONS */
#btn-envoyer { 
    border-radius: 50px !important; 
    background-image: linear-gradient(to right, #8b5cf6, #ec4899) !important; 
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
    color: #4c1d95 !important; 
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
            await navigator.share({ title: 'Culturix', text: text_to_share });
            return;
        }
    } catch (err) { console.log(err); }
    try {
        await navigator.clipboard.writeText(text_to_share);
        alert('Résultat copié ! 📋');
    } catch (err) {
        alert('Impossible de copier automatiquement.');
    }
}"""

with gr.Blocks(title="Culturix") as demo:
    gr.HTML(html_confetti_loader)
    
    gr.HTML("<h1 style='margin-bottom: 10px;'>🏛️ Culturix</h1>")
    gr.Markdown("**Le défi culture du Jour** • Une personnalité (réelle ou fictive) unique à trouver !", elem_id="subtitle")
    
    # Affichage du mot d'hier
    lbl_hier = gr.Markdown(visible=True)
    
    with gr.Accordion("❓ Comment jouer ? (Clique ici)", open=False):
        gr.Markdown("""
        **Une seule personnalité (réelle ou fictive) par jour !** (chaque jour à minuit)
        
        **Les indices :** Tape un nom, un personnage, un métier, une œuvre ou un mot-clé pour voir s'il est proche.
        
        **Les catégories :** MYTHOLOGIE & LÉGENDES, ANIMATION, BD & JEUX VIDÉO, HÉROS (Personnages), MUSIQUE, LITTÉRATURE, 
        PHILOSOPHIE, HISTOIRE & POLITIQUE, SCIENCES & TECH, ARTS, CINÉMA (Acteurs/Réal) & SPORT.
        
        * ❄️ **Froid** : Tu es très très loin.
        * 😎 **Tiède** : Tu t'approches (> 100).
        * 🔥 **Chaud** : On supporte encore la petite laine (> 300).
        * 🥵 **Brûlant** : Tu brûles, fais gaffe ! (> 500).
        * 😱 **Incroyable** : Tu es VRAIMENT tout près (> 900) !
        * 🥳 **VICTOIRE** : Tu as trouvé ! (1000)
        """)

    secret_state = gr.State()
    history_state = gr.State([])
    status_state = gr.State("JEU")
    
    txt_share_content_hidden = gr.Textbox(visible=False, value="")
    
    with gr.Row():
        txt_input = gr.Textbox(show_label=False, placeholder="Tape un mot ou un perso...", scale=4, elem_classes=["search-input"])
        btn_submit = gr.Button("GO !", scale=1, elem_id="btn-envoyer")
    
    lbl_message = gr.Label(value="Prêt ?", show_label=False)
    
    btn_share = gr.Button("📤 Partager mon exploit", elem_id="btn-share", visible=True)

    tableau = gr.Dataframe(headers=["🌡️", "Mot", "Score"], datatype=["str", "str", "str"], value=[], interactive=False)
    gr.Markdown(f"ℹ️ *Bibliothèque : {len(candidats_valides)} personnalités chargées.*")

    def wrapper_jouer(mot, secret, hist):
        h, msg, st, share_txt = jouer(mot, secret, hist)
        return gr.update(value=""), h, msg, h, st, share_txt

    def init_game():
        # Correctif pour éviter l'erreur rouge : on renvoie bien 7 valeurs
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
            D'autres défis vous attendent :<br>
            🏠 <a href="https://huggingface.co/spaces/Tiphaine/Objetix" target="_blank" style="color: #8b5cf6; text-decoration: none; font-weight: bold;">Objetix</a> (Objets cachés) 
            &nbsp;•&nbsp; 
            🦉 <a href="https://huggingface.co/spaces/Tiphaine/philosophix" target="_blank" style="color: #8b5cf6; text-decoration: none; font-weight: bold;">Philosophix</a> (Philo)
        </div>
        """)

demo.launch(css=custom_css)