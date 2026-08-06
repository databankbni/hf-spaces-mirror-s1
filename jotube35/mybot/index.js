const { Client, Events, ActivityType } = require('discord.js');
require('dotenv').config(); 

const { botIntents, botPartials } = require('./config');
require('./database'); 

const client = new Client({
    intents: botIntents,
    partials: botPartials
});

const _formatErr = (e) => (e && e.message) ? e.message : String(e);

// ==========================================
// 🛡️ درع حماية النظام من الانهيار (Anti-Crash)
// ==========================================
process.on('unhandledRejection', (reason, promise) => {
    console.error('[-] Unhandled Rejection Prevented:', _formatErr(reason));
});

process.on('uncaughtException', (err, origin) => {
    console.error('[-] Uncaught Exception Prevented:', _formatErr(err));
});

process.on('uncaughtExceptionMonitor', (err, origin) => {
    console.error('[-] Uncaught Exception Monitor:', _formatErr(err));
});

// ==========================================
// 🚀 حدث التشغيل الأساسي والـ Status
// ==========================================
client.once(Events.ClientReady, () => {
    console.log(`✅ Engine Bot Online: ${client.user.tag}`);
    
    let statusIndex = 0;
    
    setInterval(() => {
        const guildCount = client.guilds.cache.size;
        let memberCount = 0;
        
        client.guilds.cache.forEach((guild) => { 
            memberCount = memberCount + guild.memberCount; 
        });
        
        const statuses = [
            { name: `Powerful Security Style 🛡️`, type: ActivityType.Watching },
            { name: `${memberCount} Users 👥`, type: ActivityType.Listening },
            { name: `Protecting ${guildCount} Servers 📡`, type: ActivityType.Playing }
        ];
        
        client.user.setActivity(statuses[statusIndex].name, { type: statuses[statusIndex].type });
        
        statusIndex = statusIndex + 1;
        if (statusIndex >= statuses.length) {
            statusIndex = 0;
        }
    }, 10000);
});

// ==========================================
// 📂 تحميل ملفات الأحداث والأوامر
// ==========================================
require('./events')(client);
require('./commands')(client);

// ==========================================
// تسجيل الدخول
// ==========================================
client.login(process.env.TOKEN);