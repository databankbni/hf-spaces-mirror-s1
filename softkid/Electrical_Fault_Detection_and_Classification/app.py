import gradio as gr
import pandas as pd
import numpy as np
import joblib


# Load model and scaler
# Note: Ensure these files exist by running the Jupyter Notebook first!
try:
    model = joblib.load('models/rf_model.joblib')
    scaler = joblib.load('models/scaler.joblib')
except FileNotFoundError:
    raise RuntimeError("Model files not found! Please run the fault_detection_eda_and_model.ipynb notebook first to train and save the model.")

# Define the prediction function
def predict_fault(ia, ib, ic, va, vb, vc):
    # Construct dataframe from inputs
    features = pd.DataFrame({
        'Ia': [ia],
        'Ib': [ib],
        'Ic': [ic],
        'Va': [va],
        'Vb': [vb],
        'Vc': [vc]
    })
    
    # Feature Engineering
    features['I_zero_sequence'] = features['Ia'] + features['Ib'] + features['Ic']
    features['V_zero_sequence'] = features['Va'] + features['Vb'] + features['Vc']
    
    # Scale features
    features_scaled = scaler.transform(features)
    
    # Predict
    pred = model.predict(features_scaled)[0]
    prob = model.predict_proba(features_scaled)[0]
    
    confidence = max(prob)
    
    # Map the combination to a readable format
    fault_map = {
        '0000': 'No Fault',
        '1001': 'Line A to Ground',
        '1010': 'Line B to Ground',
        '1100': 'Line C to Ground',
        '0011': 'Line A to Line B',
        '0101': 'Line A to Line C',
        '0110': 'Line B to Line C',
        '1011': 'Line A & B to Ground',
        '1101': 'Line A & C to Ground',
        '1110': 'Line B & C to Ground',
        '0111': '3-Phase Fault',
        '1111': '3-Phase to Ground'
    }
    
    pred_name = fault_map.get(str(pred), "Unknown Fault")
    
    return f"{pred_name} (Code: {pred})", f"Confidence Score: {confidence:.2%}"

# Define Gradio Interface
with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown("# ⚡ Electrical Fault Detection System")
    gr.Markdown("Enter the 3-phase current and voltage readings to predict the fault classification.")
    
    with gr.Row():
        with gr.Column():
            gr.Markdown("### Current Inputs (Amps)")
            ia_input = gr.Slider(minimum=-1000, maximum=1000, step=1, label="Phase A Current (Ia)")
            ib_input = gr.Slider(minimum=-1000, maximum=1000, step=1, label="Phase B Current (Ib)")
            ic_input = gr.Slider(minimum=-1000, maximum=1000, step=1, label="Phase C Current (Ic)")
            
        with gr.Column():
            gr.Markdown("### Voltage Inputs (Volts)")
            va_input = gr.Slider(minimum=-1.0, maximum=1.0, step=0.01, label="Phase A Voltage (Va)")
            vb_input = gr.Slider(minimum=-1.0, maximum=1.0, step=0.01, label="Phase B Voltage (Vb)")
            vc_input = gr.Slider(minimum=-1.0, maximum=1.0, step=0.01, label="Phase C Voltage (Vc)")
            
    btn = gr.Button("Predict Fault", variant="primary")
    
    with gr.Row():
        pred_output = gr.Textbox(label="Prediction Result")
        conf_output = gr.Textbox(label="Confidence")

    btn.click(
        fn=predict_fault, 
        inputs=[ia_input, ib_input, ic_input, va_input, vb_input, vc_input], 
        outputs=[pred_output, conf_output]
    )

if __name__ == "__main__":
    demo.launch()
