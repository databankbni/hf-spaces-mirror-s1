import numpy as np
import json

best_thresholds = [('toxic', np.float64(0.5199999999999998), 0.8404494382022472),
('severe_toxic', np.float64(0.4599999999999999), 0.5575757575757576),
('obscene', np.float64(0.4399999999999999), 0.8489289740698985),
('threat', np.float64(0.35999999999999993), 0.5607476635514018),
('insult', np.float64(0.5199999999999998), 0.7653123104912067),
('identity_hate', np.float64(0.26), 0.5893416927899686)]

thresholds = {
    label : float(t) for label, t, _ in best_thresholds
}

with open("thresholds.json", "w") as f:
    json.dump(thresholds, f, indent=2)

print(thresholds)
