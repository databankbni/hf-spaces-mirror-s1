// utils/parser.js

function getFileSize(title) {
    if (!title) return null;
    const t = title.replace(/,/g, '.');
    const match = t.match(/\b(\d+(?:\.\d+)?)\s*(TB|GB|MB|KB|TIB|GIB|MIB|KIB)\b/i);
    if (!match) return null;
    
    let size = parseFloat(match[1]);
    let unit = match[2].toUpperCase().replace('TIB', 'TB').replace('GIB', 'GB').replace('MIB', 'MB').replace('KIB', 'KB');
    
    // Calcul de la valeur brute en MB pour les filtres stricts
    let sizeInMB = size;
    if (unit === 'TB') sizeInMB = size * 1024 * 1024;
    if (unit === 'GB') sizeInMB = size * 1024;
    if (unit === 'KB') sizeInMB = size / 1024;

    return { formatted: `${size} ${unit}`, mb: sizeInMB };
}

function getSeeders(title) {
    if (!title) return 0;
    const t = String(title).toLowerCase().replace(/\n/g, ' ');
    if (t.includes('unknown')) return 0;

    const match = t.match(/(?:👤|👥|seeders?|seeds?|\bs\b)\s*[:=]?\s*(\d+)/i);
    if (match && match[1]) return Number(match[1]) || 0;

    const fallbackMatch = t.match(/(\d+)\s*(?:seed|peer)/i);
    if (fallbackMatch && fallbackMatch[1]) return Number(fallbackMatch[1]) || 0;

    return 0; 
}

function isFake(title = '') {
    if (!title) return false;
    const t = title.toLowerCase();
    const globalBlacklist = [
        'sample', 'trailer', 'camrip', 'hdcam', 'hd-ts', 'hdts', 'telecine', 'telesync',
        'workprint', 'xbet', '1xbet', 'betwinner', 'promo', 'preview', 'clip', 'fake',
        'password', 'readme', 'proof', 'recode', 'dvdscr', 'screener'
    ];
    if (globalBlacklist.some(word => t.includes(word))) return true;

    const strictRegex = /\b(cam|ts|tc|wp|line|line\s*audio|ads|test|demo|screen)\b/i;
    return strictRegex.test(t);
}

function getCodec(title) {
    if (!title) return "x264";
    const t = title.toLowerCase();
    if (/\b(av1)\b/i.test(t)) return "AV1";
    if (/\b(hevc|x265|h265|h\.265)\b/i.test(t)) return "HEVC";
    if (/\b(avc|x264|h264|h\.264)\b/i.test(t)) return "AVC/x264";
    return "x264";
}

function getAudioCodec(title) {
    if (!title) return "🎧 AAC";
    const t = title.toLowerCase();
    if (/\b(atmos|dolby\s*atmos)\b/i.test(t)) return "🎧 Atmos";
    if (/\b(dts\s*x|dts-x)\b/i.test(t)) return "🎧 DTS:X";
    if (/\b(truehd|true-hd)\b/i.test(t)) return "🎧 TrueHD";
    if (/\b(dts-hd|dtshd|dts\s*hd\s*ma)\b/i.test(t)) return "🎧 DTS-HD MA";
    if (/\b(ddp|dd\+|eac3|dolby\s*digital\s*plus)\b/i.test(t)) return "🎧 DD+";
    if (/\b(dts)\b/i.test(t)) return "🎧 DTS";
    if (/\b(flac)\b/i.test(t)) return "🎧 FLAC";
    if (/\b(aac)\b/i.test(t)) return "🎧 AAC";
    return "🎧 AAC";
}

function getUploader(title) {
    if (!title) return "";
    const t = title.toLowerCase();
    const uploaders = {
        framestor: "⭐ Framestor", epsilon: "⭐ EPSILON", tigole: "⭐ Tigole",
        qxr: "⭐ QxR", psa: "⭐ PSA", joy: "⭐ JOY", ntb: "⭐ NTb", flux: "⭐ FLUX"
    };
    for (const key in uploaders) {
        if (t.includes(key)) return uploaders[key];
    }
    return "";
}

function getQualityInfo(title) {
    const t = (title || '').toLowerCase();
    let quality = t.includes('2160p') || t.includes('4k') ? '4K' : 
                  t.includes('1080p') ? '1080P' : 
                  t.includes('720p') ? '720P' : 'HD';

    let source = t.includes('remux') ? 'REMUX' :
                 t.includes('bluray') || t.includes('bdrip') ? 'BluRay' :
                 t.includes('web-dl') || t.includes('webdl') ? 'WEB-DL' :
                 t.includes('webrip') ? 'WEBRip' : 'P2P';

    let lang = 'Unknown';
    const languages = {
        fr: { flag: '⭐🇫🇷', names: ['french', ' vf ', ' vff ', 'francais'] },
        en: { flag: '🇺🇸', names: ['english', ' en ', ' eng '] },
        ar: { flag: '🇩🇿', names: ['arabic', ' ar ', ' arabe'] }
    };
    const found = Object.entries(languages)
        .filter(([_, data]) => data.names.some(name => t.includes(name)))
        .map(([code]) => code);

    if (t.includes('multi')) lang = '💬🎧: ⭐🌍 MULTI';
    else if (found.length === 1) lang = `💬🎧: ${languages[found[0]].flag} ${found[0].toUpperCase()}`;
    else lang = '💬🎧: 🌍 VOSTFR/Unknown';

    return { quality, source, lang };
}

module.exports = { getFileSize, getSeeders, isFake, getCodec, getAudioCodec, getUploader, getQualityInfo };