# --- Imports ---
import gradio as gr
import pandas as pd
from pycaret.classification import *
from pycaret.regression import *
import numpy as np
import warnings
import sys
from io import StringIO
import contextlib
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.figure import Figure
import io
import base64
import pickle
import os
from datetime import datetime

warnings.filterwarnings('ignore')

# Global variables to store the DataFrame and experiment
global_df = None
global_exp = None
global_leaderboard = None
global_best_model = None
global_all_models = None
global_train_shape = None
global_test_shape = None
global_cv_folds = None
global_problem_type = None

@contextlib.contextmanager
def capture_output():
    """Context manager to capture stdout and stderr"""
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    stdout_capture = StringIO()
    stderr_capture = StringIO()
    try:
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture
        yield stdout_capture, stderr_capture
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

def create_leaderboard_plot(leaderboard_df, problem_type):
    """Create a horizontal bar plot of model performance"""
    try:
        # Select the primary metric based on problem type
        if problem_type == "Classification":
            metric = 'Accuracy' if 'Accuracy' in leaderboard_df.columns else leaderboard_df.columns[1]
        else:
            metric = 'R2' if 'R2' in leaderboard_df.columns else leaderboard_df.columns[1]
        
        # Create figure
        fig, ax = plt.subplots(figsize=(12, 8))
        
        # Get top 10 models
        top_models = leaderboard_df.head(10).copy()
        
        # Create horizontal bar plot
        bars = ax.barh(range(len(top_models)), top_models[metric], 
                      color=plt.cm.viridis(np.linspace(0, 1, len(top_models))))
        
        # Customize plot
        ax.set_yticks(range(len(top_models)))
        ax.set_yticklabels(top_models.index, fontsize=10)
        ax.set_xlabel(f'{metric} Score', fontsize=12, fontweight='bold')
        ax.set_title(f'Model performance comparison - {problem_type}', fontsize=14, fontweight='bold')
        ax.grid(axis='x', alpha=0.3)
        
        # Add value labels on bars
        for i, (bar, value) in enumerate(zip(bars, top_models[metric])):
            ax.text(value + 0.001, bar.get_y() + bar.get_height()/2, 
                   f'{value:.4f}', va='center', fontsize=9, fontweight='bold')
        
        # Invert y-axis to show best model at top
        ax.invert_yaxis()
        
        plt.tight_layout()
        return fig
    except Exception as e:
        print(f"Error creating plot: {e}")
        return None

def create_mae_plot(leaderboard_df):
    """Create a horizontal bar plot of MAE for regression models"""
    try:
        # Check if MAE column exists
        if 'MAE' not in leaderboard_df.columns:
            return None
            
        # Create figure
        fig, ax = plt.subplots(figsize=(12, 8))
        
        # Get top 10 models (sorted by MAE ascending - lower is better) <--
        top_models = leaderboard_df.head(10).copy()
        mae_values = top_models['MAE']
        
        # Create horizontal bar plot (reverse order for MAE since lower is better)
        bars = ax.barh(range(len(top_models)), mae_values, 
                      color=plt.cm.plasma(np.linspace(0, 1, len(top_models))))
        
        # Customize plot
        ax.set_yticks(range(len(top_models)))
        ax.set_yticklabels(top_models.index, fontsize=10)
        ax.set_xlabel('Mean absolute error (MAE)', fontsize=12, fontweight='bold')
        ax.set_title('Model performance - mean absolute error (Lower is Better)', fontsize=14, fontweight='bold')
        ax.grid(axis='x', alpha=0.3)
        
        # Add value labels on bars
        for i, (bar, value) in enumerate(zip(bars, mae_values)):
            ax.text(value + max(mae_values) * 0.01, bar.get_y() + bar.get_height()/2, 
                   f'{value:.4f}', va='center', fontsize=9, fontweight='bold')
        
        # Invert y-axis to show best model at top
        ax.invert_yaxis()
        
        plt.tight_layout()
        return fig
    except Exception as e:
        print(f"Error creating MAE plot: {e}")
        return None

def format_dataframe_as_html(df, title="", max_rows=20):
    """Convert DataFrame to nicely formatted HTML"""
    if df is None or df.empty:
        return f"<h3>{title}</h3><p>No data available</p>"
    
    # Limit rows if too many
    display_df = df.head(max_rows) if len(df) > max_rows else df
    
    # Round numeric columns
    numeric_columns = display_df.select_dtypes(include=[np.number]).columns
    display_df = display_df.copy()
    display_df[numeric_columns] = display_df[numeric_columns].round(4)
    
    # Convert to HTML with styling
    html = f"""
    <div style="margin: 20px 0;">
        <h3 style="color: #2E86AB; margin-bottom: 15px;">{title}</h3>
        <div style="overflow-x: auto; max-height: 400px;">
            {display_df.to_html(classes='gradio-table', table_id='results-table', escape=False)}
        </div>
    </div>
    <style>
    .gradio-table {{
        border-collapse: collapse;
        width: 100%;
        font-family: 'Arial', sans-serif;
        font-size: 12px;
    }}
    .gradio-table th {{
        background-color: #2E86AB;
        color: white;
        padding: 12px 8px;
        text-align: left;
        font-weight: bold;
        position: sticky;
        top: 0;
    }}
    .gradio-table td {{
        padding: 8px;
        border-bottom: 1px solid #ddd;
    }}
    .gradio-table tr:nth-child(even) {{
        background-color: #f9f9f9;
    }}
    .gradio-table tr:hover {{
        background-color: #e6f3ff;
    }}
    </style>
    """
    
    if len(df) > max_rows:
        html += f"<p style='font-style: italic; color: #666;'>Showing top {max_rows} of {len(df)} results</p>"
    
    return html

def create_feature_importance_plot(feature_imp_df):
    """Create feature importance plot"""
    try:
        if feature_imp_df is None or feature_imp_df.empty:
            return None
            
        # Create figure
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Sort and get top features
        top_features = feature_imp_df.head(15)
        
        # Create horizontal bar plot
        bars = ax.barh(range(len(top_features)), top_features['Importance'], 
                      color=plt.cm.plasma(np.linspace(0, 1, len(top_features))))
        
        # Customize plot
        ax.set_yticks(range(len(top_features)))
        ax.set_yticklabels(top_features['Feature'], fontsize=10)
        ax.set_xlabel('Feature importance', fontsize=12, fontweight='bold')
        ax.set_title('Top feature importances', fontsize=14, fontweight='bold')
        ax.grid(axis='x', alpha=0.3)
        
        # Add value labels
        for i, (bar, value) in enumerate(zip(bars, top_features['Importance'])):
            ax.text(value + max(top_features['Importance']) * 0.01, 
                   bar.get_y() + bar.get_height()/2, 
                   f'{value:.4f}', va='center', fontsize=9, fontweight='bold')
        
        ax.invert_yaxis()
        plt.tight_layout()
        return fig
    except Exception as e:
        print(f"Error creating feature importance plot: {e}")
        return None

def save_selected_models(selected_models):
    """Save selected models to disk with metadata and code examples"""
    global global_all_models, global_problem_type, global_exp
    
    if not selected_models or global_all_models is None:
        return "No models selected or no models available to save."
    
    # Create models directory if it doesn't exist
    os.makedirs("saved_models", exist_ok=True)
    
    saved_files = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    try:
        # Get feature and target information from PyCaret config
        if global_problem_type == "Classification":
            from pycaret.classification import get_config
        else:
            from pycaret.regression import get_config
        
        try:
            feature_columns = get_config('X_train').columns.tolist()
            target_column = get_config('target_param')
        except:
            # Fallback if config is not available
            feature_columns = ["feature_info_not_available"]
            target_column = "target_info_not_available"
        
        # Create metadata and code example files
        metadata_filename = f"saved_models/model_info_{global_problem_type}_{timestamp}.txt"
        code_example_filename = f"saved_models/load_models_example_{timestamp}.py"
        
        # Write metadata file
        with open(metadata_filename, 'w') as f:
            f.write(f"AutoML Model Information\n")
            f.write(f"=" * 50 + "\n\n")
            f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Problem Type: {global_problem_type}\n")
            f.write(f"Number of Models Saved: {len(selected_models)}\n")
            f.write(f"Cross-validation Folds: {global_cv_folds}\n")
            f.write(f"Training Shape: {global_train_shape[0]} rows × {global_train_shape[1]} features\n")
            f.write(f"Testing Shape: {global_test_shape[0]} rows × {global_test_shape[1]} features\n\n")
            
            f.write(f"Target Variable:\n")
            f.write(f"- {target_column}\n\n")
            
            f.write(f"Feature Variables ({len(feature_columns)} features):\n")
            for i, feature in enumerate(feature_columns, 1):
                f.write(f"{i:2d}. {feature}\n")
            
            f.write(f"\nSaved Models:\n")
            for model_name in selected_models:
                f.write(f"- {model_name}_{global_problem_type}_{timestamp}.pkl\n")
        
        saved_files.append(metadata_filename)
        
        # Save individual models
        for model_name in selected_models:
            # Find the model in the list
            model_to_save = None
            for model in global_all_models:
                if str(model).split('(')[0] == model_name:
                    model_to_save = model
                    break
            
            if model_to_save is not None:
                # Create filename
                filename = f"saved_models/{model_name}_{global_problem_type}_{timestamp}.pkl"
                
                # Save model using pickle
                with open(filename, 'wb') as f:
                    pickle.dump(model_to_save, f)
                
                saved_files.append(filename)
        
        # Create Python code example file
        with open(code_example_filename, 'w') as f:
            f.write(f"# AutoML Model Loading Example\n")
            f.write(f"# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Problem Type: {global_problem_type}\n\n")
            
            f.write(f"import pickle\n")
            f.write(f"import pandas as pd\n")
            f.write(f"import numpy as np\n\n")
            
            f.write(f"# Feature columns (in the same order as used during training)\n")
            f.write(f"FEATURE_COLUMNS = {feature_columns}\n\n")
            f.write(f"# Target column\n")
            f.write(f"TARGET_COLUMN = '{target_column}'\n\n")
            
            f.write(f"# Example: Load a saved model\n")
            if selected_models:
                example_model = selected_models[0]
                f.write(f"model_filename = '{example_model}_{global_problem_type}_{timestamp}.pkl'\n")
                f.write(f"with open(model_filename, 'rb') as f:\n")
                f.write(f"    loaded_model = pickle.load(f)\n\n")
                
                f.write(f"print(f'Loaded model: {{type(loaded_model).__name__}}')\n\n")
                
                f.write(f"# Example: Make predictions on new data\n")
                f.write(f"# Ensure your new data has the same feature columns:\n")
                f.write(f"# new_data = pd.DataFrame(...)\n")
                f.write(f"# new_data = new_data[FEATURE_COLUMNS]  # Select only the required features\n\n")
                
                if global_problem_type == "Classification":
                    f.write(f"# For classification:\n")
                    f.write(f"# predictions = loaded_model.predict(new_data)\n")
                    f.write(f"# probabilities = loaded_model.predict_proba(new_data)  # if available\n\n")
                else:
                    f.write(f"# For regression:\n")
                    f.write(f"# predictions = loaded_model.predict(new_data)\n\n")
                
                f.write(f"# Load all saved models\n")
                f.write(f"saved_models = {{}}\n")
                for model_name in selected_models:
                    f.write(f"with open('{model_name}_{global_problem_type}_{timestamp}.pkl', 'rb') as f:\n")
                    f.write(f"    saved_models['{model_name}'] = pickle.load(f)\n")
                
                f.write(f"\nprint(f'Loaded {{len(saved_models)}} models: {{list(saved_models.keys())}}')\n")
        
        saved_files.append(code_example_filename)
        
        if saved_files:
            files_list = "\n".join([f"• {file}" for file in saved_files])
            return f"""
            <div style="background-color: #e8f5e8; padding: 15px; border-radius: 8px; border-left: 5px solid #28a745;">
                <h4 style="margin-top: 0; color: #155724;">✅ Models and Metadata Saved Successfully!</h4>
                <p><strong>Saved files ({len(saved_files)} files):</strong></p>
                <pre style="background-color: #f8f9fa; padding: 10px; border-radius: 4px; font-size: 11px; max-height: 200px; overflow-y: auto;">{files_list}</pre>
                <div style="margin-top: 15px; padding: 10px; background-color: #d1ecf1; border-radius: 4px; border-left: 4px solid #bee5eb;">
                    <h5 style="margin: 0 0 8px 0; color: #0c5460;">📋 What was saved:</h5>
                    <ul style="margin: 0; font-size: 12px; color: #0c5460;">
                        <li><strong>Model files (.pkl):</strong> The trained models ready for predictions</li>
                        <li><strong>Model info (.txt):</strong> Feature names, target variable, and training details</li>
                        <li><strong>Code example (.py):</strong> Ready-to-use Python code for loading and using your models</li>
                    </ul>
                </div>
                <p style="font-size: 12px; color: #6c757d; margin: 10px 0 0 0;">
                    💡 <strong>Quick start:</strong> Run the generated Python example file to see how to load and use your models!
                </p>
            </div>
            """
        else:
            return "Error: No models were saved. Please check the selected models."
            
    except Exception as e:
        return f"""
        <div style="background-color: #ffe6e6; padding: 15px; border-radius: 8px; border-left: 5px solid #dc3545;">
            <h4 style="margin-top: 0; color: #721c24;">❌ Error Saving Models</h4>
            <p>Error occurred while saving models: {str(e)}</p>
        </div>
        """

def load_and_update_columns(file):
    """
    Loads the CSV file into a pandas DataFrame and updates the dropdowns
    for target and feature selection.
    """
    global global_df
    if file is None:
        return (
            gr.Dropdown(choices=[], value=None),
            gr.CheckboxGroup(choices=[], value=[]),
            "Please upload a CSV file.",
            "",
            None,
            None,
            gr.CheckboxGroup(choices=[], value=[], visible=False),
            ""
        )

    try:
        df = pd.read_csv(file)  # Works in Colab
        global_df = df.copy()

        columns = df.columns.tolist()

        return (
            gr.Dropdown(choices=columns, value=None),
            gr.CheckboxGroup(choices=columns, value=[]),
            "CSV loaded successfully!",
            "",
            None,
            None,
            gr.CheckboxGroup(choices=[], value=[], visible=False),
            ""
        )
    except Exception as e:
        return (
            gr.Dropdown(choices=[], value=None),
            gr.CheckboxGroup(choices=[], value=[]),
            f"Error loading CSV: {e}",
            "",
            None,
            None,
            gr.CheckboxGroup(choices=[], value=[], visible=False),
            ""
        )

def run_automl_model(file, problem_type, target_column, selected_features, n_models, cv_folds):
    global global_df, global_exp, global_leaderboard, global_best_model, global_all_models
    global global_train_shape, global_test_shape, global_cv_folds, global_problem_type
    
    if global_df is None:
        return "", "Error: Please upload a CSV file first.", None, None, None, gr.CheckboxGroup(visible=False), ""

    df = global_df.copy()

    if not target_column:
        return "", "Error: Please select a target variable.", None, None, None, gr.CheckboxGroup(visible=False), ""

    if not selected_features:
        return "", "Error: Please select at least one feature.", None, None, None, gr.CheckboxGroup(visible=False), ""

    if target_column not in df.columns:
        return "", f"Error: Target column '{target_column}' not found.", None, None, None, gr.CheckboxGroup(visible=False), ""

    if target_column in selected_features:
        return "", "Error: Target variable cannot also be a feature.", None, None, None, gr.CheckboxGroup(visible=False), ""

    # Store global values
    global_cv_folds = cv_folds
    global_problem_type = problem_type

    # --- Data Preparation ---
    try:
        columns_to_consider = selected_features + [target_column]
        df_cleaned = df[columns_to_consider].dropna()

        if df_cleaned.empty:
            return "", "Error: Dataset empty after dropping missing values.", None, None, None, gr.CheckboxGroup(visible=False), ""

        # CRITICAL FIX: Convert target variable to appropriate type based on problem type
        if problem_type == "Classification":
            # For binary classification, ensure consistent labeling
            unique_vals = df_cleaned[target_column].unique()
            unique_values = len(unique_vals)
            
            # Verify it's actually a classification problem
            if unique_values > 10:  # Too many unique values for classification
                return "", f"Warning: Target variable has {unique_values} unique values. Consider using Regression instead.", None, None, None, gr.CheckboxGroup(visible=False), ""
            
            # Convert to categorical but keep original values as categories
            df_cleaned[target_column] = pd.Categorical(df_cleaned[target_column])
            
            # Alternative approach: use integer labels but tell PyCaret it's classification
            # This avoids string conversion issues
            df_cleaned[target_column] = df_cleaned[target_column].astype('category')
            
        else:
            # For regression, ensure target is numeric
            df_cleaned[target_column] = pd.to_numeric(df_cleaned[target_column], errors='coerce')
            if df_cleaned[target_column].isna().all():
                return "", "Error: Target variable cannot be converted to numeric for regression.", None, None, None, gr.CheckboxGroup(visible=False), ""

        # Initialize results HTML
        results_html = f"""
        <div style="font-family: Arial, sans-serif; line-height: 1.6;">
            <h2 style="color: #2E86AB; border-bottom: 2px solid #2E86AB; padding-bottom: 10px;">
                🖳 AutoML results - {problem_type}
            </h2>
            <div style="background-color: #f0f8ff; padding: 15px; border-radius: 8px; margin: 15px 0;">
                <h3 style="margin-top: 0; color: #1a5d7a;">📊 Dataset Information</h3>
                <ul style="margin: 0;">
                    <li><strong>Dataset shape:</strong> {df_cleaned.shape[0]} rows × {df_cleaned.shape[1]} columns</li>
                    <li><strong>Target variable:</strong> {target_column} ({df_cleaned[target_column].dtype})</li>
                    <li><strong>Target unique values:</strong> {df_cleaned[target_column].nunique()}</li>
                    <li><strong>Features:</strong> {', '.join(selected_features)}</li>
                    <li><strong>Models to compare:</strong> Top {n_models}</li>
                </ul>
            </div>
        """

        # Capture all PyCaret output
        with capture_output() as (stdout_capture, stderr_capture):
            # --- PyCaret Setup ---
            if problem_type == "Classification":
                from pycaret.classification import setup, compare_models, predict_model, pull, get_config
                global_exp = setup(
                    data=df_cleaned,
                    target=target_column,
                    session_id=42,
                    train_size=0.8,
                    fold=cv_folds,
                    verbose=False,
                    # Force PyCaret to treat this as classification
                    ignore_features=None,
                    # Ensure stratified split for classification
                    data_split_stratify=True
                )

                # Compare models and get the best ones
                best_models = compare_models(
                    n_select=n_models,
                    verbose=False
                )

            else:  # Regression
                from pycaret.regression import setup, compare_models, predict_model, pull, get_config
                global_exp = setup(
                    data=df_cleaned,
                    target=target_column,
                    session_id=42,
                    train_size=0.8,
                    fold=cv_folds,
                    verbose=False
                )

                best_models = compare_models(
                    n_select=n_models,
                    verbose=False
                )

        # If single model returned, convert to list
        if not isinstance(best_models, list):
            best_models = [best_models]

        # Store all models globally
        global_all_models = best_models

        # Get training and testing shapes from PyCaret config
        try:
            X_train = get_config('X_train')
            X_test = get_config('X_test')
            y_train = get_config('y_train')
            y_test = get_config('y_test')
            
            global_train_shape = (X_train.shape[0], X_train.shape[1])
            global_test_shape = (X_test.shape[0], X_test.shape[1])
        except:
            # Fallback calculation
            train_size = 0.8
            total_rows = df_cleaned.shape[0]
            train_rows = int(total_rows * train_size)
            test_rows = total_rows - train_rows
            
            global_train_shape = (train_rows, len(selected_features))
            global_test_shape = (test_rows, len(selected_features))

        # Get the comparison results
        global_leaderboard = pull()
        global_best_model = best_models[0]
        
        # Add leaderboard to HTML
        leaderboard_html = format_dataframe_as_html(
            global_leaderboard, 
            "🏆 Model performance leaderboard"
        )
        results_html += leaderboard_html

        # Evaluate the best model
        best_model_name = str(global_best_model).split('(')[0]
        results_html += f"""
        <div style="background-color: #e8f5e8; padding: 15px; border-radius: 8px; margin: 15px 0;">
            <h3 style="margin-top: 0; color: #2d5a2d;">🥇 Best Model: {best_model_name}</h3>
        </div>
        """

        # Get detailed test results
        predictions = predict_model(global_best_model)
        test_results = pull()

        # Add test results to HTML
        test_results_html = format_dataframe_as_html(
            test_results, 
            "📈 Test set performance metrics"
        )
        results_html += test_results_html

        # Feature importance (if available)
        feature_imp_df = None
        feature_importance_plot = None
        try:
            if hasattr(global_best_model, 'feature_importances_'):
                feature_names = get_config('X_train').columns
                importances = global_best_model.feature_importances_
                feature_imp_df = pd.DataFrame({
                    'Feature': feature_names,
                    'Importance': importances
                }).sort_values('Importance', ascending=False)
                
                feature_imp_html = format_dataframe_as_html(
                    feature_imp_df, 
                    "💽 Feature importance analysis"
                )
                results_html += feature_imp_html
                
                # Create feature importance plot
                feature_importance_plot = create_feature_importance_plot(feature_imp_df)
        except Exception as e:
            results_html += f"<p style='color: #666; font-style: italic;'>Feature importance not available for this model type.</p>"

        # Enhanced Training Summary with shapes and k-fold info
        results_html += f"""
        <div style="background-color: #f0f8ff; padding: 15px; border-radius: 8px; margin: 15px 0; border-left: 5px solid #2E86AB;">
            <h3 style="margin-top: 0; color: #1a5d7a;">📋 Training Summary</h3>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                <div>
                    <h4 style="color: #2E86AB; margin-bottom: 10px;">🔧 Configuration</h4>
                    <ul style="margin: 0; font-size: 14px;">
                        <li><strong>Problem Type:</strong> {problem_type}</li>
                        <li><strong>Cross-validation:</strong> {cv_folds}-fold CV</li>
                        <li><strong>Total models evaluated:</strong> {len(global_leaderboard)}</li>
                        <li><strong>Best performing model:</strong> {best_model_name}</li>
                    </ul>
                </div>
                <div>
                    <h4 style="color: #2E86AB; margin-bottom: 10px;">📏 Data Splits</h4>
                    <ul style="margin: 0; font-size: 14px;">
                        <li><strong>Training set:</strong> {global_train_shape[0]} rows × {global_train_shape[1]} features</li>
                        <li><strong>Testing set:</strong> {global_test_shape[0]} rows × {global_test_shape[1]} features</li>
                        <li><strong>Train/Test ratio:</strong> 80% / 20%</li>
                        <li><strong>Training completed:</strong> ✅</li>
                    </ul>
                </div>
            </div>
        </div>
        </div>
        """

        # Create performance comparison plot
        performance_plot = create_leaderboard_plot(global_leaderboard, problem_type)
        
        # Create MAE plot for regression problems
        mae_plot = None
        if problem_type == "Regression":
            mae_plot = create_mae_plot(global_leaderboard)

        # Create model selection checkboxes
        model_names = [str(model).split('(')[0] for model in global_all_models]
        model_checkboxes = gr.CheckboxGroup(
            choices=model_names,
            value=[],
            label="Select models to save",
            info=f"Choose which models to save to disk ({len(model_names)} models available)",
            visible=True
        )

        return results_html, "", performance_plot, feature_importance_plot, mae_plot, model_checkboxes, ""

    except Exception as e:
        error_msg = f"""
        <div style="background-color: #ffe6e6; padding: 15px; border-radius: 8px; border-left: 5px solid #ff4444;">
            <h3 style="margin-top: 0; color: #cc0000;">❌ Error</h3>
            <p>Error during PyCaret AutoML training or evaluation:</p>
            <code style="background-color: #fff; padding: 10px; display: block; border-radius: 4px;">{str(e)}</code>
        </div>
        """
        return "", error_msg, None, None, None, gr.CheckboxGroup(visible=False), ""

# --- Gradio Interface ---
with gr.Blocks(css="""
    .gradio-container {
        font-family: 'Arial', sans-serif;
    }
    .main-header {
        text-align: center;
        background:  #87CEEB; /* Light sky blue */
        color: white;
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 20px;
    }
""") as app:
    
    gr.HTML("""
    <div class="main-header">
        <h1 style="color: #666;">🖳 AutoML</h1>
        <p style="color: #666;">Upload your CSV, configure parameters, and discover the best machine learning model for your data</p>
        <p style="font-size: 0.9em; color: #666;">
            MAT RONI, S. (2025). <em>AutoML for classification and regression</em> (version 0.2) [computer software]
        </p>
    </div>
    """)

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 📁 Data & Configuration")
            file_input = gr.File(label="Upload CSV file", file_types=[".csv"])
            problem_type_radio = gr.Radio(
                ["Classification", "Regression"], 
                label="Task type", 
                value="Classification",
                info="Choose the type of machine learning problem"
            )
            target_dropdown = gr.Dropdown(
                [], 
                label="Target variable", 
                interactive=True,
                info="Select the column you want to predict"
            )
            feature_checkboxes = gr.CheckboxGroup(
                [], 
                label="Feature variables", 
                interactive=True,
                info="Select the columns to use as features"
            )
            
            with gr.Row():
                n_models_slider = gr.Slider(
                    1, 19, 
                    value=10, 
                    step=1, 
                    label="Number of models to compare",
                    info="More models = better results but longer training time"
                )
                cv_folds_slider = gr.Slider(
                    3, 10,
                    value=5,
                    step=1,
                    label="K-fold cross-validation",
                    info="Number of folds for cross-validation"
                )
            
            run_button = gr.Button("🚀 Run AutoML", variant="primary", size="lg")

        with gr.Column(scale=2):
            gr.Markdown("### 📊 Results & Analysis")
            with gr.Tabs():
                with gr.TabItem("📈 Performance overview"):
                    status_message = gr.Markdown("Upload a CSV file to begin.")
                    error_message = gr.HTML("")
                    performance_plot = gr.Plot(label="Model performance comparison")
                    mae_plot = gr.Plot(label="MAE comparison (regression only)", visible=False)
                
                with gr.TabItem("📋 Detailed results"):
                    results_display = gr.HTML(label="Detailed Results")
                
                with gr.TabItem("💽 Feature analysis"):
                    feature_plot = gr.Plot(label="Feature importance")
                
                with gr.TabItem("💾 Save models"):
                    gr.Markdown("### Save Trained Models")
                    gr.Markdown("Select which models you want to save to disk. Saved models can be loaded later using `pickle.load()`.")
                    
                    model_selection = gr.CheckboxGroup(
                        choices=[],
                        value=[],
                        label="Available models",
                        info="Select models to save",
                        visible=False
                    )
                    
                    save_button = gr.Button("💾 Save Selected Models", variant="secondary")
                    save_status = gr.HTML("")

    # Event handlers
    file_input.change(
        load_and_update_columns, 
        file_input, 
        [target_dropdown, feature_checkboxes, status_message, error_message, performance_plot, feature_plot, model_selection, save_status]
    )
    
    def update_plots_and_results(file, problem_type, target_column, selected_features, n_models, cv_folds):
        """Wrapper function to handle the MAE plot visibility and results"""
        results_html, error_msg, perf_plot, feat_plot, mae_chart, model_checks, save_msg = run_automl_model(
            file, problem_type, target_column, selected_features, n_models, cv_folds
        )
        
        # Show/hide MAE plot based on problem type
        mae_visible = problem_type == "Regression" and mae_chart is not None
        
        return (
            results_html,  # results_display
            error_msg,     # error_message
            perf_plot,     # performance_plot
            feat_plot,     # feature_plot
            mae_chart,     # mae_plot
            gr.Plot(visible=mae_visible),  # mae_plot visibility update
            model_checks,  # model_selection
            ""            # save_status (clear previous messages)
        )
    
    run_button.click(
        update_plots_and_results, 
        [file_input, problem_type_radio, target_dropdown, feature_checkboxes, n_models_slider, cv_folds_slider], 
        [results_display, error_message, performance_plot, feature_plot, mae_plot, mae_plot, model_selection, save_status]
    )
    
    # Save models event handler
    save_button.click(
        save_selected_models,
        [model_selection],
        [save_status]
    )

# Launch app
if __name__ == "__main__":
    app.launch(debug=True, share=True)