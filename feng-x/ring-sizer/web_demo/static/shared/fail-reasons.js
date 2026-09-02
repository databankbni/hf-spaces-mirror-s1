// Friendly status messages for /api/measure failures.
//
// Currently consumed by the mobile result step. The desktop
// `static/app.js` keeps an inline duplicate of this map until the
// Phase 4 desktop refactor migrates it to import from here. Until
// then, edits to copy must land in BOTH places — that's tracked in
// doc/v6/Progress.md.

export const FAIL_REASON_MESSAGES = {
  card_not_detected:
    "Card not detected. A card of standard credit card dimensions (85.6 × 54 mm) is required as a scale reference to measure your finger diameter. Place the card beside your hand on a plain white background (e.g. a sheet of paper), and turn on your phone's flash.",
  card_not_parallel:
    "Card scale calibration failed. Keep your phone parallel to the card. Use a card of standard credit card dimensions (85.6 × 54 mm) as the reference.",
  card_near_edge:
    "Card appears cropped. Place the entire card within the photo frame.",
  card_too_small:
    "Card looks too small in the photo. Move your phone closer to the table so the card takes up a larger portion of the frame, then retake.",
  hand_not_detected:
    "Hand not detected. Place your hand flat on a plain white background (e.g. a sheet of paper), and spread your fingers naturally.",
  finger_isolation_failed:
    "Could not isolate the selected finger. Keep one target finger extended and separated.",
  finger_not_fully_visible:
    "Finger is partially out of frame. Move hand to center of photo.",
  finger_mask_too_small:
    "Finger region is too small. Move closer and use a higher-resolution photo.",
  fingers_too_close:
    "Fingers are too close together. Spread your fingers apart naturally.",
  contour_extraction_failed:
    "Finger contour extraction failed. Improve lighting and reduce background clutter.",
  axis_estimation_failed:
    "Finger axis estimation failed. Keep the finger straight and fully visible.",
  zone_localization_failed:
    "Ring zone localization failed. Keep more of the finger base visible.",
  width_measurement_failed:
    "Diameter measurement failed. Retake with phone parallel to the table and steady focus.",
  sobel_edge_refinement_failed:
    "Edge refinement failed. Turn on flash or use stronger, even lighting.",
  width_unreasonable:
    "Measured diameter is out of range. Retake with the phone parallel to the table.",
  disagreement_with_contour:
    "Edge methods disagree too much. Retake with cleaner edges and more even lighting.",
  all_fingers_failed:
    "Could not measure any fingers. Ensure hand is flat with fingers spread and well-lit.",
  image_too_blurry:
    "Photo is blurry. Hold your phone steady or use a tripod.",
  image_underexposed:
    "Photo is too dark. Turn on flash or improve lighting.",
  image_overexposed:
    "Photo is too bright. Avoid direct sunlight or strong overhead light.",
  image_low_contrast:
    "Photo has low contrast. Use a different background color.",
  image_resolution_too_low:
    "Photo resolution is too low. Use the rear camera at full resolution.",
  image_quality_low_lighting:
    "Lighting is uneven. Turn on flash and shoot from directly above.",
};

export function formatFailReason(failReason) {
  if (!failReason) {
    return "Measurement failed.";
  }
  if (failReason.startsWith("quality_score_low_")) {
    return "Low edge quality detected. Turn on flash and retake.";
  }
  if (failReason.startsWith("consistency_low_")) {
    return "Edge detection was inconsistent. Keep phone parallel to table and retry.";
  }
  return (
    FAIL_REASON_MESSAGES[failReason] ||
    "Measurement failed. Please retake the photo and try again."
  );
}
