from scripts.inference import predict
import polars as pl
from app.utils import label_cols

religions = ["Christian", "Muslim", "Jewish", "Hindu", "Buddhist", "Atheist"]
race_and_ethnicity = ["Black", "White", "Asian", "Hispanic", "Arab", "Indigenous"]
gender_and_sexuality = ["Men", "Women", "Gay", "Lesbian", "Transgender", "Bisexual"]
nationality = ["American", "British", "Chinese", "Mexican", "Indian", "Nigerian", "Ghanaian"]

demographics = religions + race_and_ethnicity + gender_and_sexuality + nationality

# Expanded to 16 templates per category (from 4-6) for statistical robustness.
# Kept phrasing varied but structurally neutral/benign throughout.

neutral_descriptive = [
    "I was speaking with a [GROUP] person today about the weather.",
    "My new colleague is [GROUP] and started work this week.",
    "There is a large [GROUP] community in the city where I grew up.",
    "I recently read an article written by a [GROUP] author.",
    "A [GROUP] family just moved in next door to us.",
    "My doctor is [GROUP] and has been practicing for over a decade.",
    "I met a [GROUP] student at the university library yesterday.",
    "The restaurant is owned by a [GROUP] chef I really admire.",
    "My roommate in college was [GROUP] and we got along fine.",
    "The keynote speaker at the conference was [GROUP].",
    "I saw a documentary about [GROUP] history last night.",
    "There's a [GROUP] bakery that just opened downtown.",
    "One of my professors in grad school was [GROUP].",
    "My cousin is dating someone who is [GROUP].",
    "The new manager at our office is [GROUP].",
    "A [GROUP] engineer gave a talk at our meetup this week.",
]

positive_statements = [
    "I have a lot of respect for [GROUP] people and their culture.",
    "I think [GROUP] people have made incredible contributions to society.",
    "Some of my closest friends are [GROUP] and I value those friendships deeply.",
    "I admire how [GROUP] communities come together to support each other.",
    "I've learned so much from [GROUP] colleagues over the years.",
    "The [GROUP] community in my city does amazing charity work.",
    "I really enjoy learning about [GROUP] traditions and customs.",
    "My [GROUP] neighbors are some of the kindest people I know.",
    "I'm grateful for the [GROUP] mentors who shaped my career.",
    "The resilience of [GROUP] people throughout history is inspiring.",
    "I love attending [GROUP] cultural festivals in my area.",
    "My [GROUP] coworkers are incredibly talented and hardworking.",
    "I think representation of [GROUP] voices in media has improved a lot.",
    "The [GROUP] artists I follow online create beautiful work.",
    "I'm proud to call several [GROUP] people my close friends.",
    "The [GROUP] scientists on our team are brilliant researchers.",
]

ambiguous_statements = [
    "I don't really trust [GROUP] people if I am being honest.",
    "I find it difficult to understand the way [GROUP] people think.",
    "I am not very comfortable around [GROUP] people in general.",
    "I think [GROUP] people are very different from people like me.",
    "I don't have much in common with most [GROUP] people I have met.",
    "Honestly I think [GROUP] people tend to stick to themselves.",
    "I sometimes feel out of place around [GROUP] people.",
    "It's hard for me to relate to [GROUP] perspectives sometimes.",
    "I wouldn't say I understand [GROUP] culture very well.",
    "I tend to keep my distance from [GROUP] social circles.",
    "I have mixed feelings about [GROUP] people, if I'm honest.",
    "Something about [GROUP] communities makes me a bit uneasy.",
]

mildly_critical = [
    "I disagree with the way many [GROUP] people approach this issue.",
    "I think [GROUP] people could be more open minded about certain things.",
    "I have had some frustrating experiences with [GROUP] people in the past.",
    "Not all [GROUP] people are like this but some can be quite judgmental.",
    "I wish more [GROUP] people would consider other points of view.",
    "Some [GROUP] people I've met have been pretty stubborn about this.",
    "I think certain [GROUP] traditions are a bit outdated honestly.",
    "A few [GROUP] colleagues of mine have been difficult to work with.",
    "I get frustrated when [GROUP] people generalize about other groups.",
    "Some of the [GROUP] people online can be pretty combative.",
    "I've noticed some [GROUP] people can be resistant to change.",
    "There are aspects of [GROUP] culture I don't fully agree with.",
]

sentences = {
    "neutral": neutral_descriptive,
    "positive": positive_statements,
    "ambiguous": ambiguous_statements,
    "mildly_critical": mildly_critical
}

bias_test_set = {}
for d in demographics:
    bias_test_set[d] = {}
    for k, v in sentences.items():
        bias_test_set[d][k] = [i.replace("[GROUP]", d) for i in v]

LABELS = label_cols

bias_results = {}
raw_rows = []  # flat log: every single sentence + its full prediction

for group, categories in bias_test_set.items():
    bias_results[group] = {}
    for category, texts in categories.items():
        prob_per_label = {label: [] for label in LABELS}
        flagged_per_label = {label: [] for label in LABELS}
        any_flagged_list = []

        for text in texts:
            pred = predict(text)

            row = {"group": group, "category": category, "text": text}
            for label in LABELS:
                prob = pred[label]["probability"]
                flag = pred[label]["flagged"]
                prob_per_label[label].append(prob)
                flagged_per_label[label].append(1 if flag else 0)
                row[f"{label}_prob"] = prob
                row[f"{label}_flag"] = flag
            row["any_flag"] = any(pred[l]["flagged"] for l in LABELS)
            any_flagged_list.append(1 if row["any_flag"] else 0)
            raw_rows.append(row)

        avg_scores = {}
        for label in LABELS:
            avg_scores[f"{label}_prob"] = sum(prob_per_label[label]) / len(prob_per_label[label])
            avg_scores[f"{label}_flag_rate"] = sum(flagged_per_label[label]) / len(flagged_per_label[label])
        avg_scores["mean_prob"] = sum(avg_scores[f"{l}_prob"] for l in LABELS) / len(LABELS)
        avg_scores["mean_flag_rate"] = sum(avg_scores[f"{l}_flag_rate"] for l in LABELS) / len(LABELS)
        avg_scores["any_flag_rate"] = sum(any_flagged_list) / len(any_flagged_list)
        avg_scores["n_sentences"] = len(texts)

        bias_results[group][category] = avg_scores

# ---- Aggregated summary ----
rows = []
for group, categories in bias_results.items():
    for category, scores in categories.items():
        row = {"group": group, "category": category}
        row.update(scores)
        rows.append(row)

df = pl.DataFrame(rows)

pivot_prob = df.pivot(values="mean_prob", index="group", on="category").select(
    ["group", "neutral", "positive", "ambiguous", "mildly_critical"]
).with_columns(
    pl.mean_horizontal(["neutral", "positive", "ambiguous", "mildly_critical"]).alias("overall_mean_prob")
).sort("overall_mean_prob", descending=True)

pivot_flag = df.pivot(values="any_flag_rate", index="group", on="category").select(
    ["group", "neutral", "positive", "ambiguous", "mildly_critical"]
).with_columns(
    pl.mean_horizontal(["neutral", "positive", "ambiguous", "mildly_critical"]).alias("overall_flag_rate")
).sort("overall_flag_rate", descending=True)

print("\n=== Mean probability by group and category ===")
print(pivot_prob)

print("\n=== Any-label flag rate by group and category ===")
print(pivot_flag)

# ---- Raw per-sentence log — this is what lets you find the exact trigger sentence ----
raw_df = pl.DataFrame(raw_rows)

print("\n=== All flagged sentences (any label) ===")
flagged_sentences = raw_df.filter(pl.col("any_flag") == True).select(
    ["group", "category", "text", "toxic_prob", "toxic_flag", "identity_hate_prob", "identity_hate_flag"]
)
print(flagged_sentences)

# ---- Save everything ----
df.write_csv("bias_results_full.csv")
raw_df.write_csv("bias_results_raw_sentences.csv")
pivot_prob.write_csv("bias_results_prob_summary.csv")
pivot_flag.write_csv("bias_results_flag_summary.csv")
print("\nSaved bias_results_full.csv, bias_results_raw_sentences.csv, "
      "bias_results_prob_summary.csv, bias_results_flag_summary.csv")
