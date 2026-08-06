const mongoose = require('mongoose'); 

const GLOBAL_DEVELOPER_ID = '1263909996404539497'; 
let db = {};

const GuildModel = mongoose.model('GuildData', new mongoose.Schema({
    guildId: { 
        type: String, 
        required: true, 
        unique: true 
    },
    data: { 
        type: Object, 
        default: {} 
    }
}, { minimize: false })); 

const dbUri = process.env.MONGO_URI || process.env.MONGO_URL;

if (dbUri) {
    mongoose.connect(dbUri).then(async () => {
        console.log('✅ Connected to Host MongoDB Successfully!');
        
        const allGuilds = await GuildModel.find({});
        
        allGuilds.forEach((g) => {
            db[g.guildId] = g.data;
        });
        
        console.log(`✅ Loaded ${allGuilds.length} guilds into memory cache.`);
    }).catch((err) => {
        console.error('❌ MongoDB Connection Error:', (err && err.message) ? err.message : String(err));
    });
} else {
    console.log('❌ MONGO_URI not found in environment variables!');
}

let isDbUpdated = false;

const saveDB = () => {
    isDbUpdated = true;
};

setInterval(async () => {
    if (isDbUpdated) {
        isDbUpdated = false;
        
        try {
            const bulkOps = Object.keys(db).map((guildId) => {
                return {
                    updateOne: {
                        filter: { 
                            guildId: guildId 
                        },
                        update: { 
                            guildId: guildId, 
                            data: db[guildId] 
                        },
                        upsert: true
                    }
                };
            });
            
            if (bulkOps.length > 0) {
                await GuildModel.bulkWrite(bulkOps);
            }
        } catch (err) {
            console.error('[-] Error saving to MongoDB:', (err && err.message) ? err.message : String(err));
        }
    }
}, 15000); 

const getGuildDB = (guildId) => {
    if (!db[guildId]) {
        db[guildId] = {
            language: 'en',
            users: { 
                root: [], admin: [], mod: [], helper: [], builder: [], immune: [], role_master: [], danger: [] 
            },
            roles: { 
                admin: [], mod: [], helper: [], builder: [], immune: [], protected: [], role_master: [], danger: [] 
            },
            logChannels: { 
                security: null, messages: null, members: null, voice: null, server: null 
            },
            security: { 
                antiLink: true, antiSpam: true, antiAlt: true, antiSwear: true, antiRaid: true 
            },
            limits: { 
                antiNukeKick: 4, antiNukeBan: 2, antiNukeChannel: 3, antiNukeRole: 3 
            },
            jail: { 
                role: null, channel: null 
            },
            jailedUsers: {},
            autoRoles: []
        };
        saveDB();
    }
    
    if (!db[guildId].limits.antiNukeChannel) {
        db[guildId].limits.antiNukeChannel = 3;
        db[guildId].limits.antiNukeRole = 3;
        saveDB();
    }

    if (!db[guildId].users.danger) {
        db[guildId].users.danger = [];
        db[guildId].roles.danger = [];
        saveDB();
    }
    
    if (!db[guildId].swearTracker) {
        db[guildId].swearTracker = {};
        saveDB();
    }

    if (!db[guildId].jail) {
        db[guildId].jail = { role: null, channel: null };
        db[guildId].jailedUsers = {};
        saveDB();
    }

    if (!db[guildId].autoRoles) {
        db[guildId].autoRoles = [];
        saveDB();
    }
    
    return db[guildId];
};

module.exports = { GLOBAL_DEVELOPER_ID, db, getGuildDB, saveDB, GuildModel };