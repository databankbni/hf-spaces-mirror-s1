const { EmbedBuilder } = require('discord.js');
const locales = require('./locales');
const { getGuildDB } = require('./database');
const { colors } = require('./config');

const t = (guildId, key, variables = {}) => {
    const guildDB = getGuildDB(guildId);
    let lang = guildDB.language || 'en';
    
    let text = locales[lang][key] || locales['en'][key] || key;
    
    for (const [varName, varValue] of Object.entries(variables)) {
        text = text.replace(new RegExp(`{${varName}}`, 'g'), varValue);
    }
    
    return text;
};

const createEmbed = (desc, color = colors.main) => {
    const newEmbed = new EmbedBuilder();
    newEmbed.setDescription(desc);
    newEmbed.setColor(color);
    
    return newEmbed;
};

const tempSend = async (channel, options, ms = 7000) => {
    try {
        const msg = await channel.send(options);
        setTimeout(() => {
            msg.delete().catch(() => {});
        }, ms);
    } catch (err) {}
};

const tempReply = async (message, options, ms = 7000) => {
    try {
        const msg = await message.reply(options);
        setTimeout(() => {
            msg.delete().catch(() => {});
        }, ms);
    } catch (err) {}
};

module.exports = { t, createEmbed, tempSend, tempReply };