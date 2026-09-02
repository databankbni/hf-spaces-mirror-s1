const express = require('express');
const axios = require('axios');
const cors = require('cors');
const NodeCache = require('node-cache');

const app = express();
app.use(cors());

const cache = new NodeCache({ stdTTL: 180, checkperiod: 240 });
const TIMEOUT = 5000;

const MANIFEST = {
    id: 'org.golink.payload',
    version: '2.5.0',
    name: '🔻GHOST🔻',
    description: 'Multi-Sources Rapide - Films & Series By Superadlen DZ',
    resources: ['stream'],
    types: ['movie', 'series'],
    idPrefixes: ['tt', 'tmdb:', 'kitsu'],
    catalogs: [],
    logo: 'https://i.pinimg.com/736x/bf/77/e2/bf77e2c4b9cff50ef427ca9d4e9dfe77.jpg'
};

const SOURCES = [
    { url: 'https://showbox.codiv.dpdns.org/%7B%22cookie%22%3A%22eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE3ODUzMTQ1NDUsIm5iZiI6MTc4NTMxNDU0NSwiZXhwIjoxODE2NDE4NTY1LCJkYXRhIjp7InVpZCI6MjIzNDQxOCwidG9rZW4iOiI1MjNhNGExMTUxNjg4NmM0YzJkZDg3OTU1ZWUzZTg4MiJ9fQ.8YXH3OC9NPAYVi7Dkk3kJzSixgfsWmVl7Gd9qWG4IGk%22%7D', name: '⭐HTTP.SHBX' },
    { url: 'https://pengu.uk/%7B%22auth_token%22%3A%22kep9D1CCHeIAunGPNrfG2IJoqX5KyeR8q-CbYqQMplo%22%7D', name: '⭐HTTP MOVIEBOX' },
    { url: 'https://nova-addon-9nxe.onrender.com', name: 'HTTP NOVA' },
    { url: 'https://febbox-addon.onrender.com/LgUfPQ_WqR3zX4Ljmr8NsZg8DIl6_jiSLrDGr30gzelVyK4Ca6ClbKq7zjjmBtwyzkzvNPBYe-krA3LIkZ1Zv6T4oSxAoULXQKJJ-ekAuDGXZ3jfIVp9NPrIjfbtBxd88LbInSRAWBmOdx-maKwUVnrSm65XFVzzn9VkuAs9J3HtUPcAfH1w8cNeoZxVd_ihY3Ufzp7HpG411AsQAnOzE6dWf1rU0MCJX8Xp5RQyAJVotMCW4EXlMeOENURf2COXFBG27INfNIPDgQ6Yi3CBmJsmNc_pM7UzCs96tiAqJHXjptWrnPGsh2SWkHAX_-mISRnf_-ULXjFACZmJhYScEoaOgEPrYsedAht1ZmT_EZ6pwWLQ2cyG0Yne43urufsTIAMnnqxBxh1HYdeNFmaYmExPhQz1dTDMhRl3hJki6Xl94-fAm-Jq5JrNKN915TaUSS4nIwKvJdD3nbKEq9qTBmNG10d2BPVvxQDWWFUjipiCN-kM2Q', name: 'HTTP FEB' },
    { url: 'https://87d6a6ef6b58-webstreamrmbg.baby-beamup.club/%7B%22multi%22%3A%22on%22%2C%22fr%22%3A%22on%22%2C%22excludeResolution_Unknown%22%3A%22on%22%2C%22excludeResolution_144p%22%3A%22on%22%2C%22excludeResolution_240p%22%3A%22on%22%2C%22excludeResolution_360p%22%3A%22on%22%2C%22excludeResolution_480p%22%3A%22on%22%2C%22excludeResolution_576p%22%3A%22on%22%2C%22excludeResolution_720p%22%3A%22on%22%7D', name: 'HTTP MBG ' },
    { url: 'https://addon.peerflix.mov/language=en|qualityfilter=sd,480p,540p,hdtv,screener,vhs,unknown|sort=seed-desc,quality-desc,size-desc', name: 'DZ1' },
    { url: 'https://filmora2.vercel.app', name: 'DZ2' },
    { url: 'https://str.zmb.lat/lite', name: 'DZ3' },
    { url: 'https://zamunda-stremio.tzkppv.com/debrid=none|content=all|quality=4k,1080p,720p|lang=en', name: 'DZ4' },
    { url: 'https://hdhub.thevolecitor.qzz.io/eyJ0b3Jib3giOiJ1bnNldCIsInF1YWxpdGllcyI6IjIxNjBwLDEwODBwLDcyMHAiLCJzb3J0IjoiZGVzYyJ9', name: 'DZ5' },
    { url: 'https://watcho3.rafaelzioneverest.workers.dev', name: 'DZ6' },
    { url: 'https://vela-flow.vercel.app', name: 'DZ7' },
    { url: 'https://magneto-jnv5.onrender.com/v1', name: 'DZ8' },
    { url: 'https://toastflix.stremio-italia.eu/eyJtdWx0aUxhbmdNb2RlIjp0cnVlLCJzb2xvRkhEIjp0cnVlLCJzb2xvRGlyZWN0Ijp0cnVlfQ', name: 'HTTP IT' },
    { url: 'https://87d6a6ef6b58-webstreamrmbg.baby-beamup.club/%7B%22multi%22%3A%22on%22%2C%22fr%22%3A%22on%22%2C%22excludeResolution_Unknown%22%3A%22on%22%2C%22excludeResolution_144p%22%3A%22on%22%2C%22excludeResolution_240p%22%3A%22on%22%2C%22excludeResolution_360p%22%3A%22on%22%2C%22excludeResolution_480p%22%3A%22on%22%2C%22excludeResolution_576p%22%3A%22on%22%7D', name: 'HTTP MBG 2 ' },
    { url: 'https://aiostreamsfortheweebsstable.midnightignite.me/stremio/7ea1e7e7-0315-45a1-be59-ea3a3e79c872/eyJpIjoieWRtQ0lwU3BhNm92aXduUDJzUGZ3dz09IiwiZSI6ImdYS2NhMG41dU5OOGN0QURMZlZRK1UzeHBMb2lMYzJORkdwa2ViNWIxcjA9IiwidCI6ImEifQ', name: 'DZ11' },
    { url: 'https://froststream.cloutteam.com/%7B%22providers%22%3A%7B%22cdmoviedb%22%3Atrue%2C%22redeflix%22%3Atrue%2C%22tomato%22%3Atrue%2C%22myembed%22%3Atrue%2C%22anizone%22%3Atrue%7D%2C%22resolutions%22%3A%7B%224K%22%3Atrue%2C%221080p%22%3Atrue%2C%22720p%22%3Atrue%2C%22SD%22%3Afalse%2C%22Cinema%22%3Afalse%7D%2C%22iptvSources%22%3A%7B%224k2026%22%3Atrue%2C%22HJA%22%3Atrue%2C%22SvenTank%22%3Atrue%2C%22Shazam%22%3Atrue%7D%7D', name: 'DZ10' },
];

/* ================= UTILS & PARSERS ================= */

function getFileSize(title, behaviorHints) {
    // 1. Chercher d'abord dans le titre
    if (title) {
        const t = title.replace(/,/g, '.');
        const match = t.match(/\b(\d+(?:\.\d+)?)\s*(TB|GB|MB|KB|TIB|GIB|MIB|KIB)\b/i);
        if (match) {
            let size = parseFloat(match[1]);
            let unit = match[2].toUpperCase().replace('TIB', 'TB').replace('GIB', 'GB').replace('MIB', 'MB').replace('KIB', 'KB');
            return `${size} ${unit}`;
        }
    }
    // 2. Chercher dans behaviorHints.videoSize (octets bruts)
    if (behaviorHints && behaviorHints.videoSize) {
        const bytes = Number(behaviorHints.videoSize);
        if (!isNaN(bytes) && bytes > 0) {
            const gb = bytes / (1024 * 1024 * 1024);
            if (gb >= 1) return `${gb.toFixed(2)} GB`;
            const mb = bytes / (1024 * 1024);
            return `${mb.toFixed(0)} MB`;
        }
    }
    return null;
}

function getSeeders(title) {
    if (!title) return 0;
    const t = String(title).toLowerCase().replace(/\n/g, ' ');
    if (t.includes('unknown')) return 0;

    const match = t.match(/(?:👤|👥|seeders?|seeds?|\bs\b)\s*[:=]?\s*(\d+)/i) || t.match(/(\d+)\s*(?:seed|peer)/i);
    return (match && match[1]) ? parseInt(match[1], 10) || 0 : 0;
}

function getQualityInfo(text) {
    const t = (text || '').toLowerCase();
    let quality = 'HD';
    let codec = '';
    let lang = 'MULTI';

    const languages = {
        fr: { flag: '🇫🇷', names: ['french', ' vf ', ' vff ', 'francais'] },
        en: { flag: '🇺🇸', names: ['english', ' en ', ' eng ', 'anglais'] },
        es: { flag: '🇪🇸', names: ['spanish', ' es ', ' spa ', 'espanol'] },
        ar: { flag: '🇩🇿', names: ['arabic', ' ar ', ' ara ', 'arabe'] },
    };

    const found = Object.entries(languages)
        .filter(([code, data]) => t.includes(code) || data.names.some(name => t.includes(name)))
        .map(([code]) => code);

    if (t.includes('multi')) lang = '⭐ 🌍 MULTI';
    else if (found.length > 0) lang = languages[found[0]].flag + ' ' + found[0].toUpperCase();

    if (t.includes('2160p') || t.includes('4k')) quality = '4K';
    else if (t.includes('1080p')) quality = '1080p';
    else if (t.includes('720p')) quality = '720p';

    if (t.includes('hevc') || t.includes('x265') || t.includes('h265')) codec = 'HEVC';
    else if (t.includes('x264') || t.includes('h264')) codec = 'x264';

    return { quality, codec, lang };
}

function getQualityScore(qualityStr) {
    if (qualityStr === '1080p') return 40;
    if (qualityStr === '4K') return 30;
    if (qualityStr === '720p') return 20;
    return 10;
}

function isFake(title = '') {
    const t = title.toLowerCase();
    const fakeKeywords = ['sample', 'trailer', 'fake', 'scam', 'virus', 'password', 'keygen', 'setup.exe'];
    if (fakeKeywords.some(keyword => t.includes(keyword))) return true;
    return /\.(exe|scr|bat|cmd|vbs|rar|zip|iso)\b/i.test(t);
}

/* ================= STREAM ROUTE ================= */

app.get('/stream/:type/:id.json', async (req, res) => {
    res.setHeader('Content-Type', 'application/json');

    const { type, id } = req.params;
    const cacheKey = `${type}-${id}`;

    const cached = cache.get(cacheKey);
    if (cached) return res.json(cached);

    const promises = SOURCES.map(source =>
        axios.get(`${source.url}/stream/${type}/${id}.json`, {
            timeout: TIMEOUT,
            headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' }
        })
        .then(response => (response.data && response.data.streams ? response.data.streams : []).map(s => ({
            ...s,
            sourceName: source.name
        })))
        .catch(() => [])
    );

    const results = await Promise.all(promises);
    let finalStreams = [];
    const seenKeys = new Set();

    results.forEach((sourceStreams) => {
        for (const stream of sourceStreams) {
            const rawTitle = stream.title || stream.name || '';

            if (isFake(rawTitle)) continue;

            const isDirect = Boolean(stream.url);
            const isTorrent = Boolean(stream.infoHash);

            // Clé d'unicité
            let uniqueKey = isTorrent 
                ? stream.infoHash.toLowerCase().trim() 
                : (stream.url ? stream.url.trim() : null);

            if (!uniqueKey || seenKeys.has(uniqueKey)) continue;

            const size = getFileSize(rawTitle, stream.behaviorHints);
            const info = getQualityInfo(rawTitle + ' ' + (stream.name || ''));
            const seeds = getSeeders(rawTitle);

            // Serveur Label
            const serverLabel = stream.sourceName || (isDirect ? 'HTTP Direct' : 'Torrent');
            const streamTypeIcon = isDirect ? '⚡ DIRECT' : '🧲 TORRENT';
            
            // 1. Bouton Principal Stremio
            const displayName = `[${serverLabel}] ${info.quality} ${streamTypeIcon}`;

            // 2. Titre / Description déroulante
            let cleanFileName = rawTitle.split('\n')[0].replace(/[\/\\]/g, '').trim();
            if (cleanFileName.length > 65) cleanFileName = cleanFileName.substring(0, 62) + '...';

            let displayDetails = `📁 ${cleanFileName}\n`;
            if (size) displayDetails += `💾 ${size} `;
            if (isTorrent) displayDetails += `| 👥 Seeds: ${seeds} `;
            displayDetails += `\n🌍 ${info.lang} ${info.codec ? '| 📦 ' + info.codec : ''}`;

            // Transfert complet des behaviorHints d'origine du serveur (ex: bingeGroup, videoSize, notWebReady)
            const behaviorHints = stream.behaviorHints ? { ...stream.behaviorHints } : {};

            const formattedStream = {
                name: displayName,
                title: displayDetails,
                behaviorHints: behaviorHints
            };

            if (isDirect) {
                formattedStream.url = stream.url;
            } else if (isTorrent) {
                formattedStream.infoHash = stream.infoHash.toLowerCase();
                if (stream.fileIdx !== undefined) formattedStream.fileIdx = stream.fileIdx;
            }

            if (stream.subtitles) formattedStream.subtitles = stream.subtitles;

            // Score de priorité pour le tri :
            // 100 = ⭐HTTP.SHBX
            // 80  = Autres serveurs HTTP Direct
            // 10  = Torrents
            let priorityScore = 10;
            if (serverLabel === '⭐HTTP.SHBX') {
                priorityScore = 100;
            } else if (isDirect) {
                priorityScore = 80;
            }

            formattedStream._priorityScore = priorityScore;
            formattedStream._qualityScore = getQualityScore(info.quality);
            formattedStream._seeds = seeds;

            seenKeys.add(uniqueKey);
            finalStreams.push(formattedStream);
        }
    });

    // --- RÈGLE DE TRI FINAL ---
    // 1. ⭐HTTP.SHBX en premier, suivi des autres HTTP Direct, puis Torrents
    // 2. Qualité vidéo (1080p > 4K > 720p)
    // 3. Seeders (si torrent)
    finalStreams.sort((a, b) => {
        if (b._priorityScore !== a._priorityScore) {
            return b._priorityScore - a._priorityScore;
        }
        if (b._qualityScore !== a._qualityScore) {
            return b._qualityScore - a._qualityScore;
        }
        return b._seeds - a._seeds;
    });

    // Nettoyage des variables de tri
    finalStreams.forEach(s => {
        delete s._priorityScore;
        delete s._qualityScore;
        delete s._seeds;
    });

    const responsePayload = { streams: finalStreams };
    cache.set(cacheKey, responsePayload);
    res.json(responsePayload);
});

/* ================= MANIFEST & ROUTES CLIENTS ================= */

const sendManifest = (req, res) => {
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.json(MANIFEST);
};

app.get('/manifest.json', sendManifest);
app.get('/', sendManifest);

const PORT = process.env.PORT || 7860;
app.listen(PORT, () => console.log(`GHOST Addon v2.5 ONLINE ON PORT ${PORT}`));