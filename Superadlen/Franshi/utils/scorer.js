// utils/scorer.js
const { getUploader } = require('./parser');

function getReleaseScore(title) {
    if (!title) return 0;
    const t = title.toLowerCase();
    let score = 0;

    if (t.includes("remux")) score += 150;
    else if (t.includes("bluray")) score += 120;
    else if (t.includes("web-dl") || t.includes("webdl")) score += 90;
    else if (t.includes("webrip")) score += 70;

    if (t.includes("dolby vision") || t.includes(" dv ")) score += 35;
    if (t.includes("hdr10+")) score += 30;
    else if (t.includes("hdr")) score += 25;

    if (t.includes("atmos")) score += 25;
    if (t.includes("truehd")) score += 20;
    if (t.includes("dts-hd")) score += 20;

    return score;
}

function getConfidenceScore(title, seeds) {
    let confidence = 40; // Score de base équilibré

    // Bonus de santé (Seeders)
    if (seeds > 100) confidence += 30;
    else if (seeds > 30) confidence += 20;
    else if (seeds > 5) confidence += 10;
    else if (seeds === 0) confidence -= 30; // Pénalité torrent mort

    // Bonus d'Uploader certifié
    if (getUploader(title)) confidence += 20;

    // Bonus de codec moderne efficient (HEVC / AV1)
    if (/\b(hevc|x265|av1)\b/i.test(title.toLowerCase())) confidence += 10;

    // Encapsulation stricte entre 0 et 100%
    return Math.min(Math.max(confidence, 0), 100);
}

module.exports = { getReleaseScore, getConfidenceScore };