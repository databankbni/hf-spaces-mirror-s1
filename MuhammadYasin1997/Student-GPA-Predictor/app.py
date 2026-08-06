import gradio as gr
import joblib

# Load model
model = joblib.load("L_model_joblib")

def predict_gpa(parent_edu, study_hours, absences):
    prediction = model.predict([[parent_edu, study_hours, absences]])
    return round(float(prediction[0]), 2)

demo = gr.Interface(
    fn=predict_gpa,
    inputs=[
        gr.Number(label="Parental Education"),
        gr.Number(label="Study Time Weekly"),
        gr.Number(label="Absences")
    ],
    outputs=gr.Number(label="Predicted GPA"),
    title="Student GPA Prediction"
)

demo.launch(share=True)