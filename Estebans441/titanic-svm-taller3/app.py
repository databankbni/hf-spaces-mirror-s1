import gradio as gr
import joblib
import pandas as pd

modelo = joblib.load("svm_titanic_model.pkl")
columnas = ['Pclass', 'Age', 'SibSp', 'Parch', 'Fare', 'Sex_encoded']

def predecir_supervivencia(pclass, age, sibsp, parch, fare, genero):
    sex_encoded = 1 if genero == "Hombre" else 0  # mismo encoding usado en entrenamiento: female=0, male=1
    entrada = pd.DataFrame([[pclass, age, sibsp, parch, fare, sex_encoded]], columns=columnas)
    pred = modelo.predict(entrada)[0]
    proba = modelo.predict_proba(entrada)[0][1] if hasattr(modelo, "predict_proba") else None

    resultado = "Sobrevive" if pred == 1 else "No sobrevive"
    if proba is not None:
        resultado += f" (probabilidad de supervivencia: {proba:.1%})"
    return resultado

demo = gr.Interface(
    fn=predecir_supervivencia,
    inputs=[
        gr.Number(label="Clase (Pclass: 1, 2 o 3)", value=3),
        gr.Number(label="Edad (Age)", value=30),
        gr.Number(label="Hermanos/esposos a bordo (SibSp)", value=0),
        gr.Number(label="Padres/hijos a bordo (Parch)", value=0),
        gr.Number(label="Tarifa pagada (Fare)", value=15.0),
        gr.Radio(["Mujer", "Hombre"], label="Genero", value="Mujer"),
    ],
    outputs=gr.Textbox(label="Prediccion"),
    title="Titanic - Prediccion de Supervivencia (SVM)",
    description="Ingrese los datos de un pasajero para predecir si sobrevive o no, segun el modelo SVM optimizado del Taller 3. Se incluye el genero porque demostro ser una variable muy relevante para la supervivencia."
)

demo.launch()