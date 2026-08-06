const { 
    PermissionsBitField, 
    EmbedBuilder, 
    AttachmentBuilder, 
    ActionRowBuilder, 
    StringSelectMenuBuilder, 
    StringSelectMenuOptionBuilder, 
    UserSelectMenuBuilder, 
    ComponentType, 
    ButtonBuilder, 
    ButtonStyle, 
    ChannelType, 
    MessageFlags 
} = require('discord.js');

const { 
    colors, MAX_TIMEOUT_MS, SPAM_LIMIT, SPAM_TIME, 
    smartSwearRegex, spamMap, parseTime 
} = require('./config');

const { GLOBAL_DEVELOPER_ID, getGuildDB, saveDB } = require('./database');

const { 
    isDev, isGuildOwnerOrDev, isRoot, isDanger, isRoleMaster, isAdmin, 
    isMod, isBuilder, isImmune, isHigherHierarchy 
} = require('./permissions');

const { t, createEmbed } = require('./utils');

module.exports = (client) => {

    // ==========================================
    // 📡 دالة إرسال السجلات المحلية للأوامر
    // ==========================================
    const sendLog = async (guild, category, embed, files = []) => {
        try {
            const guildDB = getGuildDB(guild.id);
            let channelId = guildDB.logChannels[category];
            
            if (!channelId) {
                channelId = guildDB.logChannels.messages || guildDB.logChannels.server;
            }
            
            if (!channelId) return;

            const channel = await guild.channels.fetch(channelId).catch(() => null);
            if (channel) {
                embed.setTimestamp();
                embed.setFooter({ 
                    text: guild.name, 
                    iconURL: guild.iconURL({ dynamic: true }) || client.user.displayAvatarURL() 
                });
                await channel.send({ embeds: [embed], files: files }).catch(() => {});
            }
        } catch (err) {}
    };

    client.on('messageCreate', async (message) => {
        
        if (message.author.bot || !message.guild) {
            return;
        }

        const currentMember = message.member;
        const userId = message.author.id;
        const guildId = message.guild.id;
        let guildDB = getGuildDB(guildId);
        
        // ==========================================
        // دوال مساعدة (Helper Functions)
        // ==========================================
        const getTargetId = async (mentionOrId) => {
            if (!mentionOrId) return null;
            
            let id = mentionOrId.replace(/[<@!>]/g, '');
            if (!/^\d+$/.test(id)) return null;
            
            let user = client.users.cache.get(id);
            if (user) return user.id;
            
            try {
                user = await client.users.fetch(id);
                return user ? user.id : null;
            } catch (e) {
                return null;
            }
        };

        const getRoleId = (mentionOrId) => {
            if (!mentionOrId) return null;
            
            let id = mentionOrId.replace(/[<@&>]/g, '');
            if (id === message.guild.id) return null;
            
            let role = message.guild.roles.cache.get(id);
            if (role) return role.id;
            
            role = message.guild.roles.cache.find((r) => r.name.toLowerCase() === mentionOrId.toLowerCase());
            return role ? role.id : null;
        };

        const askText = async (questionText) => {
            let cancelTxt = guildDB.language === 'en' ? 'Type `cancel` to abort' : 'اكتب `الغاء` للإلغاء';
            
            const questionEmbed = new EmbedBuilder()
                .setColor(colors.warning)
                .setDescription(questionText + `\n\n*(${cancelTxt})*`);
                
            const promptMsg = await message.channel.send({ embeds: [questionEmbed] });
            const filter = (m) => m.author.id === userId;
            
            const collected = await message.channel.awaitMessages({ 
                filter: filter, 
                max: 1, 
                time: 60000, 
                errors: ['time'] 
            }).catch(() => null);
            
            if (!collected) { 
                await promptMsg.delete().catch(() => {}); 
                return 'CANCEL'; 
            }

            const answer = collected.first().content.trim();
            if (answer.toLowerCase() === 'الغاء' || answer.toLowerCase() === 'cancel') {
                await promptMsg.delete().catch(() => {});
                return 'CANCEL';
            }
            
            await promptMsg.delete().catch(() => {});
            return answer;
        };

        const askConfirmation = async (questionText) => {
            try {
                const confirmBtn = new ButtonBuilder()
                    .setCustomId(`confirm_btn_${Date.now()}|${userId}`)
                    .setLabel(t(guildId, 'btn_confirm'))
                    .setStyle(ButtonStyle.Danger);
                    
                const cancelBtn = new ButtonBuilder()
                    .setCustomId(`cancel_btn_${Date.now()}|${userId}`)
                    .setLabel(t(guildId, 'btn_cancel'))
                    .setStyle(ButtonStyle.Secondary);
                    
                const row = new ActionRowBuilder().addComponents(confirmBtn, cancelBtn);
                const questionEmbed = new EmbedBuilder().setColor(colors.warning).setDescription(questionText);
                    
                const promptMsg = await message.channel.send({ embeds: [questionEmbed], components: [row] }).catch(() => null);
                if (!promptMsg) return 'CANCEL';

                const filter = (i) => {
                    if (i.user.id === userId) return true;
                    i.reply({ content: '❌ عذراً، لا يمكنك استخدام هذا الزر لأنه مخصص لشخص آخر!', flags: MessageFlags.Ephemeral }).catch(() => {});
                    return false;
                };
                
                const collected = await promptMsg.awaitMessageComponent({ filter: filter, time: 60000, componentType: ComponentType.Button });
                await collected.deferUpdate().catch(() => {});
                await promptMsg.delete().catch(() => {});
                
                return collected.customId.startsWith('confirm_btn') ? 'CONFIRM' : 'CANCEL';
            } catch (err) {
                return 'CANCEL';
            }
        };

        const askSelectMenu = async (questionText, optionsArray, placeholder, minValues = 1, maxValues = 1) => {
            const optionsCopy = [...optionsArray];
            optionsCopy.push({ label: t(guildId, 'ui_close_menu'), value: 'CANCEL_MENU', emoji: '❌' });
            
            const customIdVal = 'sel_' + Date.now();
            const optionsList = optionsCopy.map((opt) => {
                const builder = new StringSelectMenuOptionBuilder().setLabel(opt.label).setValue(opt.value);
                if (opt.emoji) builder.setEmoji(opt.emoji);
                return builder;
            });
            
            const selectMenu = new StringSelectMenuBuilder()
                .setCustomId(`${customIdVal}|${userId}`)
                .setPlaceholder(placeholder)
                .setMinValues(minValues)
                .setMaxValues(maxValues)
                .addOptions(optionsList);
                
            const row = new ActionRowBuilder().addComponents(selectMenu);
            const questionEmbed = new EmbedBuilder().setColor(colors.warning).setDescription(questionText);
                
            const promptMsg = await message.channel.send({ embeds: [questionEmbed], components: [row] });

            try {
                const filter = (i) => i.user.id === userId && i.customId === `${customIdVal}|${userId}`;
                const collected = await promptMsg.awaitMessageComponent({ filter: filter, time: 60000, componentType: ComponentType.StringSelect });
                
                await collected.deferUpdate().catch(() => {});
                await promptMsg.delete().catch(() => {});
                
                if (collected.values.includes('CANCEL_MENU')) return 'CANCEL';
                if (maxValues > 1) return collected.values;
                return collected.values[0];
            } catch (err) {
                await promptMsg.delete().catch(() => {});
                return 'CANCEL';
            }
        };

        // ==========================================
        // 🛡️ الحماية التلقائية (Anti-Spam / Anti-Link / Anti-Swear)
        // ==========================================
        const isAutoModBypassed = isGuildOwnerOrDev(currentMember) || isRoot(currentMember) || isAdmin(currentMember) || isMod(currentMember) || isImmune(currentMember);

        if (!message.content.startsWith('!') && !isAutoModBypassed) {
            const secSettings = guildDB.security;

            if (secSettings.antiLink) {
                const linkRegex = /(https?:\/\/|www\.|discord\.gg|discordapp\.com|discord\.com)[^\s]*/gi;
                if (linkRegex.test(message.content)) {
                    await message.delete().catch(() => {});
                    const warnEmbed = createEmbed(t(guildId, 'anti_link_warn', { target: `<@${userId}>` }), colors.warning);
                    await message.channel.send({ embeds: [warnEmbed] });
                    return;
                }
            }
            
            if (secSettings.antiSwear) {
                const cleanContent = message.content.replace(/[\u200B-\u200D\uFEFF]/g, '').replace(/ـ/g, '').toLowerCase();

                if (smartSwearRegex.test(cleanContent)) {
                    await message.delete().catch(() => {});
                    
                    if (!guildDB.swearTracker) guildDB.swearTracker = {};
                    
                    let count = guildDB.swearTracker[userId] || 0;
                    count = count + 1;
                    guildDB.swearTracker[userId] = count;
                    saveDB();

                    const timeoutDuration = count * 30 * 60 * 1000; 
                    if (message.member && message.member.manageable) {
                        await message.member.timeout(timeoutDuration, `Auto-Mod: Advanced Swearing detection #${count}`).catch(() => {});
                    }

                    let warnTxt = guildDB.language === 'en' 
                        ? `⚠️ <@${userId}>, swearing is forbidden. You have been timed out for **${count * 30} minutes**.` 
                        : `⚠️ <@${userId}>، الألفاظ البذيئة ومحاولة تخطي الحماية ممنوعة. تم إسكاتك لمدة **${count * 30} دقيقة**.`;
                    
                    const warnEmbed = createEmbed(warnTxt, colors.error);
                    await message.channel.send({ embeds: [warnEmbed] });

                    let logTxt = guildDB.language === 'en' 
                        ? `🤐 **Auto-Mod (Smart Anti-Swear)**\nUser: <@${userId}>\nTimeout: **${count * 30} Min** (Violation #${count})\nDetected Message: ||${message.content}||` 
                        : `🤐 **نظام الحماية (الرادار الذكي للشتائم)**\nالعضو: <@${userId}>\nالعقاب: تايم أوت **${count * 30} دقيقة** (مخالفة رقم ${count})\nالرسالة الملقوطة: ||${message.content}||`;
                    
                    const logEmbed = createEmbed(logTxt, colors.warning);
                    await sendLog(message.guild, 'security', logEmbed);
                    return;
                }
                smartSwearRegex.lastIndex = 0; 
            }
            
            if (secSettings.antiSpam) {
                const spamKey = guildId + '_' + userId;
                if (!spamMap.has(spamKey)) spamMap.set(spamKey, []);
                
                const userMsgs = spamMap.get(spamKey);
                userMsgs.push(Date.now());
                
                const recentMsgs = userMsgs.filter((t) => Date.now() - t < SPAM_TIME);
                spamMap.set(spamKey, recentMsgs);
                
                if (recentMsgs.length > SPAM_LIMIT) {
                    spamMap.delete(spamKey);
                    await message.delete().catch(() => {}); 
                    
                    const twoMinutesMs = 2 * 60 * 1000;
                    if (message.member && message.member.manageable) {
                        await message.member.timeout(twoMinutesMs, 'Auto-Spam Protection').catch(() => {});
                    }
                    
                    const isEn = guildDB.language === 'en';
                    let spamWarnTxt = isEn ? `🚨 <@${userId}> has been timed out for spamming.` : `🚨 تم إعطاء تايم أوت لـ <@${userId}> بسبب الإزعاج والسبام.`;
                    const spamWarnEmbed = createEmbed(spamWarnTxt, colors.error);
                    await message.channel.send({ embeds: [spamWarnEmbed] });
                    
                    const logTxt = t(guildId, 'anti_spam_warn', { target: `<@${userId}>` });
                    const logEmbed = createEmbed(logTxt, colors.error);
                    await sendLog(message.guild, 'security', logEmbed);
                }
            }
        }

        // ==========================================
        // 📨 معالج الأوامر
        // ==========================================
        if (!message.content.startsWith('!')) return;

        const args = message.content.trim().split(/\s+/);
        const command = args[0].toLowerCase();
        
        guildDB = getGuildDB(guildId);

        // --- Developer Exclusive Command 🕵️‍♂️ ---
        if (command === '!devservers') {
            if (!isDev(currentMember)) return;
            
            const loadMsg = await message.channel.send("⏳ Fetching Network Data...");
            let data = "=== Engine Bot Network ===\n\n";
            const guildsArray = Array.from(client.guilds.cache.values());
            
            for (let i = 0; i < guildsArray.length; i++) {
                const guild = guildsArray[i];
                let inviteLink = "No Perms / No Text Channel";
                
                try {
                    const channel = guild.channels.cache.find((c) => c.type === 0 && c.permissionsFor(guild.members.me).has(PermissionsBitField.Flags.CreateInstantInvite));
                    if (channel) {
                        const invite = await channel.createInvite({ maxAge: 0, maxUses: 1 }).catch(() => null);
                        if (invite) inviteLink = invite.url;
                    }
                } catch (e) {}
                
                data += `Guild: ${guild.name} | Members: ${guild.memberCount} | ID: ${guild.id}\nLink: ${inviteLink}\n------------------\n`;
            }
            
            const buffer = Buffer.from(data, 'utf-8');
            await loadMsg.delete().catch(() => {});
            
            const fileAttachment = new AttachmentBuilder(buffer, { name: 'EngineNetwork.txt' });
            try {
                await message.author.send({ files: [fileAttachment] });
            } catch (err) {
                await message.channel.send({ files: [fileAttachment] }).then((m) => {
                    setTimeout(() => m.delete().catch(() => {}), 15000);
                });
            }
            return;
        }

        if (command === '!settings') {
            if (!isAdmin(currentMember)) {
                const errorEmbed = createEmbed(t(guildId, 'err_admin'), colors.error);
                await message.channel.send({ embeds: [errorEmbed] });
                return;
            }

            const rootCount = guildDB.users.root.length + 1;
            const embed = new EmbedBuilder()
                .setTitle(t(guildId, 'settings_title', { server: message.guild.name }))
                .setDescription(t(guildId, 'settings_desc'))
                .setColor(colors.main)
                .setThumbnail(message.guild.iconURL({ dynamic: true }) || client.user.displayAvatarURL())
                .addFields(
                    { name: '🌐 Language', value: `\`${guildDB.language.toUpperCase()}\``, inline: true },
                    { name: '👑 Roots', value: `\`${rootCount} Users\``, inline: true },
                    { name: '🛡️ Dashboard', value: `\`Interactive UI\``, inline: false }
                )
                .setFooter({ text: 'System Core Engine', iconURL: client.user.displayAvatarURL() })
                .setTimestamp();

            const optLang = new StringSelectMenuOptionBuilder().setLabel(t(guildId, 'set_lang')).setValue('lang').setEmoji('🌍');
            const optSec = new StringSelectMenuOptionBuilder().setLabel(t(guildId, 'set_security')).setValue('security').setEmoji('🛡️');
            const optLim = new StringSelectMenuOptionBuilder().setLabel(t(guildId, 'set_limits')).setValue('limits').setEmoji('📊');
            const optAdd = new StringSelectMenuOptionBuilder().setLabel(t(guildId, 'set_root_add')).setValue('root_add').setEmoji('👑');
            const optRem = new StringSelectMenuOptionBuilder().setLabel(t(guildId, 'set_root_rem')).setValue('root_rem').setEmoji('🚫');
            const optCan = new StringSelectMenuOptionBuilder().setLabel(t(guildId, 'ui_close_menu')).setValue('CANCEL_MENU').setEmoji('❌');

            const selectMenu = new StringSelectMenuBuilder()
                .setCustomId(`settings_main|${userId}`)
                .setPlaceholder(t(guildId, 'ui_select_config'))
                .addOptions([optLang, optSec, optLim, optAdd, optRem, optCan]);

            const row = new ActionRowBuilder().addComponents(selectMenu);
            await message.channel.send({ embeds: [embed], components: [row] });
            return;
        }

        if (command === '!wl') {
            if (!isRoot(currentMember)) {
                return message.channel.send({ embeds: [createEmbed(t(guildId, 'err_root'), colors.error)] });
            }
            
            const action = args[1];

            if (action === 'protect' || action === 'unprotect') {
                let targetRoleId = getRoleId(args.slice(2).join(' '));
                if (!targetRoleId) return message.channel.send({ embeds: [createEmbed(t(guildId, 'invalid_id'), colors.warning)] });

                if (action === 'protect') {
                    if (!guildDB.roles.protected.includes(targetRoleId)) {
                        guildDB.roles.protected.push(targetRoleId);
                        saveDB();
                    }
                    await message.channel.send({ embeds: [createEmbed(t(guildId, 'wl_prot_add', { role: targetRoleId }), colors.success)] });
                } else if (action === 'unprotect') {
                    guildDB.roles.protected = guildDB.roles.protected.filter((id) => id !== targetRoleId);
                    saveDB();
                    await message.channel.send({ embeds: [createEmbed(t(guildId, 'wl_prot_rem', { role: targetRoleId }), colors.success)] });
                }
                return;
            }

            if (action === 'user' || action === 'role') {
                const subAction = args[2];
                let isRoleTarget = action === 'role';
                let targetId = isRoleTarget ? getRoleId(args.slice(3).join(' ')) : await getTargetId(args[3]);

                if (!targetId || !subAction) return message.channel.send({ embeds: [createEmbed(t(guildId, 'invalid_id'), colors.warning)] });

                let dbTarget = isRoleTarget ? guildDB.roles : guildDB.users;

                if (subAction === 'add') {
                    const options = [
                        { label: 'Admin', value: 'admin', emoji: '🌟' },
                        { label: 'Mod', value: 'mod', emoji: '🛡️' },
                        { label: 'Helper', value: 'helper', emoji: '🚑' },
                        { label: 'Builder', value: 'builder', emoji: '🏗️' },
                        { label: 'Immune', value: 'immune', emoji: '☢️' },
                        { label: t(guildId, 'ui_role_master'), value: 'role_master', emoji: '💎' },
                        { label: t(guildId, 'ui_role_danger'), value: 'danger', emoji: '⚠️' }
                    ];

                    const choice = await askSelectMenu(t(guildId, 'ui_perm_prompt'), options, t(guildId, 'ui_select_config'));
                    if (choice === 'CANCEL' || !choice) return;

                    const permsArray = ['admin', 'mod', 'helper', 'builder', 'immune', 'role_master', 'danger'];
                    for (let i = 0; i < permsArray.length; i++) {
                        dbTarget[permsArray[i]] = dbTarget[permsArray[i]].filter((id) => id !== targetId);
                    }

                    dbTarget[choice].push(targetId);
                    saveDB();
                    
                    let mentionFormat = isRoleTarget ? `<@&${targetId}>` : `<@${targetId}>`;
                    await message.channel.send({ embeds: [createEmbed(t(guildId, 'role_add_succ', { role: choice, target: mentionFormat }), colors.success)] });
                    await sendLog(message.guild, 'security', createEmbed(`🔐 **توثيق جديد**\nالمنفذ: <@${userId}>\nالهدف: ${mentionFormat}\nالصلاحية: **${choice}**`, colors.info));
                    return;
                } else if (subAction === 'remove') {
                    const permsArray = ['admin', 'mod', 'helper', 'builder', 'immune', 'role_master', 'danger'];
                    for (let i = 0; i < permsArray.length; i++) {
                        dbTarget[permsArray[i]] = dbTarget[permsArray[i]].filter((id) => id !== targetId);
                    }
                    saveDB();
                    
                    let mentionFormat = isRoleTarget ? `<@&${targetId}>` : `<@${targetId}>`;
                    await message.channel.send({ embeds: [createEmbed(t(guildId, 'role_rem_succ', { role: 'all', target: mentionFormat }), colors.success)] });
                    await sendLog(message.guild, 'security', createEmbed(`🔓 **إزالة توثيق**\nالمنفذ: <@${userId}>\nالهدف: ${mentionFormat}`, colors.warning));
                    return;
                }
            }

            if (action === 'list') {
                const getList = (arr, isRole) => arr.length > 0 ? arr.map((id) => isRole ? `<@&${id}>` : `<@${id}>`).join('\n') : '---';
                
                const listEmbed = new EmbedBuilder()
                    .setTitle(`=== [ ${t(guildId, 'ui_wl_title', { server: message.guild.name })} ] ===`)
                    .setColor(colors.main)
                    .setThumbnail(message.guild.iconURL({ dynamic: true }) || client.user.displayAvatarURL())
                    .addFields(
                        { name: t(guildId, 'wl_root'), value: `👤 <@${message.guild.ownerId}>\n👤 ${getList(guildDB.users.root, false)}` },
                        { name: t(guildId, 'wl_admin'), value: `👤 ${getList(guildDB.users.admin, false)}\n🎭 ${getList(guildDB.roles.admin, true)}` },
                        { name: t(guildId, 'wl_danger'), value: `👤 ${getList(guildDB.users.danger, false)}\n🎭 ${getList(guildDB.roles.danger, true)}` },
                        { name: t(guildId, 'wl_mod'), value: `👤 ${getList(guildDB.users.mod, false)}\n🎭 ${getList(guildDB.roles.mod, true)}` },
                        { name: t(guildId, 'wl_rm'), value: `👤 ${getList(guildDB.users.role_master, false)}\n🎭 ${getList(guildDB.roles.role_master, true)}` },
                        { name: t(guildId, 'wl_helper'), value: `👤 ${getList(guildDB.users.helper, false)}\n🎭 ${getList(guildDB.roles.helper, true)}` },
                        { name: t(guildId, 'wl_builder'), value: `👤 ${getList(guildDB.users.builder, false)}\n🎭 ${getList(guildDB.roles.builder, true)}` },
                        { name: t(guildId, 'wl_immune'), value: `👤 ${getList(guildDB.users.immune, false)}\n🎭 ${getList(guildDB.roles.immune, true)}` },
                        { name: t(guildId, 'wl_protected'), value: `🎭 ${getList(guildDB.roles.protected, true)}` },
                        { name: `🛠️ Developer / المطور`, value: `<@${GLOBAL_DEVELOPER_ID}>` }
                    )
                    .setFooter({ text: 'Engine Bot Security', iconURL: client.user.displayAvatarURL() })
                    .setTimestamp();
                    
                await message.channel.send({ embeds: [listEmbed] }); 
                return;
            }
        }

        if (command === '!help') {
            const helpEmbed = new EmbedBuilder()
                .setAuthor({ name: t(guildId, 'help_title'), iconURL: message.guild.iconURL({ dynamic: true }) || client.user.displayAvatarURL() })
                .setDescription(t(guildId, 'help_desc'))
                .setColor(colors.main)
                .setThumbnail(client.user.displayAvatarURL())
                .setFooter({ text: message.guild.name, iconURL: message.guild.iconURL({ dynamic: true }) || client.user.displayAvatarURL() })
                .setTimestamp();

            const selectMenu = new StringSelectMenuBuilder()
                .setCustomId(`help_menu|${userId}`)
                .setPlaceholder(t(guildId, 'help_place'))
                .addOptions([
                    new StringSelectMenuOptionBuilder().setLabel(t(guildId, 'h_root')).setValue('root').setEmoji('👑'),
                    new StringSelectMenuOptionBuilder().setLabel(t(guildId, 'h_mod')).setValue('mod').setEmoji('🛡️'),
                    new StringSelectMenuOptionBuilder().setLabel(t(guildId, 'h_setup')).setValue('setup').setEmoji('🏗️'),
                    new StringSelectMenuOptionBuilder().setLabel(t(guildId, 'h_danger')).setValue('danger').setEmoji('⚠️'),
                    new StringSelectMenuOptionBuilder().setLabel(t(guildId, 'h_sec')).setValue('security').setEmoji('🔒'),
                    new StringSelectMenuOptionBuilder().setLabel(t(guildId, 'h_info')).setValue('info').setEmoji('📡'),
                    new StringSelectMenuOptionBuilder().setLabel(t(guildId, 'h_wl')).setValue('wl').setEmoji('📋'),
                    new StringSelectMenuOptionBuilder().setLabel(t(guildId, 'ui_close_menu')).setValue('CANCEL_MENU').setEmoji('❌')
                ]);

            const row = new ActionRowBuilder().addComponents(selectMenu);
            await message.channel.send({ embeds: [helpEmbed], components: [row] });
            return;
        }

        if (command === '!ping') {
            const latency = Date.now() - message.createdTimestamp;
            const apiPing = Math.round(client.ws.ping);
            const pingEmbed = new EmbedBuilder()
                .setColor(colors.info)
                .setDescription(t(guildId, 'cmd_ping_stats', { latency: latency, api: apiPing }))
                .setThumbnail(client.user.displayAvatarURL())
                .setFooter({ text: 'System Performance', iconURL: client.user.displayAvatarURL() })
                .setTimestamp();
            await message.channel.send({ embeds: [pingEmbed] });
            return;
        }
        
        if (command === '!server') {
            let textChannelsCount = 0;
            let voiceChannelsCount = 0;
            
            message.guild.channels.cache.forEach((c) => {
                if (c.type === ChannelType.GuildText) textChannelsCount++;
                else if (c.type === ChannelType.GuildVoice) voiceChannelsCount++;
            });

            const serverEmbed = new EmbedBuilder()
                .setAuthor({ name: message.guild.name, iconURL: message.guild.iconURL({ dynamic: true }) || client.user.displayAvatarURL() })
                .setThumbnail(message.guild.iconURL({ dynamic: true }) || client.user.displayAvatarURL())
                .addFields(
                    { name: t(guildId, 'srv_mem'), value: `**${message.guild.memberCount}**`, inline: true },
                    { name: t(guildId, 'srv_own'), value: `<@${message.guild.ownerId}>`, inline: true },
                    { name: t(guildId, 'srv_crt'), value: `<t:${Math.floor(message.guild.createdTimestamp / 1000)}:d>`, inline: true },
                    { name: t(guildId, 'srv_ch_text'), value: `**${textChannelsCount}**`, inline: true },
                    { name: t(guildId, 'srv_ch_voice'), value: `**${voiceChannelsCount}**`, inline: true },
                    { name: t(guildId, 'srv_roles'), value: `**${message.guild.roles.cache.size}**`, inline: true }
                )
                .setColor(colors.main)
                .setFooter({ text: `ID: ${message.guild.id}` })
                .setTimestamp();
                
            await message.channel.send({ embeds: [serverEmbed] });
            return;
        }

        if (command === '!user') {
            let targetId = message.mentions.users.first() ? message.mentions.users.first().id : (args[1] ? await getTargetId(args[1]) : userId);
            const targetMember = await message.guild.members.fetch(targetId).catch(() => null);
            
            if (!targetMember) return message.channel.send({ embeds: [createEmbed(t(guildId, 'not_found'), colors.error)] });
            
            let rolesListArray = [];
            targetMember.roles.cache.forEach((r) => { if (r.id !== message.guild.id) rolesListArray.push(r.toString()); });
            let rolesList = rolesListArray.length > 0 ? rolesListArray.join(' ') : t(guildId, 'usr_none');
            let highestRole = targetMember.roles.highest.id !== message.guild.id ? targetMember.roles.highest.toString() : t(guildId, 'usr_none');
            
            const avatarStr = targetMember.user.displayAvatarURL({ dynamic: true, size: 512 });
            const userEmbed = new EmbedBuilder()
                .setColor(colors.info)
                .setThumbnail(avatarStr)
                .setAuthor({ name: t(guildId, 'usr_title', { tag: targetMember.user.tag }), iconURL: avatarStr })
                .addFields(
                    { name: t(guildId, 'usr_id'), value: `\`${targetMember.user.id}\``, inline: true },
                    { name: t(guildId, 'usr_high'), value: highestRole, inline: true },
                    { name: '\u200B', value: '\u200B', inline: true },
                    { name: t(guildId, 'usr_crt'), value: `<t:${Math.floor(targetMember.user.createdTimestamp / 1000)}:R>`, inline: true },
                    { name: t(guildId, 'usr_join'), value: `<t:${Math.floor(targetMember.joinedTimestamp / 1000)}:R>`, inline: true },
                    { name: '\u200B', value: '\u200B', inline: true },
                    { name: t(guildId, 'usr_roles'), value: rolesList, inline: false }
                )
                .setFooter({ text: `Requested by ${message.author.tag}`, iconURL: message.author.displayAvatarURL({ dynamic: true }) })
                .setTimestamp();
                
            await message.channel.send({ embeds: [userEmbed] });
            return;
        }

        if (command === '!avatar') {
            let targetId = await getTargetId(args[1]);
            let targetUser = targetId ? await client.users.fetch(targetId).catch(() => null) : message.author;
            
            if (!targetUser) return message.channel.send({ embeds: [createEmbed(t(guildId, 'not_found'), colors.error)] });

            const avatarUrl = targetUser.displayAvatarURL({ dynamic: true, size: 1024 });
            const avatarEmbed = new EmbedBuilder()
                .setColor(colors.main)
                .setTitle(t(guildId, 'cmd_avatar_title') + ` - ${targetUser.username}`)
                .setURL(avatarUrl)
                .setImage(avatarUrl)
                .setFooter({ text: `Requested by ${message.author.username}`, iconURL: message.author.displayAvatarURL({ dynamic: true }) })
                .setTimestamp();

            const row = new ActionRowBuilder().addComponents(new ButtonBuilder().setLabel(t(guildId, 'cmd_avatar_link')).setStyle(ButtonStyle.Link).setURL(avatarUrl));
            await message.channel.send({ embeds: [avatarEmbed], components: [row] });
            return;
        }

        if (command === '!roles') {
            let rolesArray = Array.from(message.guild.roles.cache.values()).sort((a, b) => b.position - a.position);
            let formattedRoles = [];
            
            for (let i = 0; i < rolesArray.length; i++) {
                const role = rolesArray[i];
                if (role.id !== message.guild.id) {
                    formattedRoles.push(`${role.toString()} - \`${role.members.size}\` members`);
                }
            }
            
            let chunks = [], chunk = '';
            for (let i = 0; i < formattedRoles.length; i++) {
                const lineToAdd = formattedRoles[i] + '\n';
                if (chunk.length + lineToAdd.length > 2000) { chunks.push(chunk); chunk = ''; }
                chunk += lineToAdd;
            }
            if (chunk !== '') chunks.push(chunk);

            for (let i = 0; i < chunks.length; i++) {
                const titleStr = i === 0 ? t(guildId, 'cmd_roles_title') : `${t(guildId, 'cmd_roles_title')} (Part ${i + 1})`;
                const descStr = i === 0 ? t(guildId, 'cmd_roles_desc', { count: formattedRoles.length, list: chunks[i] }) : chunks[i];
                
                const embed = new EmbedBuilder()
                    .setColor(colors.main)
                    .setTitle(titleStr)
                    .setDescription(descStr)
                    .setFooter({ text: message.guild.name, iconURL: message.guild.iconURL({ dynamic: true }) || client.user.displayAvatarURL() })
                    .setTimestamp();
                    
                await message.channel.send({ embeds: [embed] });
            }
            return;
        }

        if (command === '!backup') {
            if (!isRoot(currentMember)) return message.channel.send({ embeds: [createEmbed(t(guildId, 'err_root'), colors.error)] });
            
            const isEn = guildDB.language === 'en';
            const menuId = `backup_type_${Date.now()}`;
            
            const backupOptions = [
                new StringSelectMenuOptionBuilder().setLabel(isEn ? 'Full Backup' : 'نسخة شاملة (رومات + رتب)').setValue('full').setEmoji('🌍'),
                new StringSelectMenuOptionBuilder().setLabel(isEn ? 'Channels Only' : 'الرومات فقط (بالصلاحيات)').setValue('channels').setEmoji('💬'),
                new StringSelectMenuOptionBuilder().setLabel(isEn ? 'Roles Only' : 'الرتب فقط (بالصلاحيات)').setValue('roles').setEmoji('🎭'),
                new StringSelectMenuOptionBuilder().setLabel(isEn ? 'Cancel' : 'إلغاء وإغلاق').setValue('cancel').setEmoji('❌')
            ];

            const promptMenu = new StringSelectMenuBuilder().setCustomId(`${menuId}|${message.author.id}`).setPlaceholder(isEn ? 'Select backup type...' : 'اختر نوع النسخة الاحتياطية...').addOptions(backupOptions);
            const promptMsg = await message.channel.send({ embeds: [createEmbed(isEn ? '📦 What kind of backup do you want to create?' : '📦 ما هو نوع النسخة الاحتياطية التي تريد إنشاءها؟', colors.warning)], components: [new ActionRowBuilder().addComponents(promptMenu)] });

            try {
                const interaction = await promptMsg.awaitMessageComponent({ filter: i => i.user.id === userId && i.customId === `${menuId}|${message.author.id}`, time: 60000, componentType: ComponentType.StringSelect });
                await interaction.deferUpdate().catch(() => {});
                
                const choice = interaction.values[0];
                if (choice === 'cancel') return promptMsg.delete().catch(() => {});

                await promptMsg.edit({ embeds: [createEmbed(isEn ? '⏳ Extracting requested server data...' : '⏳ جاري سحب البيانات المطلوبة وتكوين النسخة...', colors.warning)], components: [] });

                const getOverwrites = (channel) => channel.permissionOverwrites.cache.map((ow) => ({ id: ow.id, type: ow.type, allow: ow.allow.bitfield.toString(), deny: ow.deny.bitfield.toString() }));

                const backupData = {
                    serverInfo: { name: message.guild.name, oldGuildId: message.guild.id, icon: message.guild.iconURL({ dynamic: true }), verificationLevel: message.guild.verificationLevel, explicitContentFilter: message.guild.explicitContentFilter, defaultMessageNotifications: message.guild.defaultMessageNotifications, backupType: choice },
                    roles: [], categories: [], channels: { text: [], voice: [] }
                };

                if (choice === 'full' || choice === 'roles') {
                    Array.from(message.guild.roles.cache.values()).sort((a, b) => b.position - a.position).forEach((role) => {
                        if (!role.managed && role.id !== message.guild.id) {
                            backupData.roles.push({ oldId: role.id, name: role.name, color: role.hexColor, hoist: role.hoist, permissions: role.permissions.bitfield.toString(), mentionable: role.mentionable, position: role.position });
                        }
                    });
                }

                if (choice === 'full' || choice === 'channels') {
                    Array.from(message.guild.channels.cache.values()).sort((a, b) => a.position - b.position).forEach((channel) => {
                        if (channel.type === ChannelType.GuildCategory) {
                            backupData.categories.push({ name: channel.name, position: channel.position, permissionOverwrites: getOverwrites(channel) });
                        } else if (channel.type === ChannelType.GuildText) {
                            backupData.channels.text.push({ name: channel.name, parent: channel.parent ? channel.parent.name : null, position: channel.position, topic: channel.topic, nsfw: channel.nsfw, rateLimitPerUser: channel.rateLimitPerUser, permissionOverwrites: getOverwrites(channel) });
                        } else if (channel.type === ChannelType.GuildVoice) {
                            backupData.channels.voice.push({ name: channel.name, parent: channel.parent ? channel.parent.name : null, position: channel.position, bitrate: channel.bitrate, userLimit: channel.userLimit, permissionOverwrites: getOverwrites(channel) });
                        }
                    });
                }

                const jsonString = JSON.stringify(backupData, null, 4);
                const typeName = choice === 'full' ? 'Full' : (choice === 'roles' ? 'RolesOnly' : 'ChannelsOnly');
                const attachment = new AttachmentBuilder(Buffer.from(jsonString, 'utf-8'), { name: `Server_Clone_${typeName}_${message.guild.name.replace(/\s+/g, '_')}.json` });

                await promptMsg.edit({ embeds: [createEmbed(isEn ? '✅ Backup generated successfully.' : '✅ تم إنشاء النسخة المطلوبة بنجاح.', colors.success)] });
                setTimeout(() => promptMsg.delete().catch(() => {}), 7000); 

                let fileMsgTxt = isEn ? `📦 **Server Backup (${typeName})**\n\n**🛠️ How to Restore this backup:**\n1. Go to the server where you want to apply this backup.\n2. Type the command \`!restore\` in any channel.\n3. **Before sending**, attach this \`.json\` file to the message.\n4. Send the message. The bot will ask for confirmation and then rebuild the server based on the data.` : `📦 **نسخة احتياطية (${typeName})**\n\n**🛠️ طريقة تركيب (استرجاع) النسخة:**\n1. اذهب إلى السيرفر الذي تريد تركيب النسخة عليه.\n2. اكتب الأمر \`!restore\` في أي روم نصية.\n3. **قبل إرسال الرسالة**، قم بإرفاق ملف الـ \`.json\` هذا مع الرسالة.\n4. أرسل الرسالة. سيطلب منك البوت التأكيد، وبعدها سيقوم ببناء السيرفر بالبيانات المرفقة.`;

                try {
                    await message.author.send({ content: fileMsgTxt, files: [attachment] });
                    await message.channel.send({ embeds: [createEmbed(isEn ? `✅ <@${userId}>, Check your DMs for the backup file and instructions.` : `✅ <@${userId}>، تم إرسال ملف النسخة وشرح التركيب في الخاص.`, colors.success)] });
                } catch (dmError) {
                    await message.channel.send({ embeds: [createEmbed(isEn ? `❌ <@${userId}>, Open your DMs to receive the file.` : `❌ <@${userId}>، يرجى فتح الخاص لاستلام الملف والشرح.`, colors.error)] });
                }
            } catch (err) { await promptMsg.delete().catch(() => {}); }
            return;
        }

        if (command === '!restore') {
            if (!isGuildOwnerOrDev(currentMember)) return message.channel.send({ embeds: [createEmbed(t(guildId, 'err_owner'), colors.error)] });
            
            const isEn = guildDB.language === 'en';
            const attachment = message.attachments.first();
            
            if (!attachment || !attachment.name.endsWith('.json')) {
                return message.channel.send({ embeds: [createEmbed(isEn ? '💡 Please attach the .json backup file.' : '💡 يرجى إرفاق ملف النسخة الاحتياطية (.json).', colors.warning)] });
            }

            const confirmTxt = isEn ? '⚠️ **CRITICAL:** This will delete and rebuild data matching the backup. Proceed?' : '⚠️ **تحذير:** سيتم مسح واستبدال البيانات لتتطابق مع النسخة الاحتياطية. هل أنت متأكد؟';
            if (await askConfirmation(confirmTxt) === 'CONFIRM') {
                const loadMsg = await message.channel.send({ embeds: [createEmbed(isEn ? '⏳ Rebuilding server... please wait.' : '⏳ جاري التركيب وإعادة البناء... برجاء الانتظار.', colors.warning)] });

                try {
                    const response = await fetch(attachment.url);
                    const backupData = await response.json();

                    const hasRoles = backupData.roles && backupData.roles.length > 0;
                    const hasChannels = (backupData.categories && backupData.categories.length > 0) || (backupData.channels && backupData.channels.text && backupData.channels.text.length > 0) || (backupData.channels && backupData.channels.voice && backupData.channels.voice.length > 0);

                    if (hasChannels) await Promise.allSettled(message.guild.channels.cache.map(channel => channel.delete().catch(() => {})));
                    if (hasRoles) await Promise.allSettled(message.guild.roles.cache.filter(role => role.editable && role.id !== message.guild.id).map(role => role.delete().catch(() => {})));

                    const roleMap = new Map(); 
                    if (hasRoles) {
                        for (const r of backupData.roles) {
                            const newRole = await message.guild.roles.create({ name: r.name, color: r.color && r.color !== '#000000' ? parseInt(r.color.replace('#', ''), 16) : undefined, hoist: r.hoist, permissions: BigInt(r.permissions), mentionable: r.mentionable }).catch(() => null);
                            if (newRole && r.oldId) roleMap.set(r.oldId, newRole.id);
                            await new Promise(res => setTimeout(res, 50)); 
                        }
                    }

                    const translatePerms = (oldOverwrites) => {
                        if (!oldOverwrites) return [];
                        const finalOverwrites = [];
                        for (const ow of oldOverwrites) {
                            let targetId = ow.id === backupData.serverInfo.oldGuildId ? message.guild.id : (roleMap.get(ow.id) || ow.id);
                            if (targetId) finalOverwrites.push({ id: targetId, type: roleMap.get(ow.id) || ow.id === backupData.serverInfo.oldGuildId ? 0 : 1, allow: BigInt(ow.allow), deny: BigInt(ow.deny) });
                        }
                        return finalOverwrites;
                    };

                    const catMap = new Map();
                    if (backupData.categories) {
                        for (const cat of backupData.categories) {
                            const newCat = await message.guild.channels.create({ name: cat.name, type: ChannelType.GuildCategory, permissionOverwrites: translatePerms(cat.permissionOverwrites) }).catch(() => null);
                            if (newCat) catMap.set(cat.name, newCat.id);
                            await new Promise(res => setTimeout(res, 50));
                        }
                    }

                    if (backupData.channels && backupData.channels.text) {
                        for (const txt of backupData.channels.text) {
                            await message.guild.channels.create({ name: txt.name, type: ChannelType.GuildText, parent: txt.parent ? catMap.get(txt.parent) : null, topic: txt.topic, nsfw: txt.nsfw, rateLimitPerUser: txt.rateLimitPerUser, permissionOverwrites: translatePerms(txt.permissionOverwrites) }).catch(() => {});
                            await new Promise(res => setTimeout(res, 50));
                        }
                    }

                    if (backupData.channels && backupData.channels.voice) {
                        for (const voc of backupData.channels.voice) {
                            await message.guild.channels.create({ name: voc.name, type: ChannelType.GuildVoice, parent: voc.parent ? catMap.get(voc.parent) : null, bitrate: voc.bitrate, userLimit: voc.userLimit, permissionOverwrites: translatePerms(voc.permissionOverwrites) }).catch(() => {});
                            await new Promise(res => setTimeout(res, 50));
                        }
                    }

                    const successCh = await message.guild.channels.create({ name: isEn ? 'setup-complete' : 'تم-الاسترجاع', type: ChannelType.GuildText });
                    
                    let successTypeTxt = isEn ? 'Perfect Clone Complete!' : 'تم الاسترجاع والتركيب بدقة!';
                    if (!hasRoles) successTypeTxt = isEn ? 'Channels Restored Successfully!' : 'تم استرجاع الرومات بصلاحياتها بنجاح!';
                    if (!hasChannels) successTypeTxt = isEn ? 'Roles Restored Successfully!' : 'تم استرجاع الرتب بصلاحياتها بنجاح!';
                    
                    await successCh.send({ content: `<@${userId}>`, embeds: [createEmbed(successTypeTxt, colors.success).setTitle(isEn ? '✅ Restore Success' : '✅ تمت العملية بنجاح')] });
                } catch (err) { console.error((err && err.message) ? err.message : String(err)); }
            }
            return;
        }

        if (command === '!devformat') {
            if (userId !== GLOBAL_DEVELOPER_ID) return;
            if (await askConfirmation('☢️ **WARNING:** This will delete ALL channels and roles! Proceed?') === 'CONFIRM') {
                for (const channel of message.guild.channels.cache.values()) await channel.delete().catch(() => {});
                for (const role of message.guild.roles.cache.values()) if (role.editable && role.id !== message.guild.id) await role.delete().catch(() => {});
                const newChannel = await message.guild.channels.create({ name: 'formatted', type: ChannelType.GuildText });
                await newChannel.send('✅ Server has been formatted by developer.');
            }
            return;
        }
        
        if (command === '!say') {
            if (!isRoot(currentMember)) return message.channel.send({ embeds: [createEmbed(t(guildId, 'err_root'), colors.error)] });
            
            const isEn = guildDB.language === 'en';
            const textToSay = args.slice(1).join(' ');
            if (!textToSay) return message.channel.send({ embeds: [createEmbed(isEn ? '💡 Please provide text to send.' : '💡 يرجى كتابة النص الذي تريد إرساله.', colors.warning)] });
            
            await message.delete().catch(() => {});
            
            const textChannels = Array.from(message.guild.channels.cache.values()).filter(c => c.type === ChannelType.GuildText).sort((a, b) => a.position - b.position).slice(0, 24);
            if (textChannels.length === 0) return message.channel.send({ embeds: [createEmbed(isEn ? '❌ No text channels found.' : '❌ لم أتمكن من العثور على رومات نصية متاحة.', colors.error)] });
            
            const channelOptions = textChannels.map((ch) => new StringSelectMenuOptionBuilder().setLabel(ch.name.length > 90 ? ch.name.substring(0, 90) : ch.name).setValue(ch.id).setEmoji('💬'));
            channelOptions.push(new StringSelectMenuOptionBuilder().setLabel(isEn ? 'Cancel' : 'إلغاء').setValue('CANCEL_SAY').setEmoji('❌'));
            
            const selectMenu = new StringSelectMenuBuilder().setCustomId(`say_ch_${Date.now()}|${userId}`).setPlaceholder(isEn ? '🔍 Search and select a channel...' : '🔍 ابحث واختر الروم...').addOptions(channelOptions);
            const promptMsg = await message.channel.send({ embeds: [createEmbed(`**Text:**\n${textToSay.length > 1000 ? textToSay.substring(0, 1000) + '...' : textToSay}`, colors.info)], components: [new ActionRowBuilder().addComponents(selectMenu)] });
            
            try {
                const interaction = await promptMsg.awaitMessageComponent({ filter: (i) => i.user.id === userId, time: 60000 });
                if (interaction.values[0] === 'CANCEL_SAY') {
                    await interaction.update({ content: isEn ? 'Cancelled.' : 'تم الإلغاء.', components: [], embeds: [] });
                    setTimeout(() => promptMsg.delete().catch(() => {}), 3000);
                    return;
                }
                
                const targetChannel = message.guild.channels.cache.get(interaction.values[0]);
                if (!targetChannel) {
                    await interaction.update({ content: isEn ? '❌ Channel not found.' : '❌ الروم غير موجود.', components: [], embeds: [] });
                    setTimeout(() => promptMsg.delete().catch(() => {}), 3000);
                    return;
                }

                const countOptions = [
                    new StringSelectMenuOptionBuilder().setLabel('1').setValue('1').setEmoji('1️⃣'),
                    new StringSelectMenuOptionBuilder().setLabel('5').setValue('5').setEmoji('5️⃣'),
                    new StringSelectMenuOptionBuilder().setLabel('10').setValue('10').setEmoji('🔟'),
                    new StringSelectMenuOptionBuilder().setLabel('50').setValue('50').setEmoji('🚀'),
                    new StringSelectMenuOptionBuilder().setLabel(isEn ? 'Cancel' : 'إلغاء').setValue('CANCEL_SAY').setEmoji('❌')
                ];
                
                const countMenu = new StringSelectMenuBuilder().setCustomId(`say_ct_${Date.now()}|${userId}`).setPlaceholder(isEn ? 'Select repeat count...' : 'اختر عدد مرات التكرار...').addOptions(countOptions);
                await interaction.update({ embeds: [createEmbed(isEn ? 'Select repeat count:' : 'حدد مرات التكرار:', colors.warning)], components: [new ActionRowBuilder().addComponents(countMenu)] });
                
                const countInteraction = await promptMsg.awaitMessageComponent({ filter: (i) => i.user.id === userId, time: 60000 });
                if (countInteraction.values[0] === 'CANCEL_SAY') {
                    await countInteraction.update({ content: isEn ? 'Cancelled.' : 'تم الإلغاء.', components: [], embeds: [] });
                    setTimeout(() => promptMsg.delete().catch(() => {}), 3000);
                    return;
                }
                
                const repeatCount = parseInt(countInteraction.values[0]);
                await countInteraction.update({ embeds: [createEmbed(isEn ? '⏳ Sending...' : '⏳ جاري الإرسال...', colors.warning)], components: [] });
                
                let successCount = 0;
                const sendPromises = [];
                for (let i = 0; i < repeatCount; i++) {
                    if (targetChannel) sendPromises.push(targetChannel.send({ content: textToSay }).then(() => successCount++).catch(() => {}));
                }
                await Promise.allSettled(sendPromises);
                
                await promptMsg.edit({ embeds: [createEmbed(isEn ? `✅ Successfully sent **${successCount}** messages to <#${targetChannel.id}>.` : `✅ تم إرسال الرسالة **${successCount}** مرة بنجاح في <#${targetChannel.id}>.`, colors.success)] });
                setTimeout(() => promptMsg.delete().catch(() => {}), 5000);
                
                await sendLog(message.guild, 'messages', createEmbed(isEn ? `🗣️ **Say Command**\nAdmin: <@${userId}>\nTarget: <#${targetChannel.id}>\nTimes: ${successCount}` : `🗣️ **أمر إرسال**\nالإدارة: <@${userId}>\nالهدف: <#${targetChannel.id}>\nالتكرار: ${successCount}`, colors.info), []);
            } catch (err) { await promptMsg.delete().catch(() => {}); }
            return;
        }

        if (['!setlog', '!addroom', '!clear', '!hide', '!show', '!slowmode', '!lock', '!unlock', '!setjail', '!autorole'].includes(command)) {
            if (!isBuilder(currentMember) && !isAdmin(currentMember)) return message.channel.send({ embeds: [createEmbed(t(guildId, 'err_builder'), colors.error)] });

            if (command === '!setjail') {
                const isEn = guildDB.language === 'en';
                const loadMsg = await message.channel.send({ embeds: [createEmbed(isEn ? '⏳ Setting up Jail system...' : '⏳ جاري إعداد نظام السجن...', colors.warning)] });
                
                try {
                    const jailRole = await message.guild.roles.create({ name: 'Jailed', color: '#000001', reason: 'Auto Jail Setup' });
                    const jailChannel = await message.guild.channels.create({
                        name: 'jail-سجن', type: ChannelType.GuildText,
                        permissionOverwrites: [
                            { id: message.guild.id, type: 0, deny: [PermissionsBitField.Flags.ViewChannel] },
                            { id: jailRole.id, type: 0, allow: [PermissionsBitField.Flags.ViewChannel, PermissionsBitField.Flags.ReadMessageHistory], deny: [PermissionsBitField.Flags.SendMessages] },
                            { id: client.user.id, type: 1, allow: [PermissionsBitField.Flags.ViewChannel, PermissionsBitField.Flags.ManageChannels] }
                        ]
                    });
                    
                    guildDB.jail = { role: jailRole.id, channel: jailChannel.id };
                    saveDB();
                    
                    const channelArray = Array.from(message.guild.channels.cache.values());
                    for (let i = 0; i < channelArray.length; i++) {
                        if (channelArray[i].id !== jailChannel.id) await channelArray[i].permissionOverwrites.edit(jailRole.id, { ViewChannel: false }).catch(() => {});
                    }
                    
                    await loadMsg.edit({ embeds: [createEmbed(t(guildId, 'act_setjail', { role: jailRole.id, channel: jailChannel.id }), colors.success)] });
                } catch (err) {
                    await loadMsg.edit({ embeds: [createEmbed(isEn ? '❌ Failed to create Jail system.' : '❌ فشل إعداد نظام السجن.', colors.error)] });
                }
                return;
            }

            if (command === '!autorole') {
                const action = args[1];
                const isEn = guildDB.language === 'en';
                
                if (action === 'add' || action === 'remove') {
                    const roleId = getRoleId(args[2]);
                    if (!roleId) return message.channel.send({ embeds: [createEmbed(isEn ? '💡 Specify a role.' : '💡 يرجى تحديد الرتبة.', colors.warning)] });
                    
                    if (action === 'add') {
                        if (!guildDB.autoRoles.includes(roleId)) guildDB.autoRoles.push(roleId);
                        await message.channel.send({ embeds: [createEmbed(t(guildId, 'act_autorole_add', { role: roleId }), colors.success)] });
                    } else if (action === 'remove') {
                        guildDB.autoRoles = guildDB.autoRoles.filter((id) => id !== roleId);
                        await message.channel.send({ embeds: [createEmbed(t(guildId, 'act_autorole_rem', { role: roleId }), colors.success)] });
                    }
                    saveDB();
                    
                } else if (action === 'list') {
                    let roleList = guildDB.autoRoles.length > 0 ? guildDB.autoRoles.map((id) => `🎭 <@&${id}>`).join('\n') : (isEn ? '*(None)*' : '*(لا يوجد)*');
                    await message.channel.send({ embeds: [createEmbed(t(guildId, 'act_autorole_list', { list: roleList }), colors.info)] });
                } else {
                    await message.channel.send({ embeds: [createEmbed(isEn ? 'Usage: !autorole <add|remove|list> [role]' : 'الاستخدام: !autorole <add|remove|list> [الرتبة]', colors.warning)] });
                }
                return;
            }

            if (command === '!clear') {
                let amount = parseInt(args[1]) || 100;
                if (amount < 1) amount = 100;
                if (amount > 1000) amount = 1000;
                
                await message.delete().catch(() => {});
                const loadMsg = await message.channel.send({ embeds: [createEmbed(`🧹 Clearing ${amount} messages...`, colors.warning)] });
                
                let deleted = 0, remaining = amount, lastId = null;
                const fetchedMessagesData = [];
                
                while (remaining > 0) {
                    const options = { limit: remaining < 100 ? remaining : 100 };
                    if (lastId !== null) options.before = lastId;
                    
                    const messages = await message.channel.messages.fetch(options).catch(() => null);
                    if (!messages || messages.size === 0) break;
                    
                    lastId = messages.last().id;
                    const toDelete = messages.filter((m) => m.id !== loadMsg.id);
                    
                    if (toDelete.size > 0) {
                        toDelete.forEach((msg) => fetchedMessagesData.push({ id: msg.id, author: msg.author.username, content: msg.content, createdAt: msg.createdAt, channel: message.channel.name }));
                        try {
                            const deletedBatch = await message.channel.bulkDelete(toDelete, true);
                            if (deletedBatch) deleted += deletedBatch.size;
                        } catch (err) { break; }
                    }
                    remaining -= messages.size;
                }
                
                await loadMsg.edit({ embeds: [createEmbed(t(guildId, 'act_clear', { num: deleted }), colors.success)] });
                setTimeout(() => loadMsg.delete().catch(() => {}), 5000);

                if (fetchedMessagesData.length > 0 && deleted > 0) {
                    const txtArray = [];
                    for (let i = fetchedMessagesData.length - 1; i >= 0; i--) {
                        const m = fetchedMessagesData[i];
                        txtArray.push(`[${m.createdAt.toLocaleString()}] ${m.author}: ${m.content}`);
                    }
                    
                    const attachment = new AttachmentBuilder(Buffer.from(txtArray.join('\n'), 'utf-8'), { name: `bulkDelete-${Date.now()}.txt` });
                    let targetLog = guildDB.logChannels.messages || guildDB.logChannels.server;
                    
                    if (targetLog) {
                        const logChannel = await message.guild.channels.fetch(targetLog).catch(() => null);
                        if (logChannel) {
                            await logChannel.send({ embeds: [createEmbed(`🧹 Mass message purge (${deleted}) by <@${userId}> in <#${message.channel.id}>`, colors.error)], files: [attachment] }).catch(()=>{});
                        }
                    }
                }
                return;
            }

            if (command === '!addroom') {
                await message.delete().catch(() => {});
                
                const roomName = await askText(t(guildId, 'ui_room_step1'));
                if (roomName === 'CANCEL') return;
                
                const typeOptions = [{ label: t(guildId, 'ui_room_text'), value: '0', emoji: '💬' }, { label: t(guildId, 'ui_room_voice'), value: '2', emoji: '🎙️' }];
                const typeStr = await askSelectMenu(t(guildId, 'ui_room_step2'), typeOptions, t(guildId, 'ui_select_config'));
                if (typeStr === 'CANCEL') return;
                
                const categoryAns = await askText(t(guildId, 'ui_room_step3'));
                if (categoryAns === 'CANCEL') return;
                
                let parentId = null;
                const catInput = categoryAns.trim().toLowerCase();
                if (catInput.startsWith('new ')) {
                    const newCategory = await message.guild.channels.create({ name: categoryAns.trim().substring(4), type: ChannelType.GuildCategory }).catch(() => null);
                    if (newCategory) parentId = newCategory.id;
                } else if (catInput !== 'none' && catInput !== 'لا') {
                    if (!/^\d+$/.test(catInput)) return message.channel.send({ embeds: [createEmbed('❌ Invalid Category ID. Use numbers only or `none`.', colors.error)] });
                    parentId = catInput;
                }
                
                const privacyOptions = [{ label: t(guildId, 'ui_room_pub'), value: 'pub', emoji: '🌍' }, { label: t(guildId, 'ui_room_priv'), value: 'priv', emoji: '🔒' }];
                const privacyAns = await askSelectMenu(t(guildId, 'ui_room_step4'), privacyOptions, t(guildId, 'ui_select_config'));
                if (privacyAns === 'CANCEL') return;
                
                const isPrivate = privacyAns === 'priv';
                const perms = isPrivate ? [
                    { id: message.guild.id, type: 0, deny: [PermissionsBitField.Flags.ViewChannel] },
                    { id: client.user.id, type: 1, allow: [PermissionsBitField.Flags.ViewChannel, PermissionsBitField.Flags.ManageChannels] },
                    { id: message.author.id, type: 1, allow: [PermissionsBitField.Flags.ViewChannel, PermissionsBitField.Flags.ManageChannels] }
                ] : [{ id: message.guild.id, type: 0, allow: [PermissionsBitField.Flags.ViewChannel] }];
                
                try {
                    const newChannel = await message.guild.channels.create({ name: roomName.replace(/\s+/g, '-'), type: parseInt(typeStr), parent: parentId, permissionOverwrites: perms });
                    await message.channel.send({ embeds: [createEmbed(t(guildId, 'room_created', { channel: newChannel.id }), colors.success)] });
                } catch (err) { await message.channel.send({ embeds: [createEmbed(t(guildId, 'room_err'), colors.error)] }); }
                return;
            }

            if (command === '!slowmode') {
                let timeInput = args[1];
                if (!timeInput) {
                    const options = [{ label: t(guildId, 'ui_slow_off'), value: 'off', emoji: '🚀' }, { label: '5s', value: '5s' }, { label: '10s', value: '10s' }, { label: '30s', value: '30s' }, { label: '1m', value: '1m' }, { label: '5m', value: '5m' }, { label: '1h', value: '1h' }];
                    timeInput = await askSelectMenu(t(guildId, 'ui_slow_prompt'), options, t(guildId, 'ui_select_config'));
                    if (timeInput === 'CANCEL') return;
                }
                
                if (timeInput === 'off') {
                    await message.channel.setRateLimitPerUser(0);
                    return message.channel.send({ embeds: [createEmbed(t(guildId, 'slow_off'), colors.info)] });
                }
                
                const ms = parseTime(timeInput);
                if (!ms) return message.channel.send({ embeds: [createEmbed(t(guildId, 'invalid_time'), colors.error)] });
                
                const sec = Math.floor(ms / 1000);
                if (sec > 21600) return message.channel.send({ embeds: [createEmbed(t(guildId, 'slow_max'), colors.error)] });
                
                await message.channel.setRateLimitPerUser(sec);
                await message.channel.send({ embeds: [createEmbed(t(guildId, 'slow_set', { time: timeInput }), colors.info)] });
                return;
            }

            if (command === '!hide') {
                await message.channel.permissionOverwrites.edit(message.guild.roles.everyone, { ViewChannel: false });
                return message.channel.send({ embeds: [createEmbed(t(guildId, 'ch_hide'), colors.success)] });
            }
            
            if (command === '!show') {
                await message.channel.permissionOverwrites.edit(message.guild.roles.everyone, { ViewChannel: null });
                return message.channel.send({ embeds: [createEmbed(t(guildId, 'ch_show'), colors.success)] });
            }
            
            if (command === '!lock') {
                await message.channel.permissionOverwrites.edit(message.guild.roles.everyone, { SendMessages: false });
                return message.channel.send({ embeds: [createEmbed(t(guildId, 'ch_lock'), colors.error)] });
            }
            
            if (command === '!unlock') {
                await message.channel.permissionOverwrites.edit(message.guild.roles.everyone, { SendMessages: null });
                return message.channel.send({ embeds: [createEmbed(t(guildId, 'ch_unlock'), colors.success)] });
            }
            
            if (command === '!setlog') {
                const isEn = guildDB.language === 'en';
                const opts = [
                    { label: isEn ? 'Auto Setup' : 'تسطيب تلقائي', value: 'auto', emoji: '✨' },
                    { label: isEn ? 'Manual Link' : 'ربط يدوي', value: 'manual', emoji: '🔗' },
                    { label: isEn ? 'Remove All' : 'إلغاء ربط', value: 'remove', emoji: '🗑️' }
                ];
                
                const choice = await askSelectMenu(isEn ? 'Choose setup method:' : 'اختر طريقة التسطيب:', opts, isEn ? 'Select...' : 'اختر...');
                if (choice === 'CANCEL') return;
                
                if (choice === 'auto') {
                    const loadMsg = await message.channel.send({ embeds: [createEmbed(isEn ? '⏳ Creating log channels...' : '⏳ جاري إنشاء رومات السجلات...', colors.warning)] });
                    try {
                        const category = await message.guild.channels.create({ 
                            name: isEn ? '📊 SERVER LOGS' : '📊 سجلات السيرفر', 
                            type: ChannelType.GuildCategory, 
                            permissionOverwrites: [{ id: message.guild.id, type: 0, deny: [PermissionsBitField.Flags.ViewChannel] }, { id: client.user.id, type: 1, allow: [PermissionsBitField.Flags.ViewChannel] }] 
                        });
                        
                        const createCh = async (name) => await message.guild.channels.create({ name, type: ChannelType.GuildText, parent: category.id }).catch(() => null);
                        
                        const secCh = await createCh(isEn ? '🛡️-security-log' : '🛡️-سجل-الحماية');
                        const msgCh = await createCh(isEn ? '💬-message-log' : '💬-سجل-الرسائل');
                        const memCh = await createCh(isEn ? '👥-member-log' : '👥-سجل-الأعضاء');
                        const vocCh = await createCh(isEn ? '🎙️-voice-log' : '🎙️-سجل-الصوت');
                        const srvCh = await createCh(isEn ? '⚙️-server-log' : '⚙️-سجل-السيرفر');
                        
                        if (secCh) guildDB.logChannels.security = secCh.id;
                        if (msgCh) guildDB.logChannels.messages = msgCh.id;
                        if (memCh) guildDB.logChannels.members = memCh.id;
                        if (vocCh) guildDB.logChannels.voice = vocCh.id;
                        if (srvCh) guildDB.logChannels.server = srvCh.id;
                        
                        saveDB();
                        await loadMsg.edit({ embeds: [createEmbed(isEn ? '✅ Auto setup complete!' : '✅ تم التسطيب التلقائي!', colors.success)] });
                    } catch { await loadMsg.edit({ embeds: [createEmbed('❌ Error creating channels.', colors.error)] }); }
                    setTimeout(() => loadMsg.delete(), 5000);
                }
                else if (choice === 'manual') {
                    const logTypes = [{ label: isEn ? 'Security Logs' : 'سجلات الحماية', value: 'security', emoji: '🛡️' }, { label: isEn ? 'Message Logs' : 'سجلات الرسائل', value: 'messages', emoji: '💬' }, { label: isEn ? 'Member Logs' : 'سجلات الأعضاء', value: 'members', emoji: '👥' }, { label: isEn ? 'Voice Logs' : 'سجلات الصوت', value: 'voice', emoji: '🎙️' }, { label: isEn ? 'Server Logs' : 'سجلات السيرفر', value: 'server', emoji: '⚙️' }];
                    const selected = await askSelectMenu(isEn ? 'Select logs to bind:' : 'حدد السجلات لربطها:', logTypes, isEn ? 'Select...' : 'اختر...', 1, 5);
                    if (selected === 'CANCEL') return;
                    
                    const selectedArray = Array.isArray(selected) ? selected : [selected];
                    for (let i = 0; i < selectedArray.length; i++) guildDB.logChannels[selectedArray[i]] = message.channel.id; 
                    saveDB();
                    await message.channel.send({ embeds: [createEmbed(t(guildId, 'log_set_success'), colors.success)] });
                }
                else if (choice === 'remove') {
                    let count = 0;
                    for (const cat of ['security', 'messages', 'members', 'voice', 'server']) {
                        if (guildDB.logChannels[cat] === message.channel.id) { guildDB.logChannels[cat] = null; count++; }
                    }
                    saveDB();
                    await message.channel.send({ embeds: [createEmbed(count ? t(guildId, 'log_unlink_success') : (isEn ? '⚠️ No logs bound here.' : '⚠️ لا توجد سجلات هنا.'), count ? colors.success : colors.warning)] });
                }
                return;
            }
        }

        if (['!nuke', '!delroom', '!lockdown', '!unlockdown', '!timeoutall', '!untimeoutall', '!unbanall', '!hideall', '!showall'].includes(command)) {
            if (!isDanger(currentMember)) return message.channel.send({ embeds: [createEmbed(t(guildId, 'err_danger'), colors.error)] });

            if (command === '!nuke') {
                if (await askConfirmation(t(guildId, 'nuke_warn')) === 'CONFIRM') {
                    const clonedChannel = await message.channel.clone();
                    await clonedChannel.setPosition(message.channel.position);
                    await message.channel.delete();
                    await clonedChannel.send({ embeds: [createEmbed(t(guildId, 'nuke_success'), colors.success)] });
                }
                return;
            }

            if (command === '!delroom') {
                const target = message.mentions.channels.first() || message.channel;
                if (await askConfirmation(t(guildId, 'del_warn', { channel: target.id })) === 'CONFIRM') await target.delete().catch(() => {});
                return;
            }

            if (command === '!lockdown') {
                if (await askConfirmation(t(guildId, 'lock_warn')) === 'CONFIRM') {
                    Array.from(message.guild.channels.cache.values()).forEach(async (c) => {
                        if (c.type === ChannelType.GuildText) await c.permissionOverwrites.edit(message.guild.roles.everyone, { SendMessages: false }).catch(() => {});
                    });
                    await message.channel.send({ embeds: [createEmbed(t(guildId, 'lock_done'), colors.error)] });
                }
                return;
            }

            if (command === '!unlockdown') {
                if (await askConfirmation(t(guildId, 'unlock_warn')) === 'CONFIRM') {
                    Array.from(message.guild.channels.cache.values()).forEach(async (c) => {
                        if (c.type === ChannelType.GuildText) await c.permissionOverwrites.edit(message.guild.roles.everyone, { SendMessages: null }).catch(() => {});
                    });
                    await message.channel.send({ embeds: [createEmbed(t(guildId, 'unlock_done'), colors.success)] });
                }
                return;
            }

            if (command === '!timeoutall') {
                let ms = parseTime(args[1] || '1h') || 3600000;
                if (ms > MAX_TIMEOUT_MS) ms = MAX_TIMEOUT_MS;
                const reason = args.slice(2).join(' ') || 'Mass Timeout';
                
                let count = 0;
                const membersArray = Array.from((await message.guild.members.fetch()).values());
                for (let i = 0; i < membersArray.length; i++) {
                    const m = membersArray[i];
                    if (!m.user.bot && m.manageable && !isImmune(m)) {
                        await m.timeout(ms, reason).catch(() => {});
                        count++;
                    }
                }
                await message.channel.send({ embeds: [createEmbed(`✅ Timed out ${count} members.`, colors.success)] });
                return;
            }

            if (command === '!untimeoutall') {
                let count = 0;
                const membersArray = Array.from((await message.guild.members.fetch()).values());
                for (let i = 0; i < membersArray.length; i++) {
                    const m = membersArray[i];
                    if (!m.user.bot && m.manageable && m.isCommunicationDisabled()) {
                        await m.timeout(null).catch(() => {});
                        count++;
                    }
                }
                await message.channel.send({ embeds: [createEmbed(`✅ Un-timed out ${count} members.`, colors.success)] });
                return;
            }

            if (command === '!unbanall') {
                if (await askConfirmation(t(guildId, 'unbanall_warn')) === 'CONFIRM') {
                    const bansArray = Array.from((await message.guild.bans.fetch()).values());
                    let count = 0;
                    for (let i = 0; i < bansArray.length; i++) {
                        await message.guild.bans.remove(bansArray[i].user.id).catch(() => {});
                        count++;
                    }
                    await message.channel.send({ embeds: [createEmbed(t(guildId, 'unbanall_success', { num: count }), colors.success)] });
                }
                return;
            }

            if (command === '!hideall') {
                if (await askConfirmation('⚠️ Hide ALL channels?') === 'CONFIRM') {
                    Array.from(message.guild.channels.cache.values()).forEach(async (c) => {
                        if (c.type === ChannelType.GuildText || c.type === ChannelType.GuildVoice || c.type === ChannelType.GuildCategory) {
                            await c.permissionOverwrites.edit(message.guild.roles.everyone, { ViewChannel: false }).catch(() => {});
                        }
                    });
                    await message.channel.send({ embeds: [createEmbed(t(guildId, 'hideall_done'), colors.error)] });
                }
                return;
            }

            if (command === '!showall') {
                if (await askConfirmation('⚠️ Show ALL channels?') === 'CONFIRM') {
                    Array.from(message.guild.channels.cache.values()).forEach(async (c) => {
                        if (c.type === ChannelType.GuildText || c.type === ChannelType.GuildVoice || c.type === ChannelType.GuildCategory) {
                            await c.permissionOverwrites.edit(message.guild.roles.everyone, { ViewChannel: null }).catch(() => {});
                        }
                    });
                    await message.channel.send({ embeds: [createEmbed(t(guildId, 'showall_done'), colors.success)] });
                }
                return;
            }
        }

        if (['!ban', '!unban', '!kick', '!timeout', '!untimeout', '!vmute', '!vunmute', '!rar', '!jail', '!unjail', '!role'].includes(command)) {
            if (!isMod(currentMember)) return message.channel.send({ embeds: [createEmbed(t(guildId, 'err_mod'), colors.error)] });

            let targetId = await getTargetId(args[1]);
            if (!targetId) return message.channel.send({ embeds: [createEmbed(t(guildId, 'invalid_id'), colors.warning)] });

            const getReason = async () => {
                const opts = [{ label: t(guildId, 'ui_rsn_spam'), value: 'Spamming', emoji: '📢' }, { label: t(guildId, 'ui_rsn_swear'), value: 'Inappropriate Language', emoji: '🤬' }, { label: t(guildId, 'ui_rsn_rules'), value: 'Administrative Violation', emoji: '📜' }, { label: 'Custom', value: 'custom', emoji: '✏️' }];
                let reason = await askSelectMenu(t(guildId, 'ui_rsn_prompt'), opts, t(guildId, 'ui_select_config'));
                if (reason === 'CANCEL') return null;
                if (reason === 'custom') reason = await askText(t(guildId, 'ui_rsn_custom'));
                return reason === 'CANCEL' ? null : reason;
            };

            if (command === '!role') {
                const roleId = getRoleId(args.slice(2).join(' '));
                const isEn = guildDB.language === 'en';
                
                if (!roleId) return message.channel.send({ embeds: [createEmbed(isEn ? '💡 Specify a valid role.' : '💡 يرجى تحديد رتبة صحيحة.', colors.warning)] });
                
                const targetRole = message.guild.roles.cache.get(roleId);
                if (!targetRole) return message.channel.send({ embeds: [createEmbed(t(guildId, 'not_found'), colors.error)] });
                if (guildDB.roles.protected.includes(targetRole.id) && !isRoleMaster(currentMember)) return message.channel.send({ embeds: [createEmbed(t(guildId, 'role_protected_deny'), colors.error)] });
                
                const targetMember = await message.guild.members.fetch(targetId).catch(() => null);
                if (!targetMember) return message.channel.send({ embeds: [createEmbed(t(guildId, 'not_found'), colors.error)] });
                if (!isHigherHierarchy(currentMember, targetMember)) return message.channel.send({ embeds: [createEmbed(t(guildId, 'hierarchy_err'), colors.error)] });
                if (!targetMember.manageable) return message.channel.send({ embeds: [createEmbed(t(guildId, 'not_manageable'), colors.error)] });
                
                try {
                    if (targetMember.roles.cache.has(targetRole.id)) {
                        await targetMember.roles.remove(targetRole);
                        await message.channel.send({ embeds: [createEmbed(isEn ? `➖ Removed ${targetRole.name} from <@${targetId}>` : `➖ تم سحب ${targetRole.name} من <@${targetId}>`, colors.success)] }); 
                    } else {
                        await targetMember.roles.add(targetRole);
                        await message.channel.send({ embeds: [createEmbed(isEn ? `➕ Added ${targetRole.name} to <@${targetId}>` : `➕ تم إعطاء ${targetRole.name} لـ <@${targetId}>`, colors.success)] }); 
                    }
                } catch (err) { await message.channel.send({ embeds: [createEmbed(isEn ? '❌ Failed! Check my permissions and hierarchy.' : '❌ فشل! تأكد من صلاحيات البوت ورتبته.', colors.error)] }); }
                return;
            }

            if (command === '!ban') {
                const reason = await getReason();
                if (!reason) return;
                const targetMember = await message.guild.members.fetch(targetId).catch(() => null);
                const isEn = guildDB.language === 'en';
                
                if (targetMember && (!isHigherHierarchy(currentMember, targetMember) || isImmune(targetMember))) return message.channel.send({ embeds: [createEmbed(t(guildId, 'not_manageable'), colors.error)] });
                
                try {
                    await message.guild.members.ban(targetId, { reason: reason });
                    await message.channel.send({ embeds: [createEmbed(t(guildId, 'act_ban', { target: `<@${targetId}>`, reason: reason }), colors.success)] }); 
                } catch (err) { await message.channel.send({ embeds: [createEmbed(isEn ? '❌ Action failed! Please check my permissions.' : '❌ فشل الإجراء! يرجى التأكد من صلاحيات البوت.', colors.error)] }); }
                return;
            }

            if (command === '!unban') {
                const isEn = guildDB.language === 'en';
                if (await askConfirmation(isEn ? `⚠️ Unban <@${targetId}>?` : `⚠️ هل تريد فك الحظر عن <@${targetId}>؟`) === 'CONFIRM') {
                    try {
                        await message.guild.bans.remove(targetId);
                        await message.channel.send({ embeds: [createEmbed(t(guildId, 'act_unban', { target: `<@${targetId}>` }), colors.success)] }); 
                        await sendLog(message.guild, 'members', createEmbed(isEn ? `🕊️ ${message.author.tag} unbanned <@${targetId}>` : `🕊️ ${message.author.tag} فك الحظر عن <@${targetId}>`, colors.success));
                    } catch (error) { await message.channel.send({ embeds: [createEmbed(isEn ? '❌ Failed to unban. Ensure the user is actually banned and I have Ban permissions.' : '❌ فشل فك الحظر. تأكد أن العضو محظور بالفعل وأن البوت يمتلك الصلاحيات الكافية.', colors.error)] }); }
                }
                return;
            }

            if (command === '!kick') {
                const reason = await getReason();
                if (!reason) return;
                const isEn = guildDB.language === 'en';
                const targetMember = await message.guild.members.fetch(targetId).catch(() => null);
                
                if (!targetMember) return message.channel.send({ embeds: [createEmbed(t(guildId, 'not_found'), colors.error)] });
                if (targetMember.kickable && !isImmune(targetMember) && isHigherHierarchy(currentMember, targetMember)) {
                    try {
                        await targetMember.kick(reason);
                        await message.channel.send({ embeds: [createEmbed(t(guildId, 'act_kick', { target: `<@${targetId}>`, reason: reason }), colors.success)] }); 
                    } catch (err) { await message.channel.send({ embeds: [createEmbed(isEn ? '❌ Action failed! Please check my permissions.' : '❌ فشل الإجراء! يرجى التأكد من صلاحيات البوت.', colors.error)] }); }
                } else { await message.channel.send({ embeds: [createEmbed(t(guildId, 'not_manageable'), colors.error)] }); }
                return;
            }

            if (command === '!timeout') {
                const isEn = guildDB.language === 'en';
                let timeInput = args[2];
                if (!timeInput) {
                    timeInput = await askSelectMenu(t(guildId, 'ui_mute_prompt'), [{ label: '10m', value: '10m' }, { label: '1h', value: '1h' }, { label: '1d', value: '1d' }], t(guildId, 'ui_select_config'));
                    if (timeInput === 'CANCEL') return;
                }
                
                const ms = parseTime(timeInput);
                if (!ms || ms > MAX_TIMEOUT_MS) return message.channel.send({ embeds: [createEmbed(t(guildId, 'invalid_time'), colors.error)] }); 
                
                const reason = await getReason();
                if (!reason) return;
                const targetMember = await message.guild.members.fetch(targetId).catch(() => null);
                
                if (!targetMember) return message.channel.send({ embeds: [createEmbed(t(guildId, 'not_found'), colors.error)] });
                if (targetMember.manageable && !isImmune(targetMember) && isHigherHierarchy(currentMember, targetMember)) {
                    try {
                        await targetMember.timeout(ms, reason);
                        await message.channel.send({ embeds: [createEmbed(t(guildId, 'act_mute', { target: `<@${targetId}>`, time: timeInput, reason: reason }), colors.warning)] }); 
                    } catch (err) { await message.channel.send({ embeds: [createEmbed(isEn ? '❌ Action failed! Please check my permissions.' : '❌ فشل الإجراء! يرجى التأكد من صلاحيات البوت.', colors.error)] }); }
                } else { await message.channel.send({ embeds: [createEmbed(t(guildId, 'not_manageable'), colors.error)] }); }
                return;
            }

            if (command === '!untimeout') {
                const isEn = guildDB.language === 'en';
                const targetMember = await message.guild.members.fetch(targetId).catch(() => null);
                if (!targetMember) return message.channel.send({ embeds: [createEmbed(t(guildId, 'not_found'), colors.error)] });
                
                if (targetMember.manageable && targetMember.isCommunicationDisabled() && isHigherHierarchy(currentMember, targetMember)) {
                    try {
                        await targetMember.timeout(null);
                        await message.channel.send({ embeds: [createEmbed(t(guildId, 'act_unmute', { target: `<@${targetId}>` }), colors.success)] }); 
                    } catch (err) { await message.channel.send({ embeds: [createEmbed(isEn ? '❌ Action failed! Please check my permissions.' : '❌ فشل الإجراء! يرجى التأكد من صلاحيات البوت.', colors.error)] }); }
                } else { await message.channel.send({ embeds: [createEmbed(t(guildId, 'not_timed_out'), colors.error)] }); }
                return;
            }

            if (command === '!vmute') {
                const isEn = guildDB.language === 'en';
                const targetMember = await message.guild.members.fetch(targetId).catch(() => null);
                if (!targetMember) return message.channel.send({ embeds: [createEmbed(t(guildId, 'not_found'), colors.error)] });
                
                if (targetMember.voice.channel && targetMember.manageable && !isImmune(targetMember) && isHigherHierarchy(currentMember, targetMember)) {
                    try {
                        await targetMember.voice.setMute(true);
                        await message.channel.send({ embeds: [createEmbed(t(guildId, 'act_vmute', { target: `<@${targetId}>` }), colors.warning)] }); 
                    } catch (err) { await message.channel.send({ embeds: [createEmbed(isEn ? '❌ Action failed! Please check my permissions.' : '❌ فشل الإجراء! يرجى التأكد من صلاحيات البوت.', colors.error)] }); }
                } else { await message.channel.send({ embeds: [createEmbed(t(guildId, 'not_in_voice'), colors.error)] }); }
                return;
            }

            if (command === '!vunmute') {
                const isEn = guildDB.language === 'en';
                const targetMember = await message.guild.members.fetch(targetId).catch(() => null);
                if (!targetMember) return message.channel.send({ embeds: [createEmbed(t(guildId, 'not_found'), colors.error)] });
                
                if (targetMember.voice.channel && targetMember.manageable && isHigherHierarchy(currentMember, targetMember)) {
                    try {
                        await targetMember.voice.setMute(false);
                        await message.channel.send({ embeds: [createEmbed(t(guildId, 'act_vunmute', { target: `<@${targetId}>` }), colors.success)] }); 
                    } catch (err) { await message.channel.send({ embeds: [createEmbed(isEn ? '❌ Action failed! Please check my permissions.' : '❌ فشل الإجراء! يرجى التأكد من صلاحيات البوت.', colors.error)] }); }
                } else { await message.channel.send({ embeds: [createEmbed(t(guildId, 'not_in_voice'), colors.error)] }); }
                return;
            }

            if (command === '!rar') {
                if (await askConfirmation(`⚠️ Are you sure you want to remove **ALL roles** from <@${targetId}>?`) === 'CONFIRM') {
                    const targetMember = await message.guild.members.fetch(targetId).catch(() => null);
                    const isEn = guildDB.language === 'en';
                    
                    if (!targetMember) return message.channel.send({ embeds: [createEmbed(t(guildId, 'not_found'), colors.error)] });
                    if (!isHigherHierarchy(currentMember, targetMember) || isImmune(targetMember)) return message.channel.send({ embeds: [createEmbed(t(guildId, 'not_manageable'), colors.error)] });
                    
                    const rolesToRemove = targetMember.roles.cache.filter(r => r.id !== message.guild.id && r.editable);
                    let removedCount = 0;
                    
                    try {
                        for (const role of rolesToRemove.values()) {
                            await targetMember.roles.remove(role).catch(() => {});
                            removedCount++;
                        }
                        await message.channel.send({ embeds: [createEmbed(t(guildId, 'act_rar', { target: `<@${targetId}>` }), colors.warning)] }); 
                        await sendLog(message.guild, 'members', createEmbed(`🗑️ **Remove All Roles**\nExecutor: <@${userId}>\nTarget: <@${targetId}>\nRemoved: ${removedCount} roles`, colors.warning));
                    } catch (err) { await message.channel.send({ embeds: [createEmbed(isEn ? '❌ Action failed! Please check my permissions.' : '❌ فشل الإجراء! يرجى التأكد من صلاحيات البوت.', colors.error)] }); }
                }
                return;
            }

            if (command === '!jail') {
                if (!guildDB.jail || !guildDB.jail.role || !guildDB.jail.channel) return message.channel.send({ embeds: [createEmbed(t(guildId, 'jail_not_setup'), colors.error)] });
                
                const reason = await getReason(); 
                if (!reason) return;
                
                const isEn = guildDB.language === 'en';
                const targetMember = await message.guild.members.fetch(targetId).catch(() => null);
                
                if (!targetMember) return message.channel.send({ embeds: [createEmbed(t(guildId, 'not_found'), colors.error)] });
                if (guildDB.jailedUsers[targetId]) return message.channel.send({ embeds: [createEmbed(t(guildId, 'err_already_jailed'), colors.error)] });
                if (!isHigherHierarchy(currentMember, targetMember) || isImmune(targetMember)) return message.channel.send({ embeds: [createEmbed(t(guildId, 'not_manageable'), colors.error)] });
                
                try {
                    const originalRoles = [];
                    targetMember.roles.cache.forEach((r) => {
                        if (r.id !== message.guild.id && r.editable) originalRoles.push(r.id);
                    });
                    
                    guildDB.jailedUsers[targetId] = originalRoles;
                    saveDB();
                    
                    for (const role of targetMember.roles.cache.values()) {
                        if (role.id !== message.guild.id && role.editable) await targetMember.roles.remove(role).catch(() => {});
                    }
                    
                    await targetMember.roles.add(guildDB.jail.role);
                    if (targetMember.voice.channel) await targetMember.voice.disconnect().catch(() => {});
                    
                    await message.channel.send({ embeds: [createEmbed(t(guildId, 'act_jail', { target: `<@${targetId}>`, reason: reason }), colors.error)] }); 
                    await sendLog(message.guild, 'members', createEmbed(`🚨 **Jail**\nExecutor: <@${userId}>\nTarget: <@${targetId}>\nReason: ${reason}`, colors.error));
                } catch (err) { await message.channel.send({ embeds: [createEmbed(isEn ? '❌ Action failed! Please check my permissions.' : '❌ فشل الإجراء! يرجى التأكد من صلاحيات البوت.', colors.error)] }); }
                return;
            }

            if (command === '!unjail') {
                const isEn = guildDB.language === 'en';
                const targetMember = await message.guild.members.fetch(targetId).catch(() => null);
                const jailedData = guildDB.jailedUsers[targetId]; 
                
                let isJailed = false;
                if (jailedData) isJailed = true;
                if (targetMember && guildDB.jail && guildDB.jail.role && targetMember.roles.cache.has(guildDB.jail.role)) isJailed = true;
                
                if (!isJailed) return message.channel.send({ embeds: [createEmbed(t(guildId, 'err_not_jailed'), colors.error)] });
                
                if (targetMember) {
                    if (!isHigherHierarchy(currentMember, targetMember)) return message.channel.send({ embeds: [createEmbed(t(guildId, 'hierarchy_err'), colors.error)] });
                    if (!targetMember.manageable) return message.channel.send({ embeds: [createEmbed(t(guildId, 'not_manageable'), colors.error)] });
                    
                    let rolesToRestore = [];
                    if (jailedData && Array.isArray(jailedData)) {
                        for (let i = 0; i < jailedData.length; i++) {
                            if (message.guild.roles.cache.has(jailedData[i])) rolesToRestore.push(jailedData[i]);
                        }
                    }
                    
                    try {
                        await targetMember.roles.set(rolesToRestore);
                    } catch (err) {
                        return message.channel.send({ embeds: [createEmbed(isEn ? '❌ Action failed! Please check my permissions.' : '❌ فشل الإجراء! يرجى التأكد من صلاحيات البوت.', colors.error)] });
                    }
                }
                
                if (guildDB.jailedUsers[targetId]) {
                    delete guildDB.jailedUsers[targetId];
                    saveDB();
                }
                
                await message.channel.send({ embeds: [createEmbed(t(guildId, 'act_unjail', { target: `<@${targetId}>` }), colors.success)] }); 
                await sendLog(message.guild, 'members', createEmbed(isEn ? `🔓 **Unjail**\nExecutor: <@${userId}>\nTarget: <@${targetId}>` : `🔓 **إفراج (Unjail)**\nالمنفذ: <@${userId}>\nالهدف: <@${targetId}>`, colors.success));
                return;
            }
        }
    });
};