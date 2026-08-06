"""
preprocess.py

Parses the NLM Chest X-ray (NLMCXR_reports) XML dataset and extracts
FINDINGS / IMPRESSION pairs into a clean CSV file ready for training.

Source dataset: https://openi.nlm.nih.gov

Usage:
    python src/preprocess.py

Expects:
    data/NLMCXR_reports/  (folder containing the unzipped .xml report files)

Produces:
    data/processed_reports.csv  (columns: findings, impression)
"""

import os
import glob
import pandas as pd
from bs4 import BeautifulSoup

RAW_DATA_DIR = os.path.join("data", "NLMCXR_reports", "ecgen-radiology")
OUTPUT_PATH = os.path.join("data", "processed_reports.csv")


def extract_section(soup, label):
    """Extract text from an AbstractText tag with the given Label attribute."""
    tag = soup.find("AbstractText", attrs={"Label": label})
    if tag and tag.text and tag.text.strip():
        return tag.text.strip()
    return None


def parse_report(xml_path):
    """Parse a single XML report file and return (findings, impression) or None."""
    with open(xml_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "lxml-xml")

    findings = extract_section(soup, "FINDINGS")
    impression = extract_section(soup, "IMPRESSION")

    if findings is None or impression is None:
        return None

    return {"findings": findings, "impression": impression}


def run_preprocessing(raw_data_dir=RAW_DATA_DIR, output_path=OUTPUT_PATH):
    xml_files = glob.glob(os.path.join(raw_data_dir, "*.xml"))
    print(f"Found {len(xml_files)} XML files in {raw_data_dir}")

    if len(xml_files) == 0:
        raise FileNotFoundError(
            f"No XML files found in {raw_data_dir}. "
            "Make sure NLMCXR_reports has been unzipped into this folder."
        )

    records = []
    dropped = 0

    for xml_path in xml_files:
        result = parse_report(xml_path)
        if result is None:
            dropped += 1
            continue
        records.append(result)

    print(f"Parsed {len(records)} valid reports (dropped {dropped} incomplete records)")

    df = pd.DataFrame(records)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Saved processed dataset to {output_path}")

    return df


if __name__ == "__main__":
    run_preprocessing()
