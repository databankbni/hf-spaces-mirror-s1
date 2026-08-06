import polars as pl
import matplotlib.pyplot as plt
training_set_path = "dataset/train.csv"
training_set = pl.read_csv(training_set_path)
total = training_set.height
print(training_set.columns)
#all column names except the id and comments
class_cols = training_set.columns[2:]
class_cols_counts = {}
for c in class_cols:
    df_count = training_set.filter(pl.col(c) == 1).height
    class_cols_counts[c] = df_count

not_toxic = training_set.filter(pl.all_horizontal(pl.col(c) == 0 for c in class_cols)).height
#class_cols_counts["not_toxic"] = not_toxic
clc_percentages = {k:(class_cols_counts[k]*100)/total for k in class_cols_counts.keys()}
#clc_ratios = {k:(class_cols_counts["not_toxic"]/class_cols_counts[k]) for k in class_cols_counts.keys()}
pos_weight = {k:(total - class_cols_counts[k])/class_cols_counts[k] for k in class_cols_counts.keys()}
pos_weight_vals = list(pos_weight.values())
v = class_cols_counts.values()
k = class_cols_counts.keys()

comment_average_length = training_set.select(pl.col("comment_text").str.split(" ").list.len().mean()).item()
max_comment_length = training_set.select(pl.col("comment_text").str.split(" ").list.len().max()).item()
excess = training_set.filter(pl.col("comment_text").str.split(" ").list.len() > 512).height
#print(comment_average_length)
#print(max_comment_length)
#print(excess)

#will do a hard truncation for now. But will return later, to do more preprocessing to preserve all the data (possibly chunking or a sliding window)
'''
plt.bar(k, v)
plt.xlabel("Toxicity Classes")
plt.xticks(rotation=45)
plt.ylabel("Frequency")
plt.tight_layout()
plt.show()
'''
