import pandas as pd
import gradio as gr
import os

FILE = "produkter.xlsx"
LOGO = "nouryon.png"

# =========================
# LOAD DATA
# =========================

df = pd.read_excel(FILE)

produkter = {
    str(r["Produkt"]).strip(): float(r["Densitet"])
    for _, r in df.iterrows()
}

alla_produkter = sorted(produkter.keys())

# =========================
# CALC
# =========================

def berakna(produkt, typ, varde, volym_enhet, vikt_enhet, senaste):
    if not produkt:
        return "", senaste, gr.update(choices=senaste)

    try:
        varde = float(str(varde).replace(",", "."))
    except:
        return "", senaste, gr.update(choices=senaste)

    densitet = produkter[produkt]

    if typ == "Volym":
        # Konvertera inmatad volym till m³
        if volym_enhet == "L":
            volym_m3 = varde / 1000
        else:
            volym_m3 = varde

        kg = volym_m3 * densitet

        # Konvertera resultat till vald viktenhet
        if vikt_enhet == "ton":
            resultat_vikt = kg / 1000
            resultat = (
                f"{varde:.2f} {volym_enhet} {produkt} = "
                f"{resultat_vikt:.2f} ton"
            )
        else:
            resultat = (
                f"{varde:.2f} {volym_enhet} {produkt} = "
                f"{kg:,.0f} kg"
            )

    else:
        # Konvertera inmatad vikt till kg
        if vikt_enhet == "ton":
            kg = varde * 1000
        else:
            kg = varde

        m3 = kg / densitet

        # Konvertera resultat till vald volymenhet
        if volym_enhet == "L":
            resultat_volym = m3 * 1000
            resultat = (
                f"{varde:.2f} {vikt_enhet} {produkt} = "
                f"{resultat_volym:,.0f} L"
            )
        else:
            resultat = (
                f"{varde:.2f} {vikt_enhet} {produkt} = "
                f"{m3:.2f} m³"
            )

    # Uppdatera senaste produkter
    if produkt in senaste:
        senaste.remove(produkt)

    senaste.insert(0, produkt)
    senaste = senaste[:5]

    return (
        resultat,
        senaste,
        gr.update(choices=senaste, value=produkt)
    )

# =========================
# UI
# =========================

with gr.Blocks(
    title="Volym ↔ Vikt Kalkylator"
) as app:

    gr.Markdown("# Volym ↔ Vikt Kalkylator")

    if os.path.exists(LOGO):
        gr.Image(LOGO, height=120, show_label=False)

    senaste_state = gr.State([])

    typ = gr.Radio(
        choices=["Volym", "Vikt"],
        value="Volym",
        label="Beräkningstyp"
    )

    produkt = gr.Dropdown(
        choices=alla_produkter,
        label="Produkt",
        interactive=True
    )

    volym_enhet = gr.Dropdown(
        choices=["m³", "L"],
        value="m³",
        label="Volymenhet"
    )

    vikt_enhet = gr.Dropdown(
        choices=["kg", "ton"],
        value="kg",
        label="Viktenhet"
    )

    varde = gr.Textbox(
        label="Värde",
        placeholder="Ange volym eller vikt"
    )

    resultat = gr.Textbox(
        label="Resultat",
        interactive=False
    )

    btn = gr.Button("Beräkna")

    gr.Markdown("### Senaste produkter")

    snabbval = gr.Dropdown(
        choices=[],
        label="Snabbval"
    )

    gemensamma_inputs = [
        produkt,
        typ,
        varde,
        volym_enhet,
        vikt_enhet,
        senaste_state
    ]

    gemensamma_outputs = [
        resultat,
        senaste_state,
        snabbval
    ]

    btn.click(
        berakna,
        inputs=gemensamma_inputs,
        outputs=gemensamma_outputs
    )

    produkt.change(
        berakna,
        inputs=gemensamma_inputs,
        outputs=gemensamma_outputs
    )

    typ.change(
        berakna,
        inputs=gemensamma_inputs,
        outputs=gemensamma_outputs
    )

    varde.change(
        berakna,
        inputs=gemensamma_inputs,
        outputs=gemensamma_outputs
    )

    volym_enhet.change(
        berakna,
        inputs=gemensamma_inputs,
        outputs=gemensamma_outputs
    )

    vikt_enhet.change(
        berakna,
        inputs=gemensamma_inputs,
        outputs=gemensamma_outputs
    )

    snabbval.change(
        lambda x: x,
        inputs=snabbval,
        outputs=produkt
    )

app.launch(share=True)