const { GatewayIntentBits, Partials } = require('discord.js');

const botIntents = [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.GuildMembers,
    GatewayIntentBits.GuildModeration,
    GatewayIntentBits.MessageContent,
    GatewayIntentBits.GuildVoiceStates,
    GatewayIntentBits.GuildPresences 
];

const botPartials = [
    Partials.Message,
    Partials.Channel,
    Partials.User,
    Partials.GuildMember
];

const colors = { 
    main: 0x2B2D31, 
    success: 0x57F287, 
    error: 0xED4245, 
    warning: 0xFEE75C, 
    info: 0x5865F2 
};

const ONE_DAY_MS = 24 * 60 * 60 * 1000;
const TWO_DAYS_MS = 2 * ONE_DAY_MS;
const MAX_TIMEOUT_MS = 28 * ONE_DAY_MS; 
const SPAM_LIMIT = 4;
const SPAM_TIME = 5000;

const badWords = [
    'كسمك', 'متناك', 'عرص', 'خول', 'متناكه', 'متناكين',
    'معرصين', 'قحبه', 'قحبة', 'متناكة', 'fuck', 'kosomk',
    'w9', 'kosmk', 'kos', 'امك', 'كس', 'bitch',
    'عاهرة', 'عاهره', 'انيكك', 'ميتين', 'ميتينك', 'معرص',
    'انيك', 'زب', 'زبي', 'ايري', 'قواد',
    'بزاز', 'وسخه', 'وسخة', 'طيز', 'طيزك', 'سكس', 
    'sex', 'porn', 'نيكني', 'ميتناك'
]; 

const escapeRegExp = (string) => string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const buildSmartRegex = (words) => {
    const patterns = words.map(w => {
        return w.split('').map(char => {
            if (/[اأإآ]/.test(char)) return '[اأإآ]+';
            if (/[هة]/.test(char)) return '[هة]+';
            if (/[يى]/.test(char)) return '[يى]+';
            
            if (char === 'a') return '[a@4]+';
            if (char === 'e') return '[e3]+';
            if (char === 'i') return '[i1!]+';
            if (char === 'o') return '[o0]+';
            if (char === 's') return '[s$5]+';
            
            return escapeRegExp(char) + '+';
        }).join('[\\W_]*');
    });
    
    return new RegExp(`(?:^|\\s|\\W)(${patterns.join('|')})(?:$|\\s|\\W)`, 'gi');
};

const smartSwearRegex = buildSmartRegex(badWords);

const spamMap = new Map();
const kickTracker = new Map();
const banTracker = new Map();
const channelTracker = new Map();
const roleTracker = new Map();
const swearTracker = new Map();
const joinTracker = new Map();
const raidMode = new Map();

const parseTime = (str) => {
    if (!str) return null;
    const match = str.match(/^(\d+)([smhd])$/);
    if (!match) return null;
    
    const val = parseInt(match[1]);
    const unit = match[2];
    
    if (unit === 's') return val * 1000;
    if (unit === 'm') return val * 60 * 1000;
    if (unit === 'h') return val * 60 * 60 * 1000;
    if (unit === 'd') return val * 24 * 60 * 60 * 1000;
    
    return null;
};

module.exports = {
    botIntents, botPartials, colors, ONE_DAY_MS, TWO_DAYS_MS, MAX_TIMEOUT_MS,
    SPAM_LIMIT, SPAM_TIME, badWords, smartSwearRegex, spamMap, kickTracker,
    banTracker, channelTracker, roleTracker, swearTracker, joinTracker, raidMode, parseTime
};