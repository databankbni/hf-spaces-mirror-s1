import gradio as gr
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix
import pickle
import os

# Global variables to store the model and data
model = None
feature_columns = None

def load_and_train_model(csv_file):
    """Load dataset and train a Random Forest model"""
    global model, feature_columns
    
    try:
        # Read the uploaded CSV
        df = pd.read_csv(csv_file.name)
        
        # Check if 'fraud' column exists
        if 'fraud' not in df.columns:
            return "❌ Error: CSV must contain a 'fraud' column as the target variable."
        
        # Separate features and target
        X = df.drop(['fraud', 'transaction_id'], axis=1, errors='ignore')
        y = df['fraud']
        
        feature_columns = X.columns.tolist()
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
        
        # Train Random Forest model
        model = RandomForestClassifier(n_estimators=100, random_state=42, max_depth=10)
        model.fit(X_train, y_train)
        
        # Evaluate
        y_pred = model.predict(X_test)
        
        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred)
        recall = recall_score(y_test, y_pred)
        f1 = f1_score(y_test, y_pred)
        cm = confusion_matrix(y_test, y_pred)
        
        # Format results
        results = f"""
✅ **Model Trained Successfully!**

📊 **Dataset Information:**
- Total Samples: {len(df)}
- Training Samples: {len(X_train)}
- Test Samples: {len(X_test)}
- Fraud Cases: {y.sum()} ({y.mean()*100:.1f}%)
- Legitimate Cases: {(y==0).sum()} ({(y==0).mean()*100:.1f}%)

📈 **Model Performance:**
- **Accuracy:** {accuracy*100:.2f}%
- **Precision:** {precision*100:.2f}%
- **Recall:** {recall*100:.2f}%
- **F1-Score:** {f1*100:.2f}%

🔢 **Confusion Matrix:**
```
                    Predicted
                 Fraud  Legitimate
Actual Fraud       {cm[1][1]}        {cm[1][0]}
       Legit       {cm[0][1]}        {cm[0][0]}
```

**Key Metrics Explained:**
- **True Positives (TP):** {cm[1][1]} frauds correctly detected
- **False Negatives (FN):** {cm[1][0]} frauds missed (⚠️ costly!)
- **False Positives (FP):** {cm[0][1]} false alarms
- **True Negatives (TN):** {cm[0][0]} legitimate transactions correctly identified

✅ Model is ready! You can now make predictions below.
        """
        
        return results
        
    except Exception as e:
        return f"❌ Error: {str(e)}"


def predict_single_transaction(amount, hour, dist_home, dist_last, ratio_median, 
                               repeat_retailer, used_chip, used_pin, online_order):
    """Make a prediction for a single transaction"""
    global model, feature_columns
    
    if model is None:
        return "⚠️ Please upload and train a model first!", ""
    
    try:
        # Create input dataframe
        input_data = pd.DataFrame({
            'transaction_amount': [amount],
            'transaction_hour': [hour],
            'distance_from_home_km': [dist_home],
            'distance_from_last_transaction_km': [dist_last],
            'ratio_to_median_purchase': [ratio_median],
            'repeat_retailer': [repeat_retailer],
            'used_chip': [used_chip],
            'used_pin': [used_pin],
            'online_order': [online_order]
        })
        
        # Make prediction
        prediction = model.predict(input_data)[0]
        probability = model.predict_proba(input_data)[0]
        
        # Format result
        fraud_prob = probability[1] * 100
        legit_prob = probability[0] * 100
        
        if prediction == 1:
            result = f"🚨 **FRAUD DETECTED**"
            confidence = fraud_prob
            color = "red"
        else:
            result = f"✅ **LEGITIMATE TRANSACTION**"
            confidence = legit_prob
            color = "green"
        
        details = f"""
{result}

**Confidence:** {confidence:.1f}%

**Probability Distribution:**
- Fraud: {fraud_prob:.1f}%
- Legitimate: {legit_prob:.1f}%

**Risk Level:** {'🔴 HIGH' if fraud_prob > 70 else '🟡 MEDIUM' if fraud_prob > 40 else '🟢 LOW'}

**Transaction Details:**
- Amount: ${amount:,.2f}
- Time: {hour}:00
- Distance from home: {dist_home:.1f} km
- Distance from last transaction: {dist_last:.1f} km
- Ratio to median: {ratio_median:.2f}x
- Repeat retailer: {'Yes' if repeat_retailer else 'No'}
- Used chip: {'Yes' if used_chip else 'No'}
- Used PIN: {'Yes' if used_pin else 'No'}
- Online order: {'Yes' if online_order else 'No'}
        """
        
        return details, result
        
    except Exception as e:
        return f"❌ Error: {str(e)}", ""


def predict_batch(csv_file):
    """Make predictions for batch of transactions"""
    global model, feature_columns
    
    if model is None:
        return None, "⚠️ Please upload and train a model first!"
    
    try:
        # Read CSV
        df = pd.read_csv(csv_file.name)
        
        # Keep original df for output
        original_df = df.copy()
        
        # Prepare features
        X = df.drop(['fraud', 'transaction_id'], axis=1, errors='ignore')
        
        # Make predictions
        predictions = model.predict(X)
        probabilities = model.predict_proba(X)
        
        # Add predictions to dataframe
        original_df['predicted_fraud'] = predictions
        original_df['fraud_probability'] = probabilities[:, 1] * 100
        original_df['confidence'] = np.max(probabilities, axis=1) * 100
        
        # Calculate metrics if 'fraud' column exists
        if 'fraud' in original_df.columns:
            accuracy = accuracy_score(original_df['fraud'], predictions)
            precision = precision_score(original_df['fraud'], predictions)
            recall = recall_score(original_df['fraud'], predictions)
            f1 = f1_score(original_df['fraud'], predictions)
            
            metrics = f"""
📊 **Batch Prediction Results:**

- Total Transactions: {len(df)}
- Predicted Fraud: {predictions.sum()} ({predictions.mean()*100:.1f}%)
- Predicted Legitimate: {(predictions==0).sum()} ({(predictions==0).mean()*100:.1f}%)

📈 **Performance Metrics:**
- Accuracy: {accuracy*100:.2f}%
- Precision: {precision*100:.2f}%
- Recall: {recall*100:.2f}%
- F1-Score: {f1*100:.2f}%

✅ Results are ready for download!
            """
        else:
            metrics = f"""
📊 **Batch Prediction Results:**

- Total Transactions: {len(df)}
- Predicted Fraud: {predictions.sum()} ({predictions.mean()*100:.1f}%)
- Predicted Legitimate: {(predictions==0).sum()} ({(predictions==0).mean()*100:.1f}%)

✅ Results are ready for download!
            """
        
        # Save results to temporary CSV
        output_file = "predictions_output.csv"
        original_df.to_csv(output_file, index=False)
        
        return output_file, metrics
        
    except Exception as e:
        return None, f"❌ Error: {str(e)}"


# Create Gradio interface
with gr.Blocks(title="Fraud Detection System") as demo:
    
    gr.Markdown("""
    # 💳 Credit Card Fraud Detection System
    ### AI Infinity Programme | TalentSprint
    
    This interactive demo allows you to train a fraud detection model and make predictions on credit card transactions.
    
    **How to use:**
    1. Upload your training dataset (CSV file)
    2. Train the model
    3. Make single predictions or batch predictions
    """)
    
    with gr.Tab("📤 Upload & Train Model"):
        gr.Markdown("### Step 1: Upload Training Dataset")
        gr.Markdown("Upload a CSV file containing transaction data with a 'fraud' column (0 = legitimate, 1 = fraud)")
        
        with gr.Row():
            with gr.Column():
                train_file = gr.File(label="Upload Training CSV", file_types=[".csv"])
                train_button = gr.Button("🚀 Train Model", variant="primary", size="lg")
            
            with gr.Column():
                train_output = gr.Markdown(label="Training Results")
        
        train_button.click(
            fn=load_and_train_model,
            inputs=[train_file],
            outputs=[train_output]
        )
        
        gr.Markdown("""
        ---
        **Expected CSV format:**
        - `transaction_amount`, `transaction_hour`, `distance_from_home_km`, `distance_from_last_transaction_km`,
        - `ratio_to_median_purchase`, `repeat_retailer`, `used_chip`, `used_pin`, `online_order`, `fraud`
        """)
    
    with gr.Tab("🔍 Single Prediction"):
        gr.Markdown("### Test Individual Transactions")
        gr.Markdown("Enter transaction details to check if it's fraudulent")
        
        with gr.Row():
            with gr.Column():
                amount = gr.Number(label="Transaction Amount ($)", value=100)
                hour = gr.Slider(0, 23, step=1, label="Transaction Hour (0-23)", value=14)
                dist_home = gr.Number(label="Distance from Home (km)", value=10)
                dist_last = gr.Number(label="Distance from Last Transaction (km)", value=5)
                ratio_median = gr.Number(label="Ratio to Median Purchase", value=1.0)
            
            with gr.Column():
                repeat_retailer = gr.Checkbox(label="Repeat Retailer", value=True)
                used_chip = gr.Checkbox(label="Used Chip", value=True)
                used_pin = gr.Checkbox(label="Used PIN", value=True)
                online_order = gr.Checkbox(label="Online Order", value=False)
                
                predict_button = gr.Button("🔮 Predict", variant="primary", size="lg")
        
        with gr.Row():
            prediction_output = gr.Markdown(label="Prediction Result")
            prediction_label = gr.Markdown(label="Quick Result")
        
        predict_button.click(
            fn=predict_single_transaction,
            inputs=[amount, hour, dist_home, dist_last, ratio_median, 
                   repeat_retailer, used_chip, used_pin, online_order],
            outputs=[prediction_output, prediction_label]
        )
        
        gr.Markdown("---")
        gr.Markdown("### 🧪 Quick Test Scenarios")
        
        with gr.Row():
            gr.Markdown("""
            **Scenario 1: Obvious Fraud**
            - Amount: $4500, Hour: 3, Dist Home: 800km
            - New retailer, no chip/PIN, online
            """)
            gr.Markdown("""
            **Scenario 2: Normal Transaction**
            - Amount: $45, Hour: 14, Dist Home: 5km
            - Repeat retailer, chip + PIN, in-person
            """)
            gr.Markdown("""
            **Scenario 3: Suspicious**
            - Amount: $350, Hour: 22, Dist Home: 60km
            - New retailer, chip but no PIN, online
            """)
    
    with gr.Tab("📊 Batch Predictions"):
        gr.Markdown("### Upload Multiple Transactions")
        gr.Markdown("Upload a CSV file with multiple transactions to get predictions for all of them")
        
        with gr.Row():
            with gr.Column():
                batch_file = gr.File(label="Upload Test CSV", file_types=[".csv"])
                batch_button = gr.Button("📈 Predict Batch", variant="primary", size="lg")
            
            with gr.Column():
                batch_output = gr.Markdown(label="Batch Results")
                download_file = gr.File(label="Download Results CSV")
        
        batch_button.click(
            fn=predict_batch,
            inputs=[batch_file],
            outputs=[download_file, batch_output]
        )
    
    with gr.Tab("ℹ️ About"):
        gr.Markdown("""
        ## About This Demo
        
        This fraud detection system uses a **Random Forest Classifier** to identify potentially fraudulent credit card transactions.
        
        ### Features Used:
        1. **transaction_amount**: Transaction value in dollars
        2. **transaction_hour**: Hour of day (0-23)
        3. **distance_from_home_km**: Distance from cardholder's home
        4. **distance_from_last_transaction_km**: Distance from previous transaction
        5. **ratio_to_median_purchase**: Ratio compared to typical spending
        6. **repeat_retailer**: Whether customer used this merchant before
        7. **used_chip**: Whether chip card was used
        8. **used_pin**: Whether PIN was entered
        9. **online_order**: Whether transaction was online
        
        ### Model Performance:
        The model is trained to maximize **recall** (catching frauds) while maintaining reasonable **precision** (avoiding false alarms).
        
        ### Important Metrics:
        - **Precision**: Of flagged transactions, how many are actually fraud?
        - **Recall**: Of all frauds, how many do we catch?
        - **F1-Score**: Balance between precision and recall
        
        ### Business Impact:
        - **False Negative (missed fraud)**: Very costly - customer loses money
        - **False Positive (false alarm)**: Moderately costly - customer inconvenience
        
        ---
        
        **Created for:** AI Infinity Programme | TalentSprint  
        **Target Audience:** Software engineers transitioning to AI roles  
        **Educational Purpose:** Understanding classification, metrics, and business logic
        """)

# Launch the app
if __name__ == "__main__":
    demo.launch()