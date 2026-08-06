# CKB 17-variable single-sample model package

This directory is a portable inference package built from the completed CKB
17-variable analysis. It contains the frozen K=3 cluster assignment model,
its cluster SHAP surrogate, the selected classifier for each of 13 incident
outcomes, and the 13 pre-fitted SHAP explanation artifacts.

## What is included

The package has 28 model artifacts in the requested accounting:

- 1 frozen CKB nearest-centroid cluster model + 1 multiclass cluster SHAP
  surrogate;
- 13 selected outcome classifiers + 13 outcome SHAP regression surrogates.

The 13 `shap_explainer.pkl` files are runtime explanation objects for those
13 SHAP surrogates. They are not additional prediction models, but are needed
to reproduce the saved single-sample force plots without refitting an
explainer.

The selected outcome classifiers are MLP for death, A00_B99, C00_D48, E00_E90,
G00_G99, I00_I99, J00_J99, K00_K93, M00_M99, and N00_N99; RandomForest is used
for F00_F99, H00_H95, and L00_L99. The exact thresholds and provenance are in
`manifest.json`.

## Command-line use

Run from any directory with the bundled Python executable:


By default, a timestamped directory is created under
`1-output/model/predictions/`. It contains:

- `single_sample_prediction.json`: cluster result, 13 probabilities, frozen
  Youden thresholds, and high/low risk classifications;
- `force_plots/single_sample_cluster_C1_force.html` through `C3`: one force
  plot for each class of the cluster SHAP surrogate;
- `force_plots/single_sample_<outcome>_force.html`: one force plot per outcome.

To choose an explicit output directory:


Use `--no-force-plots` when only the JSON prediction is required. Force plots
use SHAP's interactive HTML format and can be opened in a browser.

## Python API

```python
import sys

sys.path.insert(0, r"C:\Users\Lenovo\Desktop\paper\CKB UKB\1-output\model")
from predict_single import predict_one

features = {
    "sex": 1,
    "age": 55,
    "edu_level": 2,
    "marital_status": 1,
    "work": 1,
    "retire": 0,
    "hh_size": 3,
    "smoking": 0,
    "alcohol": 1,
    "height_cm": 165,
    "weight_kg": 65,
    "waist_cm": 82,
    "sbp_mmhg": 125,
    "dbp_mmhg": 78,
    "bp_drugs": 0,
    "self_health": 2,
    "chronic_pain": 0,
}

result = predict_one(
    features,
    output_dir=r"C:\path\to\my_prediction",
    make_force_plots=True,
    sample_id="person_001",
)

print(result["cluster"])
print(result["outcomes"]["death"])
print(result["result_json"])
```

## Interpretation and safeguards

1. The 17 input values must use the same coding and units as CKB training.
   The package does not infer recoding rules and does not impute missing
   values. Extra fields, such as `region_code`, are ignored and listed in the
   output JSON.
2. The cluster assignment applies the frozen log1p/mean/SD parameters and
   frozen centroids. It never re-standardises or refits on the new person.
3. `cluster_label` is populated only when the frozen protocol status is
   `assigned`. For an OOD or uncertain person, the nearest class is reported
   as `provisional_cluster_label` and the status must be reviewed rather than
   treated as a definitive C1/C2/C3 subtype.
4. Outcome `probability` comes from the selected EasyEnsemble classifier. The
   binary label is `high_risk` when probability is greater than or equal to
   the stored full-CKB Youden threshold; otherwise it is `low_risk`.
5. The outcome force plot explains the fitted regression surrogate for the
   selected classifier probability. `shap_surrogate_score` is reported beside
   the classifier probability so the two quantities are not conflated. The
   cluster force plots similarly explain the multiclass RF surrogate, not the
   Euclidean nearest-centroid distance.

This package is a model-inference tool, not a clinical diagnosis or a
replacement for external validation, calibration assessment, or clinical
judgement.
