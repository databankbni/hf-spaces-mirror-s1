import os
import pickle
import datetime
import pandas as pd
import numpy as np
import xgboost as xgb
from flask import Flask, request, jsonify, render_template, send_file

app = Flask(__name__)

# Model and state paths
MODEL_PATH = 'model.pkl'
ELOS_PATH = 'team_elos.pkl'
FORMS_PATH = 'team_forms.pkl'
FEATURE_NAMES_PATH = 'feature_names.pkl'

# Global model and metadata cache
model = None
team_elos = {}
team_forms = {}
feature_names = []

# List of 48 World Cup teams (2026 Qualified Teams)
WORLD_CUP_TEAMS = [
    'Algeria', 'Argentina', 'Australia', 'Austria', 'Belgium', 'Bosnia and Herzegovina', 'Brazil', 'Canada', 'Cape Verde', 'Colombia',
    'Croatia', 'Curacao', 'Czech Republic', 'DR Congo', 'Ecuador', 'Egypt', 'England', 'France', 'Germany', 'Ghana',
    'Haiti', 'Iran', 'Iraq', 'Ivory Coast', 'Japan', 'Jordan', 'Mexico', 'Morocco', 'Netherlands', 'New Zealand',
    'Norway', 'Panama', 'Paraguay', 'Portugal', 'Qatar', 'Saudi Arabia', 'Scotland', 'Senegal', 'South Africa', 'South Korea',
    'Spain', 'Sweden', 'Switzerland', 'Tunisia', 'Turkey', 'United States', 'Uruguay', 'Uzbekistan'
]

def clean_team_name(team):
    mapping = {
        'West Germany': 'Germany',
        'Czechoslovakia': 'Czech Republic',
        'Soviet Union': 'Russia',
        'Yugoslavia': 'Serbia',
        'German DR': 'Germany',
        "Côte d'Ivoire": "Ivory Coast",
        "Cabo Verde": "Cape Verde",
        "Curaçao": "Curacao",
        "Curaao": "Curacao"
    }
    if isinstance(team, str):
        if 'Cura' in team:
            return 'Curacao'
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

def compile_assets():
    """Download data, run chronological Elo system and train model if pickle files are missing."""
    print("--- Running automatic asset compilation ---")
    url = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
    try:
        df = pd.read_csv(url)
    except Exception as e:
        print(f"Error fetching dataset: {e}")
        # Build mock data so app doesn't crash if offline
        df = pd.DataFrame(columns=['date', 'home_team', 'away_team', 'home_score', 'away_score', 'tournament', 'neutral'])
    
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(by='date').reset_index(drop=True)
    df['home_team'] = df['home_team'].apply(clean_team_name)
    df['away_team'] = df['away_team'].apply(clean_team_name)
    
    df['target'] = 1
    df.loc[df['home_score'] > df['away_score'], 'target'] = 0
    df.loc[df['home_score'] < df['away_score'], 'target'] = 2
    
    elos = {}
    last_dates = {}
    results = {}
    goals_scored = {}
    goals_conceded = {}
    h2h = {}
    
    features = []
    
    for idx, row in df.iterrows():
        date = row['date']
        home_team = row['home_team']
        away_team = row['away_team']
        home_score = row['home_score']
        away_score = row['away_score']
        tournament = row['tournament']
        neutral = 1 if row['neutral'] else 0
        
        tourn_type = get_tournament_type(tournament)
        k = get_k_factor(tourn_type)
        
        h_elo = elos.get(home_team, 1500.0)
        a_elo = elos.get(away_team, 1500.0)
        elo_diff = h_elo - a_elo
        
        def form(team):
            hist = results.get(team, [])
            if not hist:
                return 0.5
            padded = [0.5] * (5 - len(hist)) + hist[-5:]
            weights = [0.1, 0.15, 0.2, 0.25, 0.3]
            return sum(w * val for w, val in zip(weights, padded))
            
        h_form = form(home_team)
        a_form = form(away_team)
        
        def g_avg(team, scored=True):
            gls = goals_scored.get(team, []) if scored else goals_conceded.get(team, [])
            if not gls:
                return 1.0
            return sum(gls[-5:]) / len(gls[-5:])
            
        h_scored = g_avg(home_team, True)
        a_scored = g_avg(away_team, True)
        h_conceded = g_avg(home_team, False)
        a_conceded = g_avg(away_team, False)
        
        def days_last(team, curr):
            last = last_dates.get(team)
            if last is None:
                return 180.0
            return float((curr - last).days)
            
        days_h = days_last(home_team, date)
        days_a = days_last(away_team, date)
        
        def h2h_rate(h_t, a_t):
            key = tuple(sorted([h_t, a_t]))
            hist = h2h.get(key, [])
            if not hist:
                return 0.5
            out = []
            for t1, t2, val in hist[-10:]:
                if h_t == t1:
                    out.append(val)
                else:
                    out.append(1.0 - val)
            return sum(out) / len(out)
            
        h2h_win = h2h_rate(home_team, away_team)
        
        features.append({
            'elo_diff': elo_diff,
            'home_form': h_form,
            'away_form': a_form,
            'home_goals_scored_avg': h_scored,
            'away_goals_scored_avg': a_scored,
            'home_goals_conceded_avg': h_conceded,
            'away_goals_conceded_avg': a_conceded,
            'tournament_type': tourn_type,
            'neutral_venue': neutral,
            'days_since_home_last': days_h,
            'days_since_away_last': days_a,
            'head_to_head': h2h_win
        })
        
        expected_home = 1.0 / (1.0 + 10.0**((a_elo - h_elo) / 400.0))
        expected_away = 1.0 - expected_home
        
        if home_score > away_score:
            act_h, act_a = 1.0, 0.0
            out_h, out_a = 1.0, 0.0
        elif home_score == away_score:
            act_h, act_a = 0.5, 0.5
            out_h, out_a = 0.5, 0.5
        else:
            act_h, act_a = 0.0, 1.0
            out_h, out_a = 0.0, 1.0
            
        elos[home_team] = h_elo + k * (act_h - expected_home)
        elos[away_team] = a_elo + k * (act_a - expected_away)
        
        last_dates[home_team] = date
        last_dates[away_team] = date
        
        results.setdefault(home_team, []).append(out_h)
        results.setdefault(away_team, []).append(out_a)
        
        goals_scored.setdefault(home_team, []).append(home_score)
        goals_conceded.setdefault(home_team, []).append(away_score)
        goals_scored.setdefault(away_team, []).append(away_score)
        goals_conceded.setdefault(away_team, []).append(home_score)
        
        key = tuple(sorted([home_team, away_team]))
        h2h.setdefault(key, []).append((key[0], key[1], out_h if key[0] == home_team else out_a))
        
    features_df = pd.DataFrame(features)
    feature_cols = list(features_df.columns)
    
    train_mask = df['date'] < pd.to_datetime('2018-01-01')
    val_mask = (df['tournament'] == 'FIFA World Cup') & (df['date'].dt.year == 2018)
    
    X_train = features_df.loc[train_mask]
    y_train = df.loc[train_mask, 'target']
    X_val = features_df.loc[val_mask]
    y_val = df.loc[val_mask, 'target']
    
    model_xgb = xgb.XGBClassifier(
        n_estimators=200, max_depth=8, learning_rate=0.1, subsample=0.8, colsample_bytree=0.8,
        objective='multi:softprob', eval_metric='mlogloss', random_state=42, early_stopping_rounds=15
    )
    
    model_xgb.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    
    # Save files
    with open(MODEL_PATH, 'wb') as f:
        pickle.dump(model_xgb, f)
        
    last_dates_str = {k: v.strftime('%Y-%m-%d') for k, v in last_dates.items()}
    forms_data = {
        'last_match_dates': last_dates_str,
        'results_history': results,
        'goals_scored_history': goals_scored,
        'goals_conceded_history': goals_conceded,
        'h2h_history': h2h
    }
    
    with open(ELOS_PATH, 'wb') as f:
        pickle.dump(elos, f)
    with open(FORMS_PATH, 'wb') as f:
        pickle.dump(forms_data, f)
    with open(FEATURE_NAMES_PATH, 'wb') as f:
        pickle.dump(feature_cols, f)
        
    print("--- Compilation Complete ---")

def load_assets():
    global model, team_elos, team_forms, feature_names
    if not (os.path.exists(MODEL_PATH) and os.path.exists(ELOS_PATH) and os.path.exists(FORMS_PATH) and os.path.exists(FEATURE_NAMES_PATH)):
        compile_assets()
        
    with open(MODEL_PATH, 'rb') as f:
        model = pickle.load(f)
    with open(ELOS_PATH, 'rb') as f:
        team_elos = pickle.load(f)
    with open(FORMS_PATH, 'rb') as f:
        team_forms = pickle.load(f)
    with open(FEATURE_NAMES_PATH, 'rb') as f:
        feature_names = pickle.load(f)

# Load assets at startup
load_assets()

def get_prediction_features(home_team, away_team, tournament_name, neutral_venue_val):
    # Retrieve Elo ratings
    home_elo = team_elos.get(home_team, 1500.0)
    away_elo = team_elos.get(away_team, 1500.0)
    elo_diff = home_elo - away_elo
    
    # Retrieve form
    def compute_team_form(team):
        history = team_forms.get('results_history', {}).get(team, [])
        if not history:
            return 0.5
        padded = [0.5] * (5 - len(history)) + history[-5:]
        weights = [0.1, 0.15, 0.2, 0.25, 0.3]
        return sum(w * val for w, val in zip(weights, padded))
        
    home_form = compute_team_form(home_team)
    away_form = compute_team_form(away_team)
    
    # Retrieve goals
    def compute_goals_avg(team, scored=True):
        history_key = 'goals_scored_history' if scored else 'goals_conceded_history'
        goals = team_forms.get(history_key, {}).get(team, [])
        if not goals:
            return 1.0
        recent = goals[-5:]
        return sum(recent) / len(recent)
        
    home_goals_scored_avg = compute_goals_avg(home_team, scored=True)
    away_goals_scored_avg = compute_goals_avg(away_team, scored=True)
    home_goals_conceded_avg = compute_goals_avg(home_team, scored=False)
    away_goals_conceded_avg = compute_goals_avg(away_team, scored=False)
    
    # Days since last match
    today = datetime.date.today()
    def compute_days_since_last(team):
        date_str = team_forms.get('last_match_dates', {}).get(team)
        if not date_str:
            return 180.0
        try:
            last_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            diff = (today - last_date).days
            return float(max(0, diff))
        except:
            return 180.0
            
    days_since_home_last = compute_days_since_last(home_team)
    days_since_away_last = compute_days_since_last(away_team)
    
    # Head-to-Head win rate
    def compute_h2h(t_home, t_away):
        key = tuple(sorted([t_home, t_away]))
        history = team_forms.get('h2h_history', {}).get(key, [])
        if not history:
            return 0.5
        outcomes = []
        for t1, t2, val in history[-10:]:
            if t_home == t1:
                outcomes.append(val)
            else:
                outcomes.append(1.0 - val)
        return sum(outcomes) / len(outcomes)
        
    h2h = compute_h2h(home_team, away_team)
    
    # Get tournament type
    tourn_type = get_tournament_type(tournament_name)
    
    return {
        'elo_diff': elo_diff,
        'home_form': home_form,
        'away_form': away_form,
        'home_goals_scored_avg': home_goals_scored_avg,
        'away_goals_scored_avg': away_goals_scored_avg,
        'home_goals_conceded_avg': home_goals_conceded_avg,
        'away_goals_conceded_avg': away_goals_conceded_avg,
        'tournament_type': tourn_type,
        'neutral_venue': neutral_venue_val,
        'days_since_home_last': days_since_home_last,
        'days_since_away_last': days_since_away_last,
        'head_to_head': h2h
    }

@app.route('/image.png')
def bg_image():
    return send_file(os.path.join(os.path.dirname(__file__), 'templates', 'image.png'), mimetype='image/png')

@app.route('/')
def index():
    return render_template('index.html', teams=WORLD_CUP_TEAMS)

@app.route('/predict', methods=['POST'])
def predict():
    try:
        data = request.get_json() or {}
        home_team = data.get('home_team')
        away_team = data.get('away_team')
        tournament = data.get('tournament', 'FIFA World Cup')
        venue = data.get('venue', 'Neutral')
        
        if not home_team or not away_team:
            return jsonify({'error': 'Please provide both home_team and away_team'}), 400
            
        if home_team == away_team:
            return jsonify({'error': 'Home and Away teams must be different'}), 400
            
        # Handle venue swapping logic
        swapped = False
        if venue == 'Away':
            actual_home_team = away_team
            actual_away_team = home_team
            neutral_venue_val = 0
            swapped = True
        elif venue == 'Home':
            actual_home_team = home_team
            actual_away_team = away_team
            neutral_venue_val = 0
        else:
            actual_home_team = home_team
            actual_away_team = away_team
            neutral_venue_val = 1
            
        features = get_prediction_features(actual_home_team, actual_away_team, tournament, neutral_venue_val)
        input_df = pd.DataFrame([features])[feature_names]
        probabilities = model.predict_proba(input_df)[0]
        
        p_home = float(probabilities[0])
        p_draw = float(probabilities[1])
        p_away = float(probabilities[2])
        
        if swapped:
            p_home, p_away = p_away, p_home
            
        max_prob = max(p_home, p_draw, p_away)
        if max_prob == p_home:
            winner = home_team
            outcome = "Home Win"
        elif max_prob == p_away:
            winner = away_team
            outcome = "Away Win"
        else:
            winner = "Draw"
            outcome = "Draw"
            
        return jsonify({
            'home_team': home_team,
            'away_team': away_team,
            'probabilities': {
                'home_win': round(p_home * 100, 1),
                'draw': round(p_draw * 100, 1),
                'away_win': round(p_away * 100, 1)
            },
            'predicted_winner': winner,
            'predicted_outcome': outcome
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=7860)  
