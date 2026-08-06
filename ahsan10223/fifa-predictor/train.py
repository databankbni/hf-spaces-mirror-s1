import os
import pickle
import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.metrics import accuracy_score, log_loss
import matplotlib.pyplot as plt

def clean_team_name(team):
    mapping = {
        'West Germany': 'Germany',
        'Czechoslovakia': 'Czech Republic',
        'Soviet Union': 'Russia',
        'Yugoslavia': 'Serbia',
        'German DR': 'Germany'
    }
    return mapping.get(team, team)

def get_tournament_type(tournament):
    tourn = tournament.lower()
    if 'fifa world cup' in tourn and 'qualification' not in tourn:
        return 3
    elif any(x in tourn for x in ['euro', 'copa', 'african cup of nations', 'asian cup', 'gold cup', 'nations cup', 'nations league']):
        if 'qualification' in tourn or 'qualifying' in tourn:
            return 1
        return 2
    elif 'qualification' in tourn or 'qualifying' in tourn or 'prep' in tourn:
        return 1
    elif 'friendly' in tourn:
        return 0
    else:
        return 0

def get_k_factor(tourn_type):
    if tourn_type == 3:
        return 60
    elif tourn_type == 2:
        return 50
    elif tourn_type == 1:
        return 40
    else:
        return 30

def main():
    print("Step 1: Downloading dataset results.csv...")
    url = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
    try:
        df = pd.read_csv(url)
    except Exception as e:
        print(f"Error fetching dataset from GitHub: {e}")
        print("Using empty or fallback data...")
        return
        
    print(f"Dataset loaded. Total matches: {len(df)}")
    
    # Sort columns and filter
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(by='date').reset_index(drop=True)
    
    # Clean team names
    df['home_team'] = df['home_team'].apply(clean_team_name)
    df['away_team'] = df['away_team'].apply(clean_team_name)
    
    # Target Variable: 0 = Home Win, 1 = Draw, 2 = Away Win
    df['target'] = 1 # Draw
    df.loc[df['home_score'] > df['away_score'], 'target'] = 0
    df.loc[df['home_score'] < df['away_score'], 'target'] = 2
    
    # Trackers for chronological calculations
    team_elos = {}
    team_last_date = {}
    team_results = {}
    team_goals_scored = {}
    team_goals_conceded = {}
    h2h_history = {} # (teamA, teamB) -> list of outcomes (from perspective of teamA)
    
    # Lists to store computed features
    features_list = []
    
    print("Step 2: Processing matches and computing features chronologically...")
    for idx, row in df.iterrows():
        date = row['date']
        home_team = row['home_team']
        away_team = row['away_team']
        home_score = row['home_score']
        away_score = row['away_score']
        tournament = row['tournament']
        neutral = 1 if row['neutral'] else 0
        
        # Get tournament type and K-factor
        tourn_type = get_tournament_type(tournament)
        k_factor = get_k_factor(tourn_type)
        
        # Get Elo ratings BEFORE the match
        home_elo = team_elos.get(home_team, 1500.0)
        away_elo = team_elos.get(away_team, 1500.0)
        
        # Compute Elo diff
        elo_diff = home_elo - away_elo
        
        # Compute Forms BEFORE the match
        def compute_form(team):
            history = team_results.get(team, [])
            if not history:
                return 0.5
            padded = [0.5] * (5 - len(history)) + history[-5:]
            weights = [0.1, 0.15, 0.2, 0.25, 0.3]
            return sum(w * val for w, val in zip(weights, padded))
            
        home_form = compute_form(home_team)
        away_form = compute_form(away_team)
        
        # Compute average goals scored/conceded BEFORE the match
        def compute_goals_avg(team, scored=True):
            goals = team_goals_scored.get(team, []) if scored else team_goals_conceded.get(team, [])
            if not goals:
                return 1.0
            recent = goals[-5:]
            return sum(recent) / len(recent)
            
        home_goals_scored_avg = compute_goals_avg(home_team, scored=True)
        away_goals_scored_avg = compute_goals_avg(away_team, scored=True)
        home_goals_conceded_avg = compute_goals_avg(home_team, scored=False)
        away_goals_conceded_avg = compute_goals_avg(away_team, scored=False)
        
        # Compute days since last match
        def compute_days_since_last(team, current_date):
            last_date = team_last_date.get(team)
            if last_date is None:
                return 180.0
            return float((current_date - last_date).days)
            
        days_since_home_last = compute_days_since_last(home_team, date)
        days_since_away_last = compute_days_since_last(away_team, date)
        
        # Compute Head-to-Head win rate BEFORE the match
        def compute_h2h_win_rate(t_home, t_away):
            key = tuple(sorted([t_home, t_away]))
            history = h2h_history.get(key, [])
            if not history:
                return 0.5
            outcomes = []
            for t1, t2, val in history[-10:]:
                if t_home == t1:
                    outcomes.append(val)
                else:
                    outcomes.append(1.0 - val)
            return sum(outcomes) / len(outcomes)
            
        h2h = compute_h2h_win_rate(home_team, away_team)
        
        # Append features
        features_list.append({
            'elo_diff': elo_diff,
            'home_form': home_form,
            'away_form': away_form,
            'home_goals_scored_avg': home_goals_scored_avg,
            'away_goals_scored_avg': away_goals_scored_avg,
            'home_goals_conceded_avg': home_goals_conceded_avg,
            'away_goals_conceded_avg': away_goals_conceded_avg,
            'tournament_type': tourn_type,
            'neutral_venue': neutral,
            'days_since_home_last': days_since_home_last,
            'days_since_away_last': days_since_away_last,
            'head_to_head': h2h
        })
        
        # Update Elo ratings
        expected_home = 1.0 / (1.0 + 10.0**((away_elo - home_elo) / 400.0))
        expected_away = 1.0 - expected_home
        
        # actual match outcome
        if home_score > away_score:
            actual_home = 1.0
            actual_away = 0.0
            outcome_home = 1.0
            outcome_away = 0.0
        elif home_score == away_score:
            actual_home = 0.5
            actual_away = 0.5
            outcome_home = 0.5
            outcome_away = 0.5
        else:
            actual_home = 0.0
            actual_away = 1.0
            outcome_home = 0.0
            outcome_away = 1.0
            
        team_elos[home_team] = home_elo + k_factor * (actual_home - expected_home)
        team_elos[away_team] = away_elo + k_factor * (actual_away - expected_away)
        
        # Update last match dates
        team_last_date[home_team] = date
        team_last_date[away_team] = date
        
        # Update match outcome histories
        team_results.setdefault(home_team, []).append(outcome_home)
        team_results.setdefault(away_team, []).append(outcome_away)
        
        # Update goals scored/conceded histories
        team_goals_scored.setdefault(home_team, []).append(home_score)
        team_goals_conceded.setdefault(home_team, []).append(away_score)
        team_goals_scored.setdefault(away_team, []).append(away_score)
        team_goals_conceded.setdefault(away_team, []).append(home_score)
        
        # Update H2H history
        key = tuple(sorted([home_team, away_team]))
        h2h_history.setdefault(key, []).append((key[0], key[1], outcome_home if key[0] == home_team else outcome_away))
        
    features_df = pd.DataFrame(features_list)
    df = pd.concat([df, features_df], axis=1)
    
    # Feature names
    feature_names = list(features_df.columns)
    print(f"Features created: {feature_names}")
    
    # Data Split:
    # Train: All matches before 2018-01-01
    # Validation: 2018 World Cup matches
    # Test: 2022 World Cup matches
    
    train_mask = df['date'] < pd.to_datetime('2018-01-01')
    
    # Filter 2018 World Cup: tournament == 'FIFA World Cup' and year 2018
    val_mask = (df['tournament'] == 'FIFA World Cup') & (df['date'].dt.year == 2018)
    
    # Filter 2022 World Cup: tournament == 'FIFA World Cup' and year 2022
    test_mask = (df['tournament'] == 'FIFA World Cup') & (df['date'].dt.year == 2022)
    
    X_train, y_train = df.loc[train_mask, feature_names], df.loc[train_mask, 'target']
    X_val, y_val = df.loc[val_mask, feature_names], df.loc[val_mask, 'target']
    X_test, y_test = df.loc[test_mask, feature_names], df.loc[test_mask, 'target']
    
    print(f"Train set size: {X_train.shape[0]}")
    print(f"Validation set size: {X_val.shape[0]}")
    print(f"Test set size: {X_test.shape[0]}")
    
    # Train XGBoost Classifier
    print("Step 3: Training XGBoost model...")
    
    # Note: Use early stopping by setting early_stopping_rounds in XGBClassifier and passing eval_set in fit
    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=8,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        objective='multi:softprob',
        eval_metric='mlogloss',
        random_state=42,
        early_stopping_rounds=15
    )
    
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=True
    )
    
    # Evaluation
    y_pred_train = model.predict(X_train)
    y_pred_val = model.predict(X_val)
    y_pred_test = model.predict(X_test)
    
    y_prob_train = model.predict_proba(X_train)
    y_prob_val = model.predict_proba(X_val)
    y_prob_test = model.predict_proba(X_test)
    
    print("\n--- Model Evaluation ---")
    print(f"Train Accuracy: {accuracy_score(y_train, y_pred_train):.4f} | Train Log Loss: {log_loss(y_train, y_prob_train):.4f}")
    print(f"Val Accuracy: {accuracy_score(y_val, y_pred_val):.4f} | Val Log Loss: {log_loss(y_val, y_prob_val):.4f}")
    print(f"Test Accuracy: {accuracy_score(y_test, y_pred_test):.4f} | Test Log Loss: {log_loss(y_test, y_prob_test):.4f}")
    
    # Feature Importance
    fig, ax = plt.subplots(figsize=(10, 6))
    xgb.plot_importance(model, ax=ax, importance_type='weight')
    plt.title("XGBoost Feature Importance (Weight)")
    plt.tight_layout()
    plt.savefig("feature_importance.png")
    print("Feature importance plot saved as 'feature_importance.png'")
    
    # Save Model & Auxiliary Data
    print("\nStep 4: Saving model assets...")
    
    # Save model using pickle
    with open('model.pkl', 'wb') as f:
        pickle.dump(model, f)
    
    # Save auxiliary data for Flask app
    # Flask app needs:
    # 1. Final team Elo ratings
    # 2. Final team outcomes histories and last dates for computing features for predictions
    # 3. Final goals scored/conceded histories
    # 4. H2H history
    # 5. List of feature names
    
    # Convert dates to string/ISO format to prevent pickle issues or keep as Timestamp
    # Convert team_last_date to string representations
    team_last_date_str = {k: v.strftime('%Y-%m-%d') for k, v in team_last_date.items()}
    
    # We will bundle team_last_date, team_results, team_goals_scored, team_goals_conceded, and h2h_history in forms
    team_forms_data = {
        'last_match_dates': team_last_date_str,
        'results_history': team_results,
        'goals_scored_history': team_goals_scored,
        'goals_conceded_history': team_goals_conceded,
        'h2h_history': h2h_history
    }
    
    with open('team_elos.pkl', 'wb') as f:
        pickle.dump(team_elos, f)
        
    with open('team_forms.pkl', 'wb') as f:
        pickle.dump(team_forms_data, f)
        
    with open('feature_names.pkl', 'wb') as f:
        pickle.dump(feature_names, f)
        
    print("All model assets saved successfully! (model.pkl, team_elos.pkl, team_forms.pkl, feature_names.pkl)")

if __name__ == '__main__':
    main()
