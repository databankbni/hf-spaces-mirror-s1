import os
import json
import time
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import roc_curve, auc, confusion_matrix, accuracy_score, f1_score, recall_score, precision_score
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import mlflow
import mlflow.sklearn
import mlflow.data
from mlflow.models import infer_signature

def train():
    print("Pre-training steps...")
    print("Generating synthetic customer churn data...")
    
    # Generate synthetic dataset
    np.random.seed(42)
    n_samples = 1000
    
    usage_frequency = np.random.randint(1, 31, n_samples)
    support_tickets = np.random.poisson(lam=2, size=n_samples)
    active_users = np.random.randint(1, 10, n_samples)
    contract_months = np.random.choice([1, 12, 24], size=n_samples)
    monthly_spend = np.random.normal(loc=100, scale=30, size=n_samples)
    
    # Calculate churn probability based on features
    churn_prob = (
        0.3 * (support_tickets / 5.0) 
        - 0.2 * (usage_frequency / 30.0) 
        - 0.1 * active_users 
        - 0.4 * (contract_months / 24.0) 
        + 0.1 * (monthly_spend / 100.0)
    )
    # Add noise
    churn_prob += np.random.normal(loc=0, scale=0.2, size=n_samples)
    churn = (churn_prob > 0).astype(int)
    
    df = pd.DataFrame({
        "usage_frequency": usage_frequency,
        "support_tickets_opened": support_tickets,
        "active_users": active_users,
        "contract_months": contract_months,
        "monthly_spend": monthly_spend,
        "churn": churn
    })
    
    os.makedirs("data", exist_ok=True)
    df.to_csv("data/churn_dataset.csv", index=False)
    print("Saved synthetic dataset to data/churn_dataset.csv")
    
    X = df.drop(columns=["churn"])
    y = df["churn"]
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    # Setup MLflow Tracking
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "sqlite:///mlruns.db")
    mlflow.set_tracking_uri(tracking_uri)
    print(f"MLflow Tracking URI set to: {tracking_uri}")
    
    mlflow.set_experiment("CustomerCore-Churn")
    
    # Define models to train and compare
    models_to_train = {
        "Logistic-Regression": LogisticRegression(random_state=42, max_iter=1000),
        "Random-Forest": RandomForestClassifier(random_state=42),
        "Gradient-Boosting": GradientBoostingClassifier(random_state=42)
    }
    
    best_model_name = None
    best_f1 = -1.0
    best_version = None
    best_metrics = None
    all_runs_versions = []
    
    # Log Pandas DataFrame as MLflow dataset for the runs
    mlflow_dataset = mlflow.data.from_pandas(df, targets="churn", name="churn_dataset")
    
    for name, clf in models_to_train.items():
        run_name = f"{name}-Baseline"
        print(f"\n--- Training and evaluating {name} ---")
        
        with mlflow.start_run(run_name=run_name):
            # Log dataset input context
            mlflow.log_input(mlflow_dataset, context="training")
            
            clf.fit(X_train, y_train)
            y_pred = clf.predict(X_test)
            y_proba = clf.predict_proba(X_test)[:, 1] if hasattr(clf, "predict_proba") else None
            
            # Compute metrics
            fpr, tpr, _ = roc_curve(y_test, y_proba) if y_proba is not None else (None, None, None)
            roc_auc = auc(fpr, tpr) if fpr is not None else 0.0
            acc = accuracy_score(y_test, y_pred)
            f1 = f1_score(y_test, y_pred)
            rec = recall_score(y_test, y_pred)
            prec = precision_score(y_test, y_pred)
            
            metrics = {
                "auc": round(float(roc_auc), 3),
                "accuracy": round(float(acc), 3),
                "f1_score": round(float(f1), 3),
                "recall": round(float(rec), 3),
                "precision": round(float(prec), 3)
            }
            
            print(f"Metrics for {name}: {metrics}")
            
            # Log hyperparams
            if hasattr(clf, "n_estimators"):
                mlflow.log_param("n_estimators", clf.n_estimators)
            if hasattr(clf, "criterion"):
                mlflow.log_param("criterion", clf.criterion)
            if hasattr(clf, "max_depth"):
                mlflow.log_param("max_depth", clf.max_depth)
            if hasattr(clf, "C"):
                mlflow.log_param("C", clf.C)
                
            mlflow.log_param("random_state", 42)
            mlflow.log_param("test_size", 0.2)
            
            # Log metrics
            mlflow.log_metrics(metrics)
            
            # Generate and save plots
            # ROC Curve
            plt.figure(figsize=(6, 5))
            if fpr is not None:
                plt.plot(fpr, tpr, color='darkorange', lw=2, label=f'ROC curve (AUC = {roc_auc:.3f})')
            plt.plot([0, 1], [0, 1], color='navy', lw=2, linestyle='--')
            plt.xlim([0.0, 1.0])
            plt.ylim([0.0, 1.05])
            plt.xlabel('False Positive Rate')
            plt.ylabel('True Positive Rate')
            plt.title(f'ROC - {name}')
            plt.legend(loc="lower right")
            plt.tight_layout()
            roc_path = f"data/{name.lower()}_roc_curve.png"
            plt.savefig(roc_path, dpi=150)
            plt.close()
            
            # Confusion Matrix
            cm = confusion_matrix(y_test, y_pred)
            plt.figure(figsize=(5, 4))
            plt.imshow(cm, interpolation='nearest', cmap=plt.cm.Blues)
            plt.title(f'CM - {name}')
            plt.colorbar()
            tick_marks = np.arange(2)
            plt.xticks(tick_marks, ['No Churn', 'Churn'])
            plt.yticks(tick_marks, ['No Churn', 'Churn'])
            thresh = cm.max() / 2.
            for i in range(cm.shape[0]):
                for j in range(cm.shape[1]):
                    plt.text(j, i, format(cm[i, j], 'd'),
                             ha="center", va="center",
                             color="white" if cm[i, j] > thresh else "black")
            plt.ylabel('True label')
            plt.xlabel('Predicted label')
            plt.tight_layout()
            cm_path = f"data/{name.lower()}_confusion_matrix.png"
            plt.savefig(cm_path, dpi=150)
            plt.close()
            
            # Feature Importance (if applicable)
            importances = None
            if hasattr(clf, "feature_importances_"):
                importances = clf.feature_importances_
            elif hasattr(clf, "coef_"):
                importances = np.abs(clf.coef_[0])
                
            if importances is not None:
                indices = np.argsort(importances)
                plt.figure(figsize=(6, 4))
                plt.title(f'Feature Importances - {name}')
                plt.barh(range(len(indices)), importances[indices], color='b', align='center')
                plt.yticks(range(len(indices)), [X.columns[i] for i in indices])
                plt.xlabel('Relative Importance')
                plt.tight_layout()
                fi_path = f"data/{name.lower()}_feature_importance.png"
                plt.savefig(fi_path, dpi=150)
                plt.close()
                mlflow.log_artifact(fi_path, "plots")
            
            # Log artifacts
            mlflow.log_artifact(roc_path, "plots")
            mlflow.log_artifact(cm_path, "plots")
            
            # Infer signature and log/register the model atomically to avoid backend resolution delay
            signature = infer_signature(X_test, y_pred)
            model_info = mlflow.sklearn.log_model(
                sk_model=clf,
                artifact_path="model",
                registered_model_name="customercore-churn-classifier",
                signature=signature,
                input_example=X_train.head(3)
            )
            
            # Fetch registered version
            version = None
            if model_info is not None and hasattr(model_info, "registered_model_version"):
                version = model_info.registered_model_version
                print(f"Model registered successfully. Version: {version}")
                
            if version is None:
                try:
                    client = mlflow.MlflowClient()
                    latest = client.get_latest_versions("customercore-churn-classifier")
                    if latest:
                        version = latest[0].version
                        print(f"Model version queried from registry: {version}")
                except Exception as e:
                    print(f"Could not retrieve latest model version: {e}")
            
            all_runs_versions.append((name, version, f1))
            
            # Keep track of the best performing model by F1-Score
            if f1 > best_f1:
                best_f1 = f1
                best_model_name = name
                best_version = version
                best_metrics = metrics

    # Save metrics of best model to metrics.json
    with open("data/metrics.json", "w") as f:
        json.dump(best_metrics, f, indent=2)

    # Copy best model's plots to standard paths for CML reporting
    import shutil
    try:
        shutil.copy(f"data/{best_model_name.lower()}_roc_curve.png", "data/roc_curve.png")
        shutil.copy(f"data/{best_model_name.lower()}_confusion_matrix.png", "data/confusion_matrix.png")
        if os.path.exists(f"data/{best_model_name.lower()}_feature_importance.png"):
            shutil.copy(f"data/{best_model_name.lower()}_feature_importance.png", "data/feature_importance.png")
        print("Best model plots copied to standard paths for CML reporting.")
    except Exception as e:
        print(f"Failed to copy standard plots: {e}")

    print("\n==========================================")
    print(f"Best Model Selected: {best_model_name} (F1: {best_f1:.3f}) with Version: {best_version}")
    print("==========================================")
    
    # Wait for the model version to finish creation in registry
    print("Waiting for model version registry propagation...")
    time.sleep(5)
    
    # Promote/Transition the best model version to "Production" and archive the rest
    client = mlflow.MlflowClient()
    for name, ver, f1 in all_runs_versions:
        if ver is not None:
            if ver == best_version:
                print(f"Promoting model version {ver} ({name}) to stage 'Production'...")
                try:
                    client.transition_model_version_stage(
                        name="customercore-churn-classifier",
                        version=str(ver),
                        stage="Production"
                    )
                    # Set version description separately
                    client.update_model_version(
                        name="customercore-churn-classifier",
                        version=str(ver),
                        description=(
                            f"Auto-promoted best model ({name}) based on evaluation F1-Score: {f1:.3f}. "
                            f"Evaluation metrics: Accuracy={best_metrics['accuracy']:.3f}, AUC-ROC={best_metrics['auc']:.3f}."
                        )
                    )
                    print(f"Model version {ver} successfully promoted to 'Production'.")
                except Exception as e:
                    print(f"Could not transition best model version {ver} to Production: {e}")
            else:
                print(f"Archiving model version {ver} ({name}) with F1-Score: {f1:.3f}...")
                try:
                    client.transition_model_version_stage(
                        name="customercore-churn-classifier",
                        version=str(ver),
                        stage="Archived"
                    )
                    # Set version description separately
                    client.update_model_version(
                        name="customercore-churn-classifier",
                        version=str(ver),
                        description=f"Baseline run for {name}. F1-Score: {f1:.3f}. Superseded by best model."
                    )
                    print(f"Model version {ver} successfully archived.")
                except Exception as e:
                    print(f"Could not transition version {ver} to Archived: {e}")
        
    print("\nMLflow multi-model training and best model registration completed successfully!")

if __name__ == "__main__":
    train()

