import gradio as gr

from app.ml_model import predict_energy


def predict(
    YearBuilt,
    BuildingAge,
    NumberofFloors,
    Log_Surface,
    PropertyGFATotal,
    LargestPropertyUseTypeGFA,
    PropertyGFABuilding_s,
    BuildingType,
    PrimaryPropertyType,
    City,
    State,
):

    features = {
        "YearBuilt": YearBuilt,
        "BuildingAge": BuildingAge,
        "NumberofFloors": NumberofFloors,
        "Log_Surface": Log_Surface,
        "PropertyGFATotal": PropertyGFATotal,
        "LargestPropertyUseTypeGFA": LargestPropertyUseTypeGFA,
        "PropertyGFABuilding_s": PropertyGFABuilding_s,
        "BuildingType": BuildingType,
        "PrimaryPropertyType": PrimaryPropertyType,
        "City": City,
        "State": State,
    }

    prediction = predict_energy(features)

    return f"{prediction:,.2f} kBtu/an"


gradio_interface = gr.Interface(

    fn=predict,

    title="🏢 Seattle Building Energy Prediction",

    description="""
Cette application prédit la consommation énergétique annuelle
des bâtiments non résidentiels de Seattle.

Le modèle de Machine Learning a été entraîné avec un
Random Forest Regressor.

Remplissez les informations du bâtiment puis cliquez sur **Prédire**.
""",

    theme=gr.themes.Soft(),

    inputs=[

        gr.Number(
            label="Year Built"
        ),

        gr.Number(
            label="Building Age"
        ),

        gr.Number(
            label="Number of Floors"
        ),

        gr.Number(
            label="Log Surface"
        ),

        gr.Number(
            label="Total Property Area (sq ft)"
        ),

        gr.Number(
            label="Largest Property Use Type GFA"
        ),

        gr.Number(
            label="Building Area (sq ft)"
        ),

        gr.Dropdown(
            choices=[
                "Campus",
                "NonResidential",
                "Multifamily"
            ],
            label="Building Type"
        ),

        gr.Textbox(
            label="Primary Property Type"
        ),

        gr.Textbox(
            value="Seattle",
            label="City"
        ),

        gr.Textbox(
            value="WA",
            label="State"
        ),

    ],

    outputs=gr.Textbox(
        label="Prediction"
    ),

    examples=[
        [
            1992,
            24,
            3,
            13.111982,
            494835,
            757027,
            494835,
            "Campus",
            "Mixed Use Property",
            "Seattle",
            "WA"
        ],
        [
            1985,
            40,
            5,
            12.5,
            350000,
            250000,
            300000,
            "NonResidential",
            "Office",
            "Seattle",
            "WA"
        ]
    ],

    submit_btn="Predict",

    clear_btn="Reset",

    flagging_mode="never"
)