import gradio as gr
import requests
import numpy as np

#API_URL = "https://huggingface.co/spaces/Frederic-LAGNIEZ/api_jenedai/"
API_URL ="https://frederic-lagniez-api-jenedai.hf.space"


SECTEURS = ["S1: Agriculture", "S2: Industrie", "S3: Tertiaire", "S4: Non Affecté"]

PLAGES_PUISSANCE = [
    "P1: ]36-120] kVA", "P2: ]120-250] kVA", "P3: Total ]36-250] kVA",
    "P4: ]250-1000] kVA", "P5: ]1000-2000] kVA", "P6: > 2000 kVA",
    "P7: Total > 250 kVA"
]

VILLES = ["Paris", "Lyon", "Marseille", "Toulouse", "Nantes", "Lille", "Orléans", "Rouen", "Dijon"]

MOIS = [str(i) for i in range(1, 13)]
JOURS = [str(i) for i in range(7)]
VACANCES = ["0", "1"]


def generate_random_sample():
    return (
        str(np.random.choice(SECTEURS)),
        str(np.random.choice(PLAGES_PUISSANCE)),
        float(np.random.uniform(0, 1500)),
        str(np.random.choice(VILLES)),
        str(np.random.randint(0, 2)),
        float(np.random.uniform(-5, 35)),
        float(np.random.uniform(55, 95)),
        float(np.random.uniform(0, 20)),
        str(np.random.randint(1, 13)),
        str(np.random.randint(0, 7)),
    )


def predict(secteur, plage_puissance, nb_points, ville, en_vacances,
            temperature, humidite, precipitation, month, jour_semaine):
    payload = {
        "secteur_activite": secteur,
        "plage_de_puissance_souscrite": plage_puissance,
        "nb_points_soutirage": float(nb_points),
        "ville": ville,
        "en_vacances": int(en_vacances),
        "temperature_2m_mean": float(temperature),
        "relative_humidity_mean": float(humidite),
        "precipitation_sum": float(precipitation),
        "month": int(month),
        "jour_semaine": int(jour_semaine),
    }

    try:
        response = requests.post(f"{API_URL}/predict", json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        return f"⚡ Consommation prédite : {result['predicted_wh']:,.0f} Wh"
    except requests.exceptions.RequestException as e:
        return f"❌ Erreur API : {e}"


with gr.Blocks(title="Prédiction Jenedai") as demo:
    gr.Markdown("# 🔌 Prédiction de consommation énergétique — Jenedai")

    with gr.Row():
        with gr.Column():
            secteur = gr.Dropdown(SECTEURS, label="Secteur d'activité", value=SECTEURS[0])
            plage_puissance = gr.Dropdown(PLAGES_PUISSANCE, label="Plage de puissance souscrite", value=PLAGES_PUISSANCE[0])
            nb_points = gr.Number(label="Nb points de soutirage", value=100.0)
            ville = gr.Dropdown(VILLES, label="Ville", value=VILLES[0])
            en_vacances = gr.Radio(VACANCES, label="En vacances", value="0")

        with gr.Column():
            temperature = gr.Number(label="Température moyenne (°C)", value=15.0)
            humidite = gr.Number(label="Humidité relative moyenne (%)", value=70.0)
            precipitation = gr.Number(label="Précipitations (mm)", value=2.0)
            month = gr.Dropdown(MOIS, label="Mois", value="1")
            jour_semaine = gr.Dropdown(JOURS, label="Jour de la semaine (0=lundi)", value="0")

    random_btn = gr.Button("🎲 Générer un échantillon aléatoire")
    predict_btn = gr.Button("🤖 Prédire la consommation")
    output = gr.Textbox(label="Résultat")

    inputs = [secteur, plage_puissance, nb_points, ville, en_vacances,
              temperature, humidite, precipitation, month, jour_semaine]

    random_btn.click(fn=generate_random_sample, inputs=[], outputs=inputs)
    predict_btn.click(fn=predict, inputs=inputs, outputs=output)

demo.launch()