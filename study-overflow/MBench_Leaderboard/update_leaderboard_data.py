import pandas as pd
import numpy as np

# Data from LaTeX
data = [
    # text-conditioned
    ["Memflow", 61.72, 56.06, 39.48, 51.60, 57.95, 20.89, 55.06, 30.08, 62.75, 72.04, 46.31, np.nan],
    ["Self Forcing", 34.97, 33.02, 43.92, 54.58, 67.44, 55.19, 66.83, 30.15, 50.19, 66.84, 43.91, np.nan],
    ["Skyreels V2", 70.03, 53.70, 24.57, 53.76, 49.01, 56.39, 46.44, 20.33, 68.35, 79.52, 44.68, np.nan],
    ["Longlive", 63.57, 55.41, 42.51, 55.89, 46.68, 27.51, 59.44, 25.26, 70.32, 74.69, 46.97, np.nan],
    ["Longcat-Video", 46.96, 43.13, 26.56, 52.98, 28.28, 9.26, 56.10, 27.46, 84.17, 87.83, 46.25, np.nan],
    ["Cosmos-Predict 2.5", 51.90, 47.31, 16.95, 45.42, 9.73, 14.68, 55.95, 22.66, 83.67, 80.81, 45.08, np.nan],
    ["Causal Forcing", 62.23, 53.36, 42.53, 64.37, 18.10, 2.88, 57.44, 27.48, 64.79, 73.10, 44.90, np.nan],
    ["Helios", 79.43, 63.70, 31.33, 41.64, 24.79, 32.46, 41.79, 25.26, 58.27, 75.08, 43.17, np.nan],
    # action-conditioned
    ["Matrix-Game 2.0", 14.62, 28.99, 1.22, 0.94, 14.78, 3.08, 38.79, 73.78, 10.00, 26.40, np.nan, 47.86],
    ["Matrix-Game 3.0", 44.15, 58.22, 42.38, 47.91, 61.99, 32.86, 62.06, 95.17, 37.50, 48.80, np.nan, 81.93],
    ["HY-WorldPlay", 47.12, 68.54, 52.46, 66.58, 83.86, 68.17, 82.67, 98.23, 49.50, 62.40, np.nan, 85.69],
    ["Yume-1.5", 60.96, 49.99, 17.41, 40.57, 51.86, 24.55, 51.21, 92.05, 97.90, 95.00, np.nan, 62.20],
    ["Lingbot-World", 33.20, 44.54, 11.57, 33.53, 22.12, 7.57, 40.06, 85.87, 96.00, 89.40, np.nan, 63.32],
    ["Infinite-World", 35.70, 61.88, 23.08, 46.85, 74.04, 61.51, 62.63, 96.87, 48.00, 78.40, np.nan, 86.37],
]

columns = [
    "Model Name", "Object Geometry", "Object Texture", "Human Identity", "Human Appearance",
    "Epipolar Geometry", "Reprojection Consistency", "Lighting Consistency", "Style Consistency",
    "State Progress", "Physical Plausibility", "Text Interaction", "Action Interaction"
]

df = pd.DataFrame(data, columns=columns)

# Derive scores (unweighted averages ignoring nans)
df["Entity Score"] = df[["Object Geometry", "Object Texture", "Human Identity", "Human Appearance"]].mean(axis=1)
df["Environment Score"] = df[["Epipolar Geometry", "Reprojection Consistency", "Lighting Consistency", "Style Consistency"]].mean(axis=1)
df["Causal Score"] = df[["State Progress", "Physical Plausibility", "Text Interaction", "Action Interaction"]].mean(axis=1)

df["Total M-Score"] = df[["Entity Score", "Environment Score", "Causal Score"]].mean(axis=1)

# Format to 2 decimal places
for col in ["Entity Score", "Environment Score", "Causal Score", "Total M-Score"]:
    df[col] = df[col].round(2)

# Sort by Total M-Score descending
df = df.sort_values(by="Total M-Score", ascending=False).reset_index(drop=True)
df["Rank"] = df.index + 1

# Add constants
df["Model Link"] = ""
# If Model Name contains certain words, type is action-conditioned
action_models = ["Matrix", "HY-WorldPlay", "Yume", "Lingbot", "Infinite"]
df["Model Type"] = df["Model Name"].apply(lambda x: "action-conditioned" if any(a in x for a in action_models) else "text-conditioned")
df["Certification"] = "MBench Paper"
df["Accessibility"] = "TBD"
df["Sampled by"] = "MBench Team"
df["Evaluated by"] = "MBench Team"
df["Date"] = "2026-05-28"

# Optional triggers? It seems trigger coverage and memory reliability were 0 in the seed file (except for action ones).
# Wait, let's look at the original seed CSV. It has: Trigger Coverage	Memory Reliability (all 0)
df["Trigger Coverage"] = 0
df["Memory Reliability"] = 0

df = df.fillna(0) # For interactions that are nan, we can put 0, or just leave as empty string or "NaN". 
# The original CSV has "0" instead of NaN for the unused interaction type.
# Wait, let's keep all 0s? Let's check original CSV for Self Forcing: Action Interaction is 0.

# Reorder columns
final_cols = [
    "Rank", "Model Name", "Model Link", "Model Type", "Certification", "Accessibility", 
    "Sampled by", "Evaluated by", "Date", "Total M-Score", "Entity Score", "Environment Score", 
    "Causal Score", "Object Geometry", "Object Texture", "Human Identity", "Human Appearance", 
    "Epipolar Geometry", "Reprojection Consistency", "Lighting Consistency", "Style Consistency", 
    "State Progress", "Physical Plausibility", "Text Interaction", "Action Interaction", 
    "Trigger Coverage", "Memory Reliability"
]
df = df[final_cols]
df.to_csv("MBench_Leaderboard/seed/results.csv", index=False)
