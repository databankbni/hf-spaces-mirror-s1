import polars as pl
from iterstrat.ml_stratifiers import MultilabelStratifiedShuffleSplit
from langchain_text_splitters import RecursiveCharacterTextSplitter
import numpy as np
from datasets import Dataset
from scripts.eda import training_set, class_cols

WORD_LIMIT=512
CHAR_LIMIT = WORD_LIMIT * 6
CHUNK_OVERLAP = 0
splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHAR_LIMIT,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
)
#trying this kind of coding haha
def word_count(text: str) -> int:
    return len(text.split())

def split_row(row: dict) -> list[dict]:
    chunks = splitter.split_text(row["comment_text"])
    result = []
    for n, chunk in enumerate(chunks):
        new_row = row.copy()
        new_row["comment_text"] = chunk
        new_row["id"] = f"{row["id"]}__chunk{n}"
        result.append(new_row)
    return result

def process_df(df:pl.DataFrame) -> pl.DataFrame:
    kept_rows: list[dict] = []
    expanded_rows: list[dict] = []

    for row in df.iter_rows(named=True):
        if word_count(row["comment_text"]) > WORD_LIMIT:
            expanded_rows.extend(split_row(row))
        else:
            kept_rows.append(row)
    all_rows = kept_rows + expanded_rows

    return pl.DataFrame(all_rows, schema=df.schema)
bert_training_set = process_df(training_set)
y = bert_training_set.select(class_cols).to_numpy()
X_dummy = np.zeros((bert_training_set.height, 1))

msss = MultilabelStratifiedShuffleSplit(
    n_splits=1, test_size=0.1, random_state=42
)

train_idx, val_idx = next(msss.split(X_dummy, y))
train_set = bert_training_set[train_idx]
val_set = bert_training_set[val_idx]
print(train_set.height)

train_ds = Dataset.from_polars(train_set)
val_ds = Dataset.from_polars(val_set)
