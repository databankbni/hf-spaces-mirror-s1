import { getDb } from "@/lib/db";
import { all } from "@/lib/db/helpers";
import type { Dataset, UploadRequirement, SubmissionFileType } from "@/lib/db/schema";
import { contentValue, hasLocalizedText, localized } from "@/lib/i18n";

export function getDatasetsWithVersions(): {
  datasets: Dataset[];
  uploadRequirements: UploadRequirement[];
  fileTypes: SubmissionFileType[];
} {
  const db = getDb();
  const uploadRequirements = all<UploadRequirement>(
    db.prepare("SELECT * FROM upload_requirements ORDER BY sort_order, id")
  )
    .map((row) => ({
      ...row,
      titleText: localized(row.title_en || row.title, row.title_zh),
      bodyText: localized(row.body_en || row.body, row.body_zh),
    }))
    .filter((row) => hasLocalizedText(row.titleText) || hasLocalizedText(row.bodyText));
  const fileTypes = all<SubmissionFileType>(
    db.prepare("SELECT * FROM submission_file_types ORDER BY id")
  )
    .map((row) => ({
      ...row,
      accepted_extensions: contentValue(row.accepted_extensions),
      labelText: localized(row.label_en || row.label, row.label_zh),
      descriptionText: localized(row.description_en || row.description || "", row.description_zh),
    }))
    .filter(
      (row) =>
        hasLocalizedText(row.labelText) ||
        hasLocalizedText(row.descriptionText) ||
        Boolean(row.accepted_extensions)
    );
  return {
    datasets: all<Dataset>(db.prepare(
      `SELECT d.*, v.version_label, v.release_date, v.download_url, v.checksum, v.notes AS version_notes
       FROM datasets d LEFT JOIN dataset_versions v ON v.dataset_id = d.id AND v.is_latest = 1 ORDER BY d.id`
    )),
    uploadRequirements,
    fileTypes,
  };
}

export function getDatasets(): Dataset[] {
  return all<Dataset>(getDb().prepare(
    `SELECT d.*, v.version_label, v.release_date, v.download_url, v.checksum, v.notes AS version_notes
     FROM datasets d LEFT JOIN dataset_versions v ON v.dataset_id = d.id AND v.is_latest = 1 ORDER BY d.id`
  ));
}
