import json
from app import app

def run_tests():
    client = app.test_client()

    print("Testing prediction endpoint /predict...")
    pred_response = client.post('/predict', data=json.dumps({
        'home_team': 'Argentina',
        'away_team': 'France',
        'tournament': 'FIFA World Cup',
        'venue': 'Neutral'
    }), content_type='application/json')

    print(f"Status Code: {pred_response.status_code}")
    pred_data = json.loads(pred_response.data.decode('utf-8'))
    print(f"Response Data: {pred_data}")

    assert pred_response.status_code == 200
    assert 'probabilities' in pred_data
    assert 'home_win' in pred_data['probabilities']
    assert 'draw' in pred_data['probabilities']
    assert 'away_win' in pred_data['probabilities']
    assert pred_data['home_team'] == 'Argentina'
    assert pred_data['away_team'] == 'France'

    print("Prediction endpoint tested successfully!\n")

    print("Testing simulation endpoint /simulate...")
    sim_response = client.post('/simulate', content_type='application/json')
    print(f"Status Code: {sim_response.status_code}")
    sim_data = json.loads(sim_response.data.decode('utf-8'))
    print(f"Simulation Count: {sim_data.get('simulation_count')}")
    print(f"Number of teams in probabilities: {len(sim_data.get('probabilities', []))}")
    print(f"Sample bracket keys: {sim_data.get('sample_bracket', {}).keys()}")

    assert sim_response.status_code == 200
    assert sim_data.get('simulation_count') == 1000
    assert len(sim_data.get('probabilities', [])) == 48
    assert 'groups' in sim_data['sample_bracket']
    assert 'r32' in sim_data['sample_bracket']
    assert 'r16' in sim_data['sample_bracket']
    assert 'qf' in sim_data['sample_bracket']
    assert 'sf' in sim_data['sample_bracket']
    assert 'final' in sim_data['sample_bracket']

    print("Simulation endpoint tested successfully!\n")
    print("ALL TESTS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    run_tests()
