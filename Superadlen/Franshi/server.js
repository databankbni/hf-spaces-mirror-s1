const express = require('express');
const axios = require('axios');
const cors = require('cors');
const NodeCache = require('node-cache');

const app = express();
app.use(cors());

const cache = new NodeCache({ stdTTL: 10, checkperiod: 10 });
const TIMEOUT = 5150;

const MANIFEST = {
    id: 'org.golink.payload',
    version: '2.2.7',
    name: '🔻GHOST🔻',
    description: 'Multi-Sources Rapide - Films & Series By Superadlen DZ',
    resources: ['stream'],
    types: ['movie', 'series'],
    idPrefixes: ['tt', 'tmdb:', 'kitsu'],
    catalogs: [],
    logo: 'https://i.pinimg.com/736x/bf/77/e2/bf77e2c4b9cff50ef427ca9d4e9dfe77.jpg'
};

const SOURCES = [
    { url: 'https://addon.peerflix.mov/language=en|qualityfilter=sd,480p,540p,hdtv,screener,vhs,unknown|sort=seed-desc,quality-desc,size-desc', name: 'DZ1' },
    { url: 'https://filmora2.vercel.app', name: 'DZ2' },
    { url: 'https://str.zmb.lat/lite', name: 'DZ3' },
    { url: 'https://zamunda-stremio.tzkppv.com/debrid=none|content=all|quality=4k,1080p,720p|lang=en', name: 'DZ4' },
    { url: 'https://hdhub.thevolecitor.qzz.io/eyJ0b3Jib3giOiJ1bnNldCIsInF1YWxpdGllcyI6IjIxNjBwLDEwODBwLDcyMHAiLCJzb3J0IjoiZGVzYyJ9', name: 'DZ5' },
    { url: 'https://watcho3.rafaelzioneverest.workers.dev', name: 'DZ6' },
    { url: 'https://vela-flow.vercel.app', name: 'DZ7' },
    { url: 'https://showbox.codiv.dpdns.org/%7B%22cookie%22%253A%22eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE3ODUzMTQ1NDUsIm5iZiI6MTc4NTMxNDU0NSwiZXhwIjoxODE2NDE4NTY1LCJkYXDataI6eyJ1aWQiOjIyMzQ0MTgsInRva2VuIjoiNTIzYTRhMTE1MTY4ODZjNGMyZGQ4Nzk1NWVlM2U4ODIiLCJhbGciOiJIUzI1NiJ9.8YXH3OC9NPAYVi7Dkk3kJzSixgfsWmVl7Gd9qWG4IGk%22%7D', name: 'HTTP.DZ1⭐' },
    { url: 'https://pengu.uk/%7B%22auth_token%22%3A%22re3Z2wByO95MYjcFmBzKY_8fPxql6xtpdHRNCrFBomA%22%7D', name: 'HTTP.DZ2⭐' },
    { url: 'https://magneto-jnv5.onrender.com/v1', name: 'DZ8' },
    { url: 'https://yastream.tamthai.de/eyJjYXRhbG9ncyI6WyJraXNza2gubW92aWUuVVMiLCJraXNza2guc2VyaWVzLlVTIiwib25ldG91Y2h0di5zZXJpZXMuUG9wdWxhciIsImtpc3NraC5zZXJpZXMuU2VhcmNoIiwia2lzc2toLm1vdmllLlNlYXJjaCIsIm9uZXRvdWNodHYuc2VyaWVzLlNlYXJjaCIsImlkcmFtYS5zZXJpZXMuaURyYW1hIiwiaWRyYW1hLnNlcmllcy5TZWFyY2giXSwiY2F0YWxvZyI6WyJraXNza2giLCJvbmV0b3VjaHR2Il0sInN0cmVhbSI6WyJraXNza2giLCJvbmV0b3VjaHR2Il0sIm5zZnciOmZhbHNlLCJpbmZvIjp0cnVlLCJwb3N0ZXIiOiJycGRiIiwibWZwVXJsIjoiIiwidGJLZXkiOiIiLCJtZnBQYXNzIjoiIn0=', name: 'HTTP.DZ3⭐' },
    { url: 'https://hdhub.thevolecitor.qzz.io/eyJ0b3Jib3giOiJ1bnNldCIsInF1YWxpdGllcyI6IjIxNjBwLDEwODBwLDcyMHAiLCJzb3J0IjoiZGVzYyIsImNvbnRlbnQiOiJmcmVuY2giLCJjYXRhbG9ncyI6IiJ9', name: 'HTTP.DZ4⭐' }
];

/* ================= PROVIDER / PEER DETECTOR ================= */
function getPeerSite(title) {
    const t = (title || '').toLowerCase();
    if (t.includes('yts') || t.includes('yify') || t.includes('yifi')) return 'YTS';
    if (t.includes('vegamovies')) return 'VegaMovies⚡';
    if (t.includes('moviebox')) return 'MovieBox⚡';
    if (t.includes('hdghartv')) return 'HDGharTv';
    if (t.includes('hdhub')) return 'HD-Hub🌐';
    if (t.includes('vidlink')) return 'VidLink';
    if (t.includes('vidking')) return 'VidKing⚡';
    if (t.includes('vaplayer')) return 'VaPlayer';
    if (t.includes('2peckle')) return '2Peckle';
    if (t.includes('4khdhub')) return '4K-HuB';
    if (t.includes('cinefreak')) return 'CineCloud';
    if (t.includes('yastream')) return 'Yastream✨';
    if (t.includes('cinejoy')) return 'CineJoy';
    if (t.includes('moviesdrives')) return 'MoviesDrives';
    if (t.includes('thepiratebay') || t.includes('tpb')) return 'TPB';
    if (t.includes('1337x')) return '1337X';
    if (t.includes('rutor')) return 'RUTOR';
    if (t.includes('rarbg')) return 'RARBG';
    if (t.includes('torrentgalaxy') || t.includes('tgx')) return 'TGX';
    if (t.includes('eztv')) return 'EZTV';
    if (t.includes('nyaa')) return 'NYAA';
    if (t.includes('torrentleech')) return 'TL';
    if (t.includes('kickass') || t.includes('kat')) return 'KAT';
    if (t.includes('zooqle')) return 'ZOOQLE';
    if (t.includes('limetorrents')) return 'LIME';
    if (t.includes('torlock')) return 'TORLOCK';
    if (t.includes('torrentdownloads')) return 'TD';
    if (t.includes('magnetdl')) return 'MAGNETDL';
    if (t.includes('idope')) return 'IDOPE';
    if (t.includes('rutracker')) return 'RUTRACKER';
    if (t.includes('solidtorrents')) return 'SOLID';
    if (t.includes('bitsearch')) return 'BITSEARCH';
    if (t.includes('torrentfunk')) return 'TFUNK';
    if (t.includes('glodls')) return 'GLODLS';
    if (t.includes('ettv')) return 'ETTV';
    if (t.includes('psa')) return 'PSA';
    if (t.includes('rmteam')) return 'RMTEAM';
    if (t.includes('galaxyrg')) return 'GALAXYRG';
    if (t.includes('megusta')) return 'MEGUSTA';
    if (t.includes('tigole')) return 'TIGOLE';
    if (t.includes('qxr')) return 'QXR';
    if (t.includes('utr')) return 'UTR';
    if (t.includes('xannyfamily')) return 'ADLEN';
    return 'P2P++';
}

function getPeerScore(title) {
    const peer = getPeerSite(title);
    const order = [
        'VidKing⚡', 'VegaMovies⚡', 'MovieBox⚡', 'Yastream✨', 'HDGharTv','CineJoy','HD-Hub🌐','YTS', '1337X', 'TIGOLE', 'ADLEN', 'RARBG', 'RUTRACKER', 'TPB', 'EZTV', 'PSA', 
        'TORLOCK', 'ZOOQLE', 'SOLID', 'BITSEARCH', 'QXR', 'TL', 'NYAA', 'UTR', 'GLODLS', 
        'TFUNK', 'ETTV', 'GALAXYRG', 'RMTEAM', 'MEGUSTA', 'TGX', 'RUTOR', 'LIME', 'TD', 
        'MAGNETDL', 'IDOPE', 'KAT'
    ];
    const index = order.indexOf(peer);
    return index !== -1 ? order.length - index : 0;
}

/* ================= SIZE ================= */
function getFileSize(title) {
    if (!title) return null;
    const t = title.replace(/,/g, '.');
    const match = t.match(/\b(\d+(?:\.\d+)?)\s*(TB|GB|MB|KB|TIB|GIB|MIB|KIB)\b/i);
    if (!match) return null;

    let size = parseFloat(match[1]);
    let unit = match[2].toUpperCase(); 
    unit = unit.replace('TIB', 'TB').replace('GIB', 'GB').replace('MIB', 'MB').replace('KIB', 'KB');
    return `${size} ${unit}`;
}

/* ================= SEEDERS ================= */
function getSeeders(title) {
    if (!title) return 0;
    const t = String(title).toLowerCase().replace(/\n/g, ' ');
    if (t.includes('unknown')) return 0;

    const match = t.match(/(?:👤|👥|seeders?|seeds?|\bs\b)\s*[:=]?\s*(\d+)/i);
    if (match && match[1]) {
        const num = Number(match[1]);
        return isNaN(num) ? 0 : num;
    }

    const fallbackMatch = t.match(/(\d+)\s*(?:seed|peer)/i);
    if (fallbackMatch && fallbackMatch[1]) {
        const num = Number(fallbackMatch[1]);
        return isNaN(num) ? 0 : num;
    }
    return 0; 
}

/* ================= QUALITY SCORE ================= */
function getQualityScore(text) {
    const t = (text || '').toLowerCase();
    if (t.includes('1080p')) return 10; 
    if (t.includes('4k') || t.includes('2160p')) return 7; 
    if (t.includes('720p')) return 5; 
    return 1;
}

/* ================= LANG SCORE ================= */
function getLangScore(text) {
    const t = (text || '').toLowerCase();
    if (t.includes('fr') || t.includes('french') || t.includes(' vf ') || t.includes(' vff ') || t.includes('francais')) {
        return 1; 
    }
    return 0;
}

/* ================= QUALITY INFO ================= */
function getQualityInfo(title) {
    const t = (title || '').toLowerCase();
    let quality = '';
    let codec = '';
    let lang = 'Unknown';
    let audio = 'Unknown';

    const languages = {
        fr: { flag: '⭐🇫🇷', names: ['french', ' vf ', ' vff ', 'francais'], label: 'VF' },
        en: { flag: '🇺🇸', names: ['english', ' en ', ' eng ', 'anglais'], label: 'VO' },
        es: { flag: '🇪🇸', names: ['spanish', ' es ', ' spa ', 'espanol'] },
        sub: { flag: '💬', names: ['subtitles', ' sub ', 'srt'] },
        it: { flag: '🇮🇹', names: ['italian', ' it ', ' ita ', 'italiano'] },
        ar: { flag: '🇩🇿', names: ['arabic', ' ar ', ' ara ', 'arabe'] },
        ru: { flag: '🇷🇺', names: ['russian', ' ru ', ' rus ', 'russe'] },
        hi: { flag: '🇮🇳', names: ['hindi', ' hi ', ' hin '] },
    };

    const found = Object.entries(languages)
        .filter(([code, data]) => t.includes(code) || data.names.some(name => t.includes(name)))
        .map(([code]) => code);

    if (found.length >= 2) {
        lang = `🎧: ${found.map(code => languages[code].flag).join('/')} `;
    } else if (t.includes('multi')) {
        const hasFrench = t.includes('fr') || languages.fr.names.some(name => t.includes(name));
        lang = hasFrench ? '🎧: ⭐🌍 MULTI ' : '🎧: 🌍 MULTI ';
    } else if (found.length === 1) {
        const code = found[0];
        lang = `🎧: ${languages[code].flag}${code === 'fr' ? ' VF' : (code === 'en' ? ' VO' : '')}`;
    }

    if (t.includes('2160p') || t.includes('4k')) quality = '🟤4K';
    else if (t.includes('1080p')) quality = '🟢1080P';
    else if (t.includes('720p')) quality = '🟠720P';
    else if (t.includes('480p') || t.includes('360p')) quality = '⚪SD';
    else if (t.includes('cam')) quality = '🔴CAM';
    else quality = '🔵Stream';

    if (t.includes('hevc') || t.includes('x265') || t.includes('h265')) codec = 'HEVC';
    else if (t.includes('x264') || t.includes('h264')) codec = 'AVC/x264';
    else codec = 'x264';

    let source = 'MP4';
    if (t.includes('bluray') || t.includes('bdrip')) source = 'BluRay';
    else if (t.includes('web-dl') || t.includes('webdl') || t.includes('webrip')) source = 'WEB-DL';
    else if (t.includes('dvdrip')) source = 'DVDRip';
    else if (t.includes('hdrip')) source = '🎞️HDRip';
    else if (t.includes('uhd')) source = '🖥️UHD';
    else if (t.includes('3d')) source = '🔅3D';
    else if (t.includes('amzn')) source ='🛒AMZN';
    else if (t.includes('10bit')) source = '🎨10BIT';
    else if (t.includes('hdr10')) source = '💯HDR10';
    else if (t.includes('hdr')) source = '✨HDR';
    else if (t.includes('moviebox')) source = 'F-WEB💎';
    else if (t.includes('yastream')) source = 'V-Fast✨';
    else if (t.includes('cinejoy')) source = 'CineJoy💎';
    else if (t.includes('dolby vision') || t.includes(' dv ') || t.includes('vision') || t.includes('.dv.')) source = '🌈D-Vision';
    else if (t.includes('mkv')) source = 'MKV';

    if (t.includes('atmos')) audio = 'Atmos';
    else if (t.includes('dts-hd')) audio = 'DTS-HD MA';
    else if (t.includes('dts')) audio = 'DTS';
    else if (t.includes('ddp5') || t.includes('ddp5.1')) audio = 'DDP5.1';
    else if (t.includes('truehd')) audio = 'TrueHD';
    else if (t.includes('aac')) audio = 'AAC';

    return { quality, codec, source, audio, lang };
}

/* ================= FILTER FAKE ADVANCED ================= */
function isFake(title = '') {
    const t = title.toLowerCase();
    const fakeKeywords = [
        'sample', 'trailer', 'test', 'fake', 'scam', 'virus', 
        'password', 'mot de passe', 'crack', 'patched', 'serial',
        'keyger', 'keygen', 'unzip me', 'extract me', 'install', 
        'setup', 'update', 'vlc player', 'codec update'
    ];
    if (fakeKeywords.some(keyword => t.includes(keyword))) return true;

    const dangerousExtensions = /\.(exe|scr|bat|cmd|vbs|rar|zip|iso|dmg|tar|7z)\b/i;
    if (dangerousExtensions.test(t)) return true;

    const scamPatterns = /(free[\s_-]?movie|download[\s_-]?here|click[\s_-]?here|premium)/i;
    if (scamPatterns.test(t)) return true;

    return false;
}

/* ================= DETECT PREMIUM UPLOADERS ================= */
function getUploader(title) {
    if (!title) return "";
    const t = title.toLowerCase();
    const topGroups = [
        { name: "FraMeSToR", label: "💎 FraMeSToR" },
        { name: "EPSILON", label: "💎 EPSILON" },
        { name: "Tigole", label: "⭐ Tigole" },
        { name: "QxR", label: "⭐ QxR" },
        { name: "PSA", label: "⭐ PSA" },
        { name: "Joy", label: "⭐ Joy" },
        { name: "NTb", label: "⚡ NTb" },
        { name: "FLUX", label: "⚡ FLUX" },
        { name: "DON", label: "⭐ DON" },
        { name: "CtrlHD", label: "⭐ CtrlHD" },
        { name: "WiKi", label: "⭐ WiKi" },
        { name: "GanoOM", label: "⭐ GanoOM" }
    ];
    for (const group of topGroups) {
        const regex = new RegExp(`\\b${group.name.toLowerCase()}\\b`, 'i');
        if (regex.test(t)) return group.label;
    }
    return "";
}

/* ================= STREAM ROUTE ================= */
app.get('/stream/:type/:id.json', async (req, res) => {
    const { type, id } = req.params;
    const cacheKey = `${type}-${id}`;

    const cached = cache.get(cacheKey);
    if (cached) return res.json(cached);

    const promises = SOURCES.map(source =>
        axios.get(`${source.url}/stream/${type}/${id}.json`, { 
            timeout: TIMEOUT,
            headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' }
        })
        .then(res => (res.data.streams || []).map(s => ({
            ...s,
            sourceName: source.name
        })))
        .catch((err) => {
            console.log(`[Source Error] ${source.name}: ${err.message}`);
            return [];
        })
    );

    const results = await Promise.all(promises);
    let finalStreams = [];
    const seenKeys = new Set();
    const seenContents = new Set();

    results.forEach((sourceStreams, index) => {
        const sourceName = SOURCES[index].name;
        const counts = { '1080p': 0, '4k': 0, '720p': 0, 'other': 0 };

        const sortedSourceStreams = [...sourceStreams].sort((a, b) => getSeeders(b.title) - getSeeders(a.title));

        for (const stream of sortedSourceStreams) {
            // 0. Ignorer les liens externes / dons
            if (stream.externalUrl && !stream.url) continue;

            // 1. Reconstituer un rawTitle complet (title OU name + description)
            let rawTitle = stream.title || '';
            if (!rawTitle) {
                const nameStr = stream.name || '';
                const descStr = stream.description || '';
                rawTitle = `${nameStr}\n${descStr}`;
            }

            // 2. Filtrage strict par mots-clés de fakes
            if (isFake(rawTitle)) continue;

            // 3. Extraction/Calcul de la taille
            let size = getFileSize(rawTitle);

            // Secours si la taille est dans behaviorHints.videoSize (en octets)
            if (!size && stream.behaviorHints && stream.behaviorHints.videoSize) {
                const bytes = stream.behaviorHints.videoSize;
                const mb = (bytes / (1024 * 1024)).toFixed(0);
                if (mb >= 1000) {
                    size = `${(mb / 1024).toFixed(2)} GB`;
                } else {
                    size = `${mb} MB`;
                }
            }

            // Secours par défaut élargi pour les flux Cinejoy / HLS / IPTV sans taille fixe
            const lowerTitle = rawTitle.toLowerCase();
            const streamUrl = (stream.url || '').toLowerCase();
            const isStreamSource = lowerTitle.includes('cinejoy') ||
                                    lowerTitle.includes('m3u8') ||
                                    lowerTitle.includes('auto') ||
                                    lowerTitle.includes('hls') ||
                                    streamUrl.includes('m3u8') ||
                                    streamUrl.includes('hls') ||
                                    streamUrl.includes('cinejoy');

            if (!size && isStreamSource) {
                size = "STREAM";
            }

            if (!size) continue;

            // Calcul de la taille en MB pour le filtre < 400 MB
            let sizeInMB = 0;
            if (size === "STREAM") {
                sizeInMB = 9999; // bypass pour laisser passer les flux HLS direct
            } else {
                const sizeValue = parseFloat(size);
                if (size.includes("GB")) sizeInMB = sizeValue * 1024;
                else if (size.includes("MB")) sizeInMB = sizeValue;
            }

            if (size !== "STREAM" && sizeInMB < 400) continue;

            // 4. Élimination des doublons de réseau stricts (Clé unique)
            let key = (stream.infoHash || stream.url || '').toLowerCase().trim();
            if (!key || seenKeys.has(key)) continue;

            // 5. Nettoyage du nom de fichier
            let cleanedRawTitle = rawTitle;
            if (rawTitle.toLowerCase().includes('vela')) {
                cleanedRawTitle = rawTitle.replace(/[|.\-_]?\s*vela\s*[|.\-_]?/gi, '').trim();
                cleanedRawTitle = cleanedRawTitle.replace(/\s*[|]\s*/g, '|').trim();
                cleanedRawTitle = cleanedRawTitle.replace(/[.\-_]{2,}/g, '.').trim();
            }

            const lines = cleanedRawTitle.split('\n').map(s => s.trim());

            let fileName =
                lines.find(l => l.startsWith('🍿')) ||
                lines.find(l => /\(\d{4}\)/.test(l)) ||
                lines[0] ||
                'Unknown';
            fileName = fileName
                .replace(/\s*(1080p|720p|4k|2160p|hevc|x265|x264|h264|h265|bluray|web-dl|webrip|bdrip|dvdrip|hdrip|amzn|hdr|dolby vision|atmos|dts|aac)\s*/gi, '')
                .replace(/\s*(🐧 PenguPlay|pengu)\s*/gi, 'Fast Source🔥 :')
                .replace(/\s*(🐧)\s*/gi, '📼')
                .replace(/\s*(🍿)\s*/gi, '')
                .replace(/\s*[\[\(].*?[\]\)]\s*/g, '') 
                .replace(/[.\-_]{2,}/g, '.') 
                .replace(/^[.\-_]+|[.\-_]+$/g, '') 
                .trim();

            if (fileName.length > 60) {
                fileName = fileName.substring(0, 57) + '...';
            }

            // 6. Élimination des doublons visuels
            const contentSignature = `${fileName.toLowerCase()}_${size.toLowerCase()}`.replace(/\s+/g, '');
            if (seenContents.has(contentSignature)) continue;

            // 7. Quotas par catégories de qualité
            const t = rawTitle.toLowerCase();
            let qType = 'other';
            if (t.includes('1080p')) qType = '1080p';
            else if (t.includes('4k') || t.includes('2160p')) qType = '4k';
            else if (t.includes('720p')) qType = '720p';

            if (counts[qType] >= 25) continue;

            // Validation finale
            seenKeys.add(key);
            seenContents.add(contentSignature);
            counts[qType]++;

            // 8. Collecte des métadonnées enrichies
            const info = getQualityInfo(rawTitle);
            const seeds = getSeeders(rawTitle);
            const seedText = seeds > 0 ? seeds : "Speed⚡";
            const peer = getPeerSite(rawTitle);
            const uploader = getUploader(rawTitle);
            const uploaderTag = uploader ? ` | 👑 ${uploader}` : "";

            const buttonName = `🎬 ${info.quality !== 'Unknown' ? info.quality : ''} |📦 ${info.codec} | ${info.source}`.trim();

            let packInfo = "";
            const packMatch = rawTitle.match(/Pack:\s*(\d+(?:\.\d+)?\s*[TGMBK]B)/i);
            if (packMatch) {
                packInfo = ` / Pack: ${packMatch[1]}`;
            }

            // Conservation des behaviorHints originaux
            const behavior = stream.behaviorHints ? { ...stream.behaviorHints, notWebReady: true } : { notWebReady: true };
            console.log(stream.behaviorHints);

            finalStreams.push({
                name: buttonName || sourceName,
                title: `📁: ${fileName}\n💾: ${size}${packInfo}\n👥: ${seedText} | ⚙️: ${peer} • 📡:${sourceName}${uploaderTag}\n🌍: ${info.lang}`,
                infoHash: stream.infoHash ? stream.infoHash.toLowerCase() : undefined,
                url: stream.url,
                fileIdx: stream.fileIdx,
                behaviorHints: behavior,
                _isTopSource:
                    (sourceName === 'HTTP.DZ1⭐' || 
                      sourceName === 'HTTP.DZ2⭐' || 
                      sourceName === 'HTTP.DZ3⭐' || 
                      sourceName === 'HTTP.DZ4⭐') ? 1 : 0,
                _sortQuality: getQualityScore(cleanedRawTitle),
                _sortPeer: getPeerScore(cleanedRawTitle),
                _sortSeeds: seeds,
                _sortLang: getLangScore(cleanedRawTitle)
            });
        }
    });

    // Tri final des flux
    finalStreams.sort((a, b) => {
        if (b._isTopSource !== a._isTopSource) return b._isTopSource - a._isTopSource;
        if (b._sortPeer !== a._sortPeer) return b._sortPeer - a._sortPeer; 
        if (b._sortSeeds !== a._sortSeeds) return b._sortSeeds - a._sortSeeds;
        return b._sortLang - a._sortLang;
    });

    // Nettoyage des propriétés temporaires de tri
    finalStreams.forEach(s => {
        delete s._sortQuality;
        delete s._sortPeer;
        delete s._sortSeeds;
        delete s._sortLang;
    });

    cache.set(cacheKey, { streams: finalStreams });
    res.json({ streams: finalStreams });
});

/* ================= MANIFEST & HOME ROUTES ================= */
app.get('/manifest.json', (req, res) => res.json(MANIFEST));
app.get('/', (req, res) => res.json(MANIFEST));

const PORT = process.env.PORT || 7860;
app.listen(PORT, () => console.log(`Torrent DZ ONLINE FIXED ON PORT ${PORT}`));