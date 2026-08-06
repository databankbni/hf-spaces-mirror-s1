import pandas as pd

f = r"data\race_day\attempt_01\attempt1_cleaned.csv"
df = pd.read_csv(f)
start = df["timeS"].iloc[0]
df["timeS"] = df["timeS"] - start
df.to_csv(f, index=False)
print(f"Done. Offset -{start}s. timeS now: {df['timeS'].iloc[0]} to {df['timeS'].iloc[-1]}")
