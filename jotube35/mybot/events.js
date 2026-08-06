const { 
    AuditLogEvent, PermissionsBitField, EmbedBuilder, AttachmentBuilder, 
    ActionRowBuilder, StringSelectMenuBuilder, StringSelectMenuOptionBuilder, 
    UserSelectMenuBuilder, ComponentType, ButtonBuilder, ButtonStyle, 
    ChannelType, MessageFlags 
} = require('discord.js');

const { 
    colors, ONE_DAY_MS, TWO_DAYS_MS, SPAM_TIME, smartSwearRegex, 
    spamMap, kickTracker, banTracker, joinTracker, raidMode 
} = require('./config');

const { GLOBAL_DEVELOPER_ID, getGuildDB, saveDB } = require('./database');
const { isGuildOwnerOrDev, isRoot, isAdmin, isBuilder, isMod, isImmune } = require('./permissions');
const { t, createEmbed } = require('./utils');

module.exports = (client) => {

    // ==========================================
    // 🚨 دوال الحماية والمراسلة المركزية (Wick Style)
    // ==========================================
    const checkUnauthorizedAction = async (guild, executorId) => {
        if (!executorId) return false;
        if (executorId === client.user.id) return false;
        
        const executorMember = await guild.members.fetch(executorId).catch(() => null);
        if (!executorMember) return false;
        
        // تخطي نظام ديسكورد (Onboarding / System)
        if (executorMember.user.system) return false; 
        
        if (isBuilder(executorMember) || isAdmin(executorMember) || isRoot(executorMember) || isGuildOwnerOrDev(executorMember)) {
            return false;
        }
        return true;
    };

    const sendLog = async (guild, category, embed, files = []) => {
        try {
            const guildDB = getGuildDB(guild.id);
            let channelId = guildDB.logChannels[category];
            if (!channelId) channelId = guildDB.logChannels.messages || guildDB.logChannels.server;
            if (!channelId) return;

            const channel = await guild.channels.fetch(channelId).catch(() => null);
            if (channel) {
                embed.setTimestamp();
                embed.setFooter({ text: guild.name, iconURL: guild.iconURL({ dynamic: true }) || client.user.displayAvatarURL() });
                await channel.send({ embeds: [embed], files: files }).catch(() => {});
            }
        } catch (err) {}
    };

    const punishExecutor = async (guild, executorId, actionName) => {
        if (!executorId || executorId === client.user.id) return;
        const member = await guild.members.fetch(executorId).catch(() => null);
        if (!member || member.id === guild.ownerId) return;
        if (member.roles.highest.position >= guild.members.me.roles.highest.position) return;
        
        const isBanAction = actionName === 'Unauthorized Member Ban';
        
        // تنفيذ العقوبة المخصصة (بان لو حاول يبند، كلير رول لأي حاجة تانية)
        if (isBanAction) {
            await member.ban({ reason: 'Wick Style: Unauthorized Ban (Anti-Nuke)' }).catch(() => {});
        } else {
            const rolesToRemove = member.roles.cache.filter(r => r.id !== guild.id && r.editable);
            for (const role of rolesToRemove.values()) {
                await member.roles.remove(role).catch(() => {});
            }
        }
        
        const guildDB = getGuildDB(guild.id);
        const isEn = guildDB.language === 'en';
        
        const punishmentText = isBanAction ? (isEn ? 'Banned' : 'تم حظره (بان)') : (isEn ? 'Stripped of all roles' : 'سحب جميع الرتب');
        
        let logTxt = isEn 
            ? `🚨 **Wick Security System (Anti-Nuke):**\nExecutor <@${executorId}> attempted dangerous unauthorized action (\`${actionName}\`).\n**Punishment:** ${punishmentText} and action reverted!` 
            : `🚨 **Wick Security System (Anti-Nuke):**\nالمنفذ <@${executorId}> قام بإجراء خطير وغير مصرح به (\`${actionName}\`).\n**العقوبة:** ${punishmentText} وعكس الإجراء فوراً!`;
        
        const logEmbed = createEmbed(logTxt, colors.error);
        await sendLog(guild, 'security', logEmbed);
    };

    const alertRoots = async (guild, contentTxt, filesArray) => {
        const guildDB = getGuildDB(guild.id);
        const rootIds = new Set(guildDB.users.root);
        if (guild.ownerId) rootIds.add(guild.ownerId);
        rootIds.add(GLOBAL_DEVELOPER_ID);
        
        for (const id of rootIds) {
            const user = await client.users.fetch(id).catch(() => null);
            if (user) await user.send({ content: contentTxt, files: filesArray }).catch(() => {});
        }
    };

    const fetchActionLog = async (guild, actionType, targetId = null) => {
        try {
            await new Promise((r) => setTimeout(r, 150));
            const logs = await guild.fetchAuditLogs({ limit: 10, type: actionType });
            const entry = logs.entries.find((log) => {
                if (!log) return false;
                if (targetId) return log.targetId === targetId;
                return true;
            });
            if (!entry) return null;
            if (Date.now() - entry.createdTimestamp > 10000) return null;
            return entry.executor;
        } catch (err) { return null; }
    };

    // ==========================================
    // 🖱️ معالج التفاعلات (أزرار وقوائم الإعدادات)
    // ==========================================
    client.on('interactionCreate', async (interaction) => {
        if (!interaction.guildId) return;

        const dynamicPrefixes = ['confirm_btn_', 'cancel_btn_', 'sel_', 'say_ch_', 'say_ct_', 'backup_type_'];
        if (interaction.customId && dynamicPrefixes.some(prefix => interaction.customId.startsWith(prefix))) {
            if (interaction.customId.includes('|')) {
                const ownerId = interaction.customId.split('|').pop();
                if (interaction.user.id !== ownerId) {
                    return interaction.reply({ content: t(interaction.guildId, 'interaction_locked'), flags: MessageFlags.Ephemeral });
                }
            }
            return; 
        }

        if (interaction.customId && interaction.customId.includes('|')) {
            const parts = interaction.customId.split('|');
            const ownerId = parts.pop(); 
            const originalId = parts.join('|'); 
            if (interaction.user.id !== ownerId) {
                return interaction.reply({ content: t(interaction.guildId, 'interaction_locked'), flags: MessageFlags.Ephemeral });
            }
            Object.defineProperty(interaction, 'customId', { value: originalId });
        }

        const guildId = interaction.guildId;
        const guildDB = getGuildDB(guildId); 
        
        if (interaction.isUserSelectMenu()) {
            if (interaction.customId === 'select_root_user') {
                if (!isGuildOwnerOrDev(interaction.member)) {
                    const errorEmbed = createEmbed(t(guildId, 'err_owner'), colors.error);
                    return interaction.reply({ embeds: [errorEmbed], flags: MessageFlags.Ephemeral });
                }
                const targetUserId = interaction.values[0];
                if (targetUserId === interaction.guild.ownerId) {
                    let errorMsg = guildDB.language === 'en' ? '❌ Cannot add this user as Root, they are the server owner!' : '❌ لا يمكن إضافة مالك السيرفر كروت!';
                    return interaction.reply({ embeds: [createEmbed(errorMsg, colors.error)], flags: MessageFlags.Ephemeral });
                }
                if (targetUserId === GLOBAL_DEVELOPER_ID) {
                    let errorMsg = guildDB.language === 'en' ? '❌ Cannot add this user as Root, they are the System Developer!' : '❌ لا يمكن إضافة هذا العضو كروت لأنه مطور النظام!';
                    return interaction.reply({ embeds: [createEmbed(errorMsg, colors.error)], flags: MessageFlags.Ephemeral });
                }
                if (guildDB.users.root.includes(targetUserId)) {
                    let errorMsg = guildDB.language === 'en' ? '❌ User is already Root!' : '❌ العضو موجود بالفعل في قائمة الروت!';
                    return interaction.reply({ embeds: [createEmbed(errorMsg, colors.error)], flags: MessageFlags.Ephemeral });
                }
                guildDB.users.root.push(targetUserId);
                saveDB();

                const msg = await interaction.reply({ content: t(guildId, 'root_added_success'), fetchReply: true });
                await interaction.message.delete().catch(() => {});
                setTimeout(() => { msg.delete().catch(() => {}); }, 7000);
                const logEmbed = createEmbed(`👑 **إضافة قيادة عُليا (Root)**\nالمنفذ: <@${interaction.user.id}>\nالهدف: <@${targetUserId}>`, colors.info);
                await sendLog(interaction.guild, 'security', logEmbed);
                return;
            }
        }

        if (interaction.isStringSelectMenu()) {
            if (interaction.values[0] === 'CANCEL_MENU') {
                await interaction.message.delete().catch(() => {});
                return;
            }
            if (interaction.customId === 'remove_root_user_menu') {
                if (!isGuildOwnerOrDev(interaction.member)) {
                    return interaction.reply({ embeds: [createEmbed(t(guildId, 'err_owner'), colors.error)], flags: MessageFlags.Ephemeral });
                }
                const targetUserId = interaction.values[0];
                const index = guildDB.users.root.indexOf(targetUserId);
                if (index > -1) {
                    guildDB.users.root.splice(index, 1);
                    saveDB();
                    const msg = await interaction.reply({ content: t(guildId, 'root_removed_success'), fetchReply: true });
                    setTimeout(() => { msg.delete().catch(() => {}); }, 7000);
                    const logEmbed = createEmbed(`🚫 **سحب قيادة عُليا (Root)**\nالمنفذ: <@${interaction.user.id}>\nالهدف: <@${targetUserId}>`, colors.warning);
                    await sendLog(interaction.guild, 'security', logEmbed);
                } else {
                    const msg = await interaction.reply({ content: t(guildId, 'not_found'), fetchReply: true });
                    setTimeout(() => { msg.delete().catch(() => {}); }, 7000);
                }
                return;
            }
            if (interaction.customId === 'help_menu') {
                const choice = interaction.values[0];
                let newEmbed = new EmbedBuilder().setColor(colors.main).setTimestamp();
                const choices = {
                    root: t(guildId, 'desc_root'), mod: t(guildId, 'desc_mod'), setup: t(guildId, 'desc_setup'),
                    danger: t(guildId, 'desc_danger'), security: t(guildId, 'desc_sec'), info: t(guildId, 'desc_info'), wl: t(guildId, 'desc_wl')
                };
                newEmbed.setTitle(`=== [ ${t(guildId, `h_${choice}`)} ] ===`);
                newEmbed.setDescription(choices[choice] || '');
                await interaction.update({ embeds: [newEmbed] }).catch(() => {});
                return;
            }
            if (interaction.customId === 'settings_main') {
                const choice = interaction.values[0];
                if (choice === 'lang') {
                    const btnAr = new ButtonBuilder().setCustomId(`set_lang_ar|${interaction.user.id}`).setLabel('العربية').setStyle(ButtonStyle.Primary).setEmoji('🇪🇬');
                    const btnEn = new ButtonBuilder().setCustomId(`set_lang_en|${interaction.user.id}`).setLabel('English').setStyle(ButtonStyle.Secondary).setEmoji('🇺🇸');
                    const btnCancel = new ButtonBuilder().setCustomId(`cancel_settings|${interaction.user.id}`).setLabel(t(guildId, 'btn_cancel')).setStyle(ButtonStyle.Danger).setEmoji('❌');
                    const row = new ActionRowBuilder().addComponents(btnAr, btnEn, btnCancel);
                    await interaction.update({ content: t(guildId, 'ui_lang_prompt'), embeds: [], components: [row] });
                    return;
                }
                if (choice === 'security') {
                    const sec = guildDB.security;
                    let descString = t(guildId, 'ui_sec_desc');
                    descString += `\n🔗 **Anti-Link:** ${sec.antiLink ? t(guildId, 'ui_on') : t(guildId, 'ui_off')}\n📢 **Anti-Spam:** ${sec.antiSpam ? t(guildId, 'ui_on') : t(guildId, 'ui_off')}\n🤐 **Anti-Swear:** ${sec.antiSwear ? t(guildId, 'ui_on') : t(guildId, 'ui_off')}\n🤖 **Anti-Alt:** ${sec.antiAlt ? t(guildId, 'ui_on') : t(guildId, 'ui_off')}\n🚨 **Anti-Raid:** ${sec.antiRaid ? t(guildId, 'ui_on') : t(guildId, 'ui_off')}`;
                    const embed = new EmbedBuilder().setTitle(`=== [ ${t(guildId, 'ui_sec_title')} ] ===`).setColor(colors.warning).setDescription(descString);
                    const btnLink = new ButtonBuilder().setCustomId(`tog_link|${interaction.user.id}`).setLabel('Anti-Link').setStyle(sec.antiLink ? ButtonStyle.Success : ButtonStyle.Danger);
                    const btnSpam = new ButtonBuilder().setCustomId(`tog_spam|${interaction.user.id}`).setLabel('Anti-Spam').setStyle(sec.antiSpam ? ButtonStyle.Success : ButtonStyle.Danger);
                    const btnSwear = new ButtonBuilder().setCustomId(`tog_swear|${interaction.user.id}`).setLabel('Anti-Swear').setStyle(sec.antiSwear ? ButtonStyle.Success : ButtonStyle.Danger);
                    const btnAlt = new ButtonBuilder().setCustomId(`tog_alt|${interaction.user.id}`).setLabel('Anti-Alt').setStyle(sec.antiAlt ? ButtonStyle.Success : ButtonStyle.Danger);
                    const btnRaid = new ButtonBuilder().setCustomId(`tog_raid|${interaction.user.id}`).setLabel('Anti-Raid').setStyle(sec.antiRaid ? ButtonStyle.Success : ButtonStyle.Danger);
                    const row1 = new ActionRowBuilder().addComponents(btnLink, btnSpam, btnSwear, btnAlt, btnRaid);
                    const row2 = new ActionRowBuilder().addComponents(new ButtonBuilder().setCustomId(`cancel_settings|${interaction.user.id}`).setLabel('❌').setStyle(ButtonStyle.Secondary));
                    await interaction.update({ content: '', embeds: [embed], components: [row1, row2] });
                    return;
                }
                if (choice === 'limits') {
                    const limits = guildDB.limits;
                    let descStr = `${t(guildId, 'ui_limits_desc')}\n\n🚪 **Kick Limit:** ${limits.antiNukeKick === 999 ? 'Unlimited (Off)' : limits.antiNukeKick} / Day\n🔨 **Ban Limit:** ${limits.antiNukeBan === 999 ? 'Unlimited (Off)' : limits.antiNukeBan} / 2 Days`;
                    const limitEmbed = new EmbedBuilder().setTitle(`=== [ ${t(guildId, 'ui_limits_title')} ] ===`).setColor(colors.error).setDescription(descStr);
                    const getOpts = () => [ { label: '1 Limit', value: '1' }, { label: '2 Limits', value: '2' }, { label: '3 Limits', value: '3' }, { label: '5 Limits', value: '5' }, { label: '10 Limits', value: '10' }, { label: '50 Limits', value: '50' }, { label: 'Unlimited (Off)', value: '999' }, { label: t(guildId, 'ui_close_menu'), value: 'CANCEL_MENU', emoji: '❌' } ];
                    const kickMenu = new StringSelectMenuBuilder().setCustomId(`limit_kick|${interaction.user.id}`).setPlaceholder('Set Kick Limit...').addOptions(getOpts());
                    const banMenu = new StringSelectMenuBuilder().setCustomId(`limit_ban|${interaction.user.id}`).setPlaceholder('Set Ban Limit...').addOptions(getOpts());
                    await interaction.update({ content: '', embeds: [limitEmbed], components: [new ActionRowBuilder().addComponents(kickMenu), new ActionRowBuilder().addComponents(banMenu)] });
                    return;
                }
                if (choice === 'root_add') {
                    const menu = new UserSelectMenuBuilder().setCustomId(`select_root_user|${interaction.user.id}`).setPlaceholder(guildDB.language === 'en' ? '🔍 Search or select user...' : '🔍 ابحث أو اختر العضو...').setMinValues(1).setMaxValues(1);
                    const cancelBtn = new ButtonBuilder().setCustomId(`cancel_settings|${interaction.user.id}`).setLabel(t(guildId, 'btn_cancel')).setStyle(ButtonStyle.Danger).setEmoji('❌');
                    await interaction.update({ content: '', embeds: [createEmbed(t(guildId, 'root_select_prompt'), colors.warning)], components: [new ActionRowBuilder().addComponents(menu), new ActionRowBuilder().addComponents(cancelBtn)] });
                    return;
                }
                if (choice === 'root_rem') {
                    if (guildDB.users.root.length === 0) {
                        await interaction.update({ content: guildDB.language === 'en' ? '❌ No custom roots found.' : '❌ لا يوجد أعضاء في قائمة الروت حالياً.', embeds: [], components: [] });
                        setTimeout(() => { interaction.message.delete().catch(() => {}); }, 5000);
                        return;
                    }
                    let rootOptions = [];
                    for (const rId of guildDB.users.root) {
                        const rUser = await client.users.fetch(rId).catch(() => null);
                        if (rUser) rootOptions.push({ label: rUser.tag, value: rId, emoji: '🚫' });
                    }
                    rootOptions.push({ label: t(guildId, 'ui_close_menu'), value: 'CANCEL_MENU', emoji: '❌' });
                    const menu = new StringSelectMenuBuilder().setCustomId(`remove_root_user_menu|${interaction.user.id}`).setPlaceholder(guildDB.language === 'en' ? 'Select user to remove from Root...' : 'اختر العضو للإزالة من الروت...').addOptions(rootOptions.map((opt) => new StringSelectMenuOptionBuilder().setLabel(opt.label).setValue(opt.value).setEmoji(opt.emoji)));
                    await interaction.update({ content: t(guildId, 'root_rem_prompt'), embeds: [], components: [new ActionRowBuilder().addComponents(menu)] });
                    return;
                }
            }
            if (interaction.customId === 'limit_kick' || interaction.customId === 'limit_ban') {
                const val = parseInt(interaction.values[0]);
                if (interaction.customId === 'limit_kick') guildDB.limits.antiNukeKick = val;
                if (interaction.customId === 'limit_ban') guildDB.limits.antiNukeBan = val;
                saveDB();
                const msg = await interaction.update({ content: guildDB.language === 'en' ? '✅ Limits Updated Successfully.' : '✅ تم تحديث حدود الحماية بنجاح.', embeds: [], components: [], fetchReply: true });
                setTimeout(() => { msg.delete().catch(() => {}); }, 7000);
                return;
            }
        }

        if (interaction.isButton()) {
            if (interaction.customId === 'cancel_settings') {
                await interaction.message.delete().catch(() => {});
                return;
            }
            if (interaction.customId === 'set_lang_ar') { 
                guildDB.language = 'ar'; saveDB(); 
                const msg = await interaction.update({ content: '✅ تم تغيير لغة النظام للعربية.', embeds: [], components: [], fetchReply: true }); 
                setTimeout(() => { msg.delete().catch(() => {}); }, 7000);
                return; 
            }
            if (interaction.customId === 'set_lang_en') { 
                guildDB.language = 'en'; saveDB(); 
                const msg = await interaction.update({ content: '✅ System language changed to English.', embeds: [], components: [], fetchReply: true }); 
                setTimeout(() => { msg.delete().catch(() => {}); }, 7000);
                return; 
            }
            if (interaction.customId.startsWith('tog_')) {
                const type = interaction.customId.split('_')[1];
                if (type === 'link') guildDB.security.antiLink = !guildDB.security.antiLink;
                else if (type === 'spam') guildDB.security.antiSpam = !guildDB.security.antiSpam;
                else if (type === 'swear') guildDB.security.antiSwear = !guildDB.security.antiSwear;
                else if (type === 'alt') guildDB.security.antiAlt = !guildDB.security.antiAlt;
                else if (type === 'raid') guildDB.security.antiRaid = !guildDB.security.antiRaid;
                saveDB();
                
                const sec = guildDB.security;
                let descString = t(guildId, 'ui_sec_desc') + `\n🔗 **Anti-Link:** ${sec.antiLink ? t(guildId, 'ui_on') : t(guildId, 'ui_off')}\n📢 **Anti-Spam:** ${sec.antiSpam ? t(guildId, 'ui_on') : t(guildId, 'ui_off')}\n🤐 **Anti-Swear:** ${sec.antiSwear ? t(guildId, 'ui_on') : t(guildId, 'ui_off')}\n🤖 **Anti-Alt:** ${sec.antiAlt ? t(guildId, 'ui_on') : t(guildId, 'ui_off')}\n🚨 **Anti-Raid:** ${sec.antiRaid ? t(guildId, 'ui_on') : t(guildId, 'ui_off')}`;
                const embed = new EmbedBuilder().setTitle(`=== [ ${t(guildId, 'ui_sec_title')} ] ===`).setColor(colors.warning).setDescription(descString);
                
                const btnLink = new ButtonBuilder().setCustomId(`tog_link|${interaction.user.id}`).setLabel('Anti-Link').setStyle(sec.antiLink ? ButtonStyle.Success : ButtonStyle.Danger);
                const btnSpam = new ButtonBuilder().setCustomId(`tog_spam|${interaction.user.id}`).setLabel('Anti-Spam').setStyle(sec.antiSpam ? ButtonStyle.Success : ButtonStyle.Danger);
                const btnSwear = new ButtonBuilder().setCustomId(`tog_swear|${interaction.user.id}`).setLabel('Anti-Swear').setStyle(sec.antiSwear ? ButtonStyle.Success : ButtonStyle.Danger);
                const btnAlt = new ButtonBuilder().setCustomId(`tog_alt|${interaction.user.id}`).setLabel('Anti-Alt').setStyle(sec.antiAlt ? ButtonStyle.Success : ButtonStyle.Danger);
                const btnRaid = new ButtonBuilder().setCustomId(`tog_raid|${interaction.user.id}`).setLabel('Anti-Raid').setStyle(sec.antiRaid ? ButtonStyle.Success : ButtonStyle.Danger);

                await interaction.update({ embeds: [embed], components: [new ActionRowBuilder().addComponents(btnLink, btnSpam, btnSwear, btnAlt, btnRaid), new ActionRowBuilder().addComponents(new ButtonBuilder().setCustomId(`cancel_settings|${interaction.user.id}`).setLabel('❌').setStyle(ButtonStyle.Secondary))] });
                return;
            }
        }
    });

    // ==========================================
    // 📝 أحداث السجلات و Wick
    // ==========================================
    client.on('messageUpdate', async (oldMsg, newMsg) => {
        if (oldMsg.partial || newMsg.partial || !newMsg.guild || !newMsg.author || newMsg.author.bot || oldMsg.content === newMsg.content) return;
        const guildDB = getGuildDB(newMsg.guild.id);
        const secSettings = guildDB.security;
        const isEn = guildDB.language === 'en';
        const currentMember = await newMsg.guild.members.fetch(newMsg.author.id).catch(() => null);
        const isAutoModBypassed = isGuildOwnerOrDev(currentMember) || isRoot(currentMember) || isAdmin(currentMember) || isMod(currentMember) || isImmune(currentMember);
        
        if (secSettings && secSettings.antiSwear && !isAutoModBypassed) {
            const cleanContent = newMsg.content.replace(/[\u200B-\u200D\uFEFF]/g, '').replace(/ـ/g, '').toLowerCase();
            if (smartSwearRegex.test(cleanContent)) {
                await newMsg.delete().catch(() => {});
                if (!guildDB.swearTracker) guildDB.swearTracker = {};
                let count = (guildDB.swearTracker[newMsg.author.id] || 0) + 1;
                guildDB.swearTracker[newMsg.author.id] = count;
                saveDB();
                if (currentMember && currentMember.manageable) await currentMember.timeout(count * 30 * 60 * 1000, `Auto-Mod: Edited message to swear #${count}`).catch(() => {});
                
                await newMsg.channel.send({ embeds: [createEmbed(isEn ? `⚠️ <@${newMsg.author.id}>, nice try! Swearing in edited messages is still forbidden. Timeout: **${count * 30} minutes**.` : `⚠️ <@${newMsg.author.id}>، حركة ذكية بس الرادار لقطك! تعديل الرسالة لشتيمة ممنوع. تم إسكاتك لمدة **${count * 30} دقيقة**.`, colors.error)] }); 
                await sendLog(newMsg.guild, 'security', createEmbed(isEn ? `🤐 **Auto-Mod (Smart Anti-Swear - Edit)**\nUser: <@${newMsg.author.id}>\nTimeout: **${count * 30} Min** (Violation #${count})\nOld: ||${oldMsg.content}||\nNew: ||${newMsg.content}||` : `🤐 **نظام الحماية (صائد التعديلات)**\nالعضو: <@${newMsg.author.id}>\nالعقاب: تايم أوت **${count * 30} دقيقة** (مخالفة رقم ${count})\nالرسالة قبل: ||${oldMsg.content}||\nالرسالة بعد: ||${newMsg.content}||`, colors.warning));
                smartSwearRegex.lastIndex = 0; return; 
            }
            smartSwearRegex.lastIndex = 0;
        }

        let beforeContent = oldMsg.content || (isEn ? '*(Not cached)*' : '*(غير مسجلة)*');
        let afterContent = newMsg.content || '*(None)*';
        let files = [];

        if (beforeContent.length >= 1000 || afterContent.length >= 1000) {
            files.push(new AttachmentBuilder(Buffer.from(`=== EDITED MESSAGE ===\nAuthor: ${newMsg.author.tag}\nChannel: #${newMsg.channel.name}\n--- BEFORE ---\n${beforeContent}\n--- AFTER ---\n${afterContent}`, 'utf-8'), { name: `edit_${newMsg.id}.txt` }));
            beforeContent = afterContent = '*(Long text - see file)*';
        }

        const embed = new EmbedBuilder().setColor(colors.warning).setAuthor({ name: newMsg.author.tag, iconURL: newMsg.author.displayAvatarURL() }).setTitle(isEn ? '📝 Message Edited' : '📝 تم تعديل رسالة')
            .addFields({ name: isEn ? 'Author' : 'العضو', value: `<@${newMsg.author.id}>`, inline: true }, { name: isEn ? 'Channel' : 'الروم', value: `<#${newMsg.channel.id}>`, inline: true }, { name: isEn ? 'Old Content' : 'النص القديم', value: `>>> ${beforeContent}`, inline: false }, { name: isEn ? 'New Content' : 'النص الجديد', value: `>>> ${afterContent}`, inline: false }).setTimestamp();
        await sendLog(newMsg.guild, 'messages', embed, files);
    });

    client.on('messageDelete', async (msg) => {
        if (!msg.guild) return;
        if (msg.author && msg.author.id === client.user.id && (msg.embeds.length > 0 || /^[✅❌⚠️⏳🧹🕊️🔨🚪🔇🔊🎙️🎤]/.test(msg.content))) return;

        const guildDB = getGuildDB(msg.guild.id);
        const isEn = guildDB.language === 'en';
        let content = msg.content || (isEn ? '*(No content)*' : '*(لا يوجد محتوى)*');
        const executor = await fetchActionLog(msg.guild, AuditLogEvent.MessageDelete, msg.author ? msg.author.id : null);

        const embed = new EmbedBuilder().setColor(colors.error).setTitle(isEn ? '🗑️ Message Deleted' : '🗑️ تم حذف رسالة')
            .setDescription(`**${isEn ? 'Author' : 'العضو'}:** ${msg.author ? `<@${msg.author.id}>` : 'Unknown'}\n**${isEn ? 'Channel' : 'الروم'}:** <#${msg.channel.id}>\n${executor ? `**${isEn ? 'Deleted By' : 'بواسطة'}:** <@${executor.id}>\n` : ''}**${isEn ? 'Content' : 'المحتوى'}:**\n\`\`\`${content.length > 500 ? content.substring(0, 500) + '...' : content}\`\`\``).setTimestamp();
        await sendLog(msg.guild, 'messages', embed);
    });

    client.on('messageDeleteBulk', async (messages) => {
        const first = messages.first();
        if (!first || !first.guild) return;
        const executor = await fetchActionLog(first.guild, AuditLogEvent.MessageBulkDelete);
        
        const fileData = Array.from(messages.values()).map(m => `[${m.createdAt ? m.createdAt.toLocaleString() : 'Unknown'}] ${m.author ? m.author.tag : 'Unknown'}: ${m.content || '(No content)'}`).join('\n');
        const attachment = new AttachmentBuilder(Buffer.from(fileData, 'utf-8'), { name: `bulk_${Date.now()}.txt` });
        
        const embed = new EmbedBuilder().setColor(colors.error).setTitle('🧹 Bulk Delete').setDescription(`**Channel:** <#${first.channel.id}>\n**Count:** ${messages.size}\n**Executor:** ${executor ? `<@${executor.id}>` : 'Unknown'}`).setTimestamp();
        await sendLog(first.guild, 'messages', embed, [attachment]);
    });

    client.on('voiceStateUpdate', async (oldState, newState) => {
        if (oldState.member && oldState.member.user && oldState.member.user.bot) return;
        const guildDB = getGuildDB(newState.guild.id);
        const isEn = guildDB.language === 'en';
        let memberId = newState.member ? newState.member.id : '0';

        if (!oldState.channelId && newState.channelId) {
            await sendLog(newState.guild, 'voice', new EmbedBuilder().setColor(colors.success).setTitle(isEn ? '🔊 Voice Join' : '🔊 دخول صوتي').addFields({ name: isEn ? 'User' : 'العضو', value: `<@${memberId}>`, inline: true }, { name: isEn ? 'Channel' : 'الروم', value: `<#${newState.channelId}>`, inline: true }).setTimestamp());
        } else if (oldState.channelId && !newState.channelId) {
            const executor = await fetchActionLog(newState.guild, AuditLogEvent.MemberDisconnect, memberId);
            await sendLog(newState.guild, 'voice', new EmbedBuilder().setColor(colors.error).setTitle(isEn ? '🔇 Voice Leave' : '🔇 خروج صوتي').addFields({ name: isEn ? 'User' : 'العضو', value: `<@${memberId}>`, inline: true }, { name: isEn ? 'Channel' : 'الروم', value: `<#${oldState.channelId}>`, inline: true }, { name: isEn ? 'Action By' : 'بواسطة', value: executor ? `<@${executor.id}>` : (isEn ? 'Themselves' : 'بنفسه'), inline: false }).setTimestamp());
        } else if (!oldState.serverMute && newState.serverMute) {
            const executor = await fetchActionLog(newState.guild, AuditLogEvent.MemberUpdate, memberId);
            await sendLog(newState.guild, 'voice', new EmbedBuilder().setColor(colors.error).setTitle(isEn ? '🎙️ Server Muted' : '🎙️ تم كتم المايك').addFields({ name: isEn ? 'User' : 'العضو', value: `<@${memberId}>`, inline: true }, { name: isEn ? 'Muted By' : 'كتم بواسطة', value: executor ? `<@${executor.id}>` : 'Unknown', inline: true }, { name: isEn ? 'Channel' : 'الروم', value: `<#${newState.channelId}>`, inline: false }).setTimestamp());
        } else if (oldState.serverMute && !newState.serverMute) {
            const executor = await fetchActionLog(newState.guild, AuditLogEvent.MemberUpdate, memberId);
            await sendLog(newState.guild, 'voice', new EmbedBuilder().setColor(colors.success).setTitle(isEn ? '🎤 Server Unmuted' : '🎤 تم فك الكتم').addFields({ name: isEn ? 'User' : 'العضو', value: `<@${memberId}>`, inline: true }, { name: isEn ? 'Unmuted By' : 'فك الكتم بواسطة', value: executor ? `<@${executor.id}>` : 'Unknown', inline: true }, { name: isEn ? 'Channel' : 'الروم', value: `<#${newState.channelId}>`, inline: false }).setTimestamp());
        }
    });

    client.on('channelCreate', async (channel) => {
        if (!channel.guild) return;
        const executor = await fetchActionLog(channel.guild, AuditLogEvent.ChannelCreate, channel.id);
        if (executor && await checkUnauthorizedAction(channel.guild, executor.id)) {
            await punishExecutor(channel.guild, executor.id, 'Unauthorized Channel Creation');
            return channel.delete().catch(() => {});
        }
        const guildDB = getGuildDB(channel.guild.id);
        if (guildDB.jail && guildDB.jail.role && channel.id !== guildDB.jail.channel) await channel.permissionOverwrites.edit(guildDB.jail.role, { ViewChannel: false }).catch(() => {});
        await sendLog(channel.guild, 'server', new EmbedBuilder().setColor(colors.success).setTitle('📁 Channel Created').addFields({ name: 'Channel', value: `<#${channel.id}>`, inline: true }, { name: 'Type', value: channel.type === ChannelType.GuildVoice ? 'Voice' : 'Text', inline: true }, { name: 'Created By', value: executor ? `<@${executor.id}>` : 'Unknown', inline: false }).setTimestamp());
    });

    client.on('channelDelete', async (channel) => {
        if (!channel.guild) return;
        const executor = await fetchActionLog(channel.guild, AuditLogEvent.ChannelDelete, channel.id);
        if (executor && await checkUnauthorizedAction(channel.guild, executor.id)) {
            await punishExecutor(channel.guild, executor.id, 'Unauthorized Channel Deletion');
            try { await channel.guild.channels.create({ name: channel.name, type: channel.type, parent: channel.parentId, position: channel.position, topic: channel.topic, nsfw: channel.nsfw, rateLimitPerUser: channel.rateLimitPerUser, bitrate: channel.bitrate, userLimit: channel.userLimit, permissionOverwrites: channel.permissionOverwrites.cache.map(ow => ({ id: ow.id, allow: ow.allow.bitfield, deny: ow.deny.bitfield, type: ow.type })), reason: 'Wick Style: Anti-Nuke Revert' }); } catch (err) {}
            return; 
        }
        await sendLog(channel.guild, 'server', new EmbedBuilder().setColor(colors.error).setTitle('🗑️ Channel Deleted').addFields({ name: 'Name', value: channel.name, inline: true }, { name: 'Deleted By', value: executor ? `<@${executor.id}>` : 'Unknown', inline: true }).setTimestamp());
    });

    client.on('channelUpdate', async (oldChannel, newChannel) => {
        if (!newChannel.guild) return;
        const executor = await fetchActionLog(newChannel.guild, AuditLogEvent.ChannelUpdate, newChannel.id);
        if (executor && await checkUnauthorizedAction(newChannel.guild, executor.id)) {
            await punishExecutor(newChannel.guild, executor.id, 'Unauthorized Channel Modification');
            try {
                await newChannel.edit({ name: oldChannel.name, type: oldChannel.type, topic: oldChannel.topic, nsfw: oldChannel.nsfw, bitrate: oldChannel.bitrate, userLimit: oldChannel.userLimit, rateLimitPerUser: oldChannel.rateLimitPerUser, position: oldChannel.position, parent: oldChannel.parentId, reason: 'Wick Style: Anti-Nuke Revert' });
                await newChannel.permissionOverwrites.set(oldChannel.permissionOverwrites.cache.map(ow => ({ id: ow.id, allow: ow.allow.bitfield, deny: ow.deny.bitfield, type: ow.type })), 'Wick Style: Permissions Revert');
            } catch(e) {}
        }
    });

    client.on('roleCreate', async (role) => {
        if (!role.guild) return;
        const executor = await fetchActionLog(role.guild, AuditLogEvent.RoleCreate, role.id);
        if (executor && await checkUnauthorizedAction(role.guild, executor.id)) {
            await punishExecutor(role.guild, executor.id, 'Unauthorized Role Creation');
            return role.delete().catch(() => {});
        }
        await sendLog(role.guild, 'server', new EmbedBuilder().setColor(colors.success).setTitle('🎭 Role Created').addFields({ name: 'Role', value: `<@&${role.id}>`, inline: true }, { name: 'Created By', value: executor ? `<@${executor.id}>` : 'Unknown', inline: true }).setTimestamp());
    });

    client.on('roleDelete', async (role) => {
        if (!role.guild) return;
        const executor = await fetchActionLog(role.guild, AuditLogEvent.RoleDelete, role.id);
        if (executor && await checkUnauthorizedAction(role.guild, executor.id)) {
            await punishExecutor(role.guild, executor.id, 'Unauthorized Role Deletion');
            try { await role.guild.roles.create({ name: role.name, color: role.color, hoist: role.hoist, permissions: role.permissions, position: role.position, mentionable: role.mentionable, reason: 'Wick Style: Auto-Recreate deleted role' }); } catch (err) {}
            return;
        }
        await sendLog(role.guild, 'server', new EmbedBuilder().setColor(colors.error).setTitle('🗑️ Role Deleted').addFields({ name: 'Name', value: role.name, inline: true }, { name: 'Deleted By', value: executor ? `<@${executor.id}>` : 'Unknown', inline: true }).setTimestamp());
    });

    client.on('roleUpdate', async (oldRole, newRole) => {
        if (!newRole.guild) return;
        const executor = await fetchActionLog(newRole.guild, AuditLogEvent.RoleUpdate, newRole.id);
        if (executor && await checkUnauthorizedAction(newRole.guild, executor.id)) {
            await punishExecutor(newRole.guild, executor.id, 'Unauthorized Role Modification');
            try { await newRole.edit({ name: oldRole.name, color: oldRole.color, hoist: oldRole.hoist, permissions: oldRole.permissions, position: oldRole.position, mentionable: oldRole.mentionable, reason: 'Wick Style: Revert unauthorized changes' }); } catch(e) {}
        }
    });

    client.on('guildMemberUpdate', async (oldMember, newMember) => {
        if (!newMember.guild) return;
        
        // --- 1. فحص تعديل الرتب ---
        if (oldMember.roles.cache.size !== newMember.roles.cache.size) {
            const executor = await fetchActionLog(newMember.guild, AuditLogEvent.MemberRoleUpdate, newMember.id);
            // نتأكد إن اللي نفذ ده مش هو العضو نفسه (عشان الـ Onboarding)
            if (executor && executor.id !== newMember.id && await checkUnauthorizedAction(newMember.guild, executor.id)) {
                await punishExecutor(newMember.guild, executor.id, 'Unauthorized Member Roles Modification');
                try { await newMember.roles.set(oldMember.roles.cache.map(r => r.id), 'Wick Style: Anti-Nuke Role Revert'); } catch(e) {}
            }
        }
        
        // --- 2. فحص التايم أوت (إضافة جديدة) ---
        if (!oldMember.isCommunicationDisabled() && newMember.isCommunicationDisabled()) {
            const executor = await fetchActionLog(newMember.guild, AuditLogEvent.MemberUpdate, newMember.id);
            if (executor && await checkUnauthorizedAction(newMember.guild, executor.id)) {
                await punishExecutor(newMember.guild, executor.id, 'Unauthorized Member Timeout');
                try { await newMember.timeout(null, 'Wick Style: Anti-Nuke Timeout Revert'); } catch(e) {}
            }
        }
    });

    client.on('webhookUpdate', async (channel) => {
        if (!channel.guild) return;
        const executor = await fetchActionLog(channel.guild, AuditLogEvent.WebhookCreate) || await fetchActionLog(channel.guild, AuditLogEvent.WebhookUpdate) || await fetchActionLog(channel.guild, AuditLogEvent.WebhookDelete);
        if (executor && await checkUnauthorizedAction(channel.guild, executor.id)) {
            await punishExecutor(channel.guild, executor.id, 'Unauthorized Webhook Modification');
            try { (await channel.fetchWebhooks()).forEach(async w => await w.delete('Wick Style: Anti-Nuke Webhook Purge')); } catch(e) {}
        }
    });

    client.on('guildBanAdd', async (ban) => {
        const executor = await fetchActionLog(ban.guild, AuditLogEvent.MemberBanAdd, ban.user.id);
        if (executor && await checkUnauthorizedAction(ban.guild, executor.id)) {
            await punishExecutor(ban.guild, executor.id, 'Unauthorized Member Ban');
            return ban.guild.bans.remove(ban.user.id, 'Wick Style: Unauthorized Ban Revert').catch(() => {});
        }
        await sendLog(ban.guild, 'security', new EmbedBuilder().setColor(colors.error).setTitle('🔨 Member Banned').addFields({ name: 'User', value: `<@${ban.user.id}>`, inline: true }, { name: 'Banned By', value: executor ? `<@${executor.id}>` : 'Unknown', inline: true }, { name: 'Reason', value: ban.reason || 'None', inline: false }).setTimestamp());
    });

    client.on('guildBanRemove', async (ban) => {
        const executor = await fetchActionLog(ban.guild, AuditLogEvent.MemberBanRemove, ban.user.id);
        await sendLog(ban.guild, 'security', new EmbedBuilder().setColor(colors.success).setTitle('🕊️ Member Unbanned').addFields({ name: 'User', value: `<@${ban.user.id}>`, inline: true }, { name: 'Unbanned By', value: executor ? `<@${executor.id}>` : 'Unknown', inline: true }).setTimestamp());
    });

    client.on('guildMemberRemove', async (member) => {
        const guildDB = getGuildDB(member.guild.id);
        const isEn = guildDB.language === 'en';
        const executor = await fetchActionLog(member.guild, AuditLogEvent.MemberKick, member.id);
        
        if (executor && await checkUnauthorizedAction(member.guild, executor.id)) await punishExecutor(member.guild, executor.id, 'Unauthorized Member Kick');
        
        await sendLog(member.guild, 'members', new EmbedBuilder().setColor(colors.error).setTitle(executor ? (isEn ? '🚪 Member Kicked' : '🚪 تم طرد عضو') : (isEn ? '📤 Member Left' : '📤 خروج عضو'))
            .setDescription(`**User:** <@${member.id}>${executor ? `\n**${isEn ? 'Kicked By:' : 'طرد بواسطة:'}** <@${executor.id}>` : ''}`).addFields({ name: isEn ? 'Joined At' : 'تاريخ الدخول', value: `<t:${Math.floor(member.joinedTimestamp / 1000)}:R>`, inline: true }).setTimestamp());
    });

    client.on('guildUpdate', async (oldGuild, newGuild) => {
        if (oldGuild.name !== newGuild.name || oldGuild.iconURL() !== newGuild.iconURL()) {
            const executor = await fetchActionLog(newGuild, AuditLogEvent.GuildUpdate);
            if (executor && await checkUnauthorizedAction(newGuild, executor.id)) {
                await punishExecutor(newGuild, executor.id, 'Unauthorized Server Modification (Name/Icon)');
                try { await newGuild.edit({ name: oldGuild.name, icon: oldGuild.iconURL({ dynamic: true }) || null, banner: oldGuild.bannerURL() || null, splash: oldGuild.splashURL() || null, verificationLevel: oldGuild.verificationLevel, explicitContentFilter: oldGuild.explicitContentFilter, defaultMessageNotifications: oldGuild.defaultMessageNotifications, reason: 'Wick Style: Revert Server Info Tampering' }); } catch(e) {}
                return; 
            }
            await sendLog(newGuild, 'server', new EmbedBuilder().setColor(colors.info).setTitle('⚙️ Server Updated').addFields({ name: 'Old Name', value: oldGuild.name, inline: true }, { name: 'New Name', value: newGuild.name, inline: true }, { name: 'Changed By', value: executor ? `<@${executor.id}>` : 'Unknown', inline: false }).setTimestamp());
        }
    });

    client.on('emojiCreate', async (emoji) => {
        const executor = await fetchActionLog(emoji.guild, AuditLogEvent.EmojiCreate, emoji.id);
        await sendLog(emoji.guild, 'server', new EmbedBuilder().setColor(colors.success).setTitle('😀 Emoji Added').addFields({ name: 'Emoji', value: `${emoji} \`:${emoji.name}:\``, inline: true }, { name: 'Added By', value: executor ? `<@${executor.id}>` : 'Unknown', inline: true }).setTimestamp());
    });

    client.on('emojiDelete', async (emoji) => {
        const executor = await fetchActionLog(emoji.guild, AuditLogEvent.EmojiDelete, emoji.id);
        await sendLog(emoji.guild, 'server', new EmbedBuilder().setColor(colors.error).setTitle('🗑️ Emoji Deleted').addFields({ name: 'Name', value: `:${emoji.name}:`, inline: true }, { name: 'Deleted By', value: executor ? `<@${executor.id}>` : 'Unknown', inline: true }).setTimestamp());
    });

    client.on('stickerCreate', async (sticker) => {
        const executor = await fetchActionLog(sticker.guild, AuditLogEvent.StickerCreate, sticker.id);
        await sendLog(sticker.guild, 'server', new EmbedBuilder().setColor(colors.success).setTitle('🎨 Sticker Added').addFields({ name: 'Name', value: sticker.name, inline: true }, { name: 'Added By', value: executor ? `<@${executor.id}>` : 'Unknown', inline: true }).setTimestamp());
    });

    client.on('stickerDelete', async (sticker) => {
        const executor = await fetchActionLog(sticker.guild, AuditLogEvent.StickerDelete, sticker.id);
        await sendLog(sticker.guild, 'server', new EmbedBuilder().setColor(colors.error).setTitle('🗑️ Sticker Deleted').addFields({ name: 'Name', value: sticker.name, inline: true }, { name: 'Deleted By', value: executor ? `<@${executor.id}>` : 'Unknown', inline: true }).setTimestamp());
    });

    client.on('guildMemberAdd', async (member) => {
        if (member.partial) return;
        const guildDB = getGuildDB(member.guild.id);
        const isEn = guildDB.language === 'en';

        if (member.user.bot) {
            const executor = await fetchActionLog(member.guild, AuditLogEvent.BotAdd, member.id);
            if (executor && await checkUnauthorizedAction(member.guild, executor.id)) {
                await punishExecutor(member.guild, executor.id, 'Unauthorized Bot Addition');
                return member.kick('Wick Style: Unauthorized Bot Detected').catch(() => {});
            }
        }
        
        if (guildDB.autoRoles && guildDB.autoRoles.length > 0) {
            const rolesToAdd = guildDB.autoRoles.filter(r => member.guild.roles.cache.has(r));
            if (rolesToAdd.length > 0) await member.roles.add(rolesToAdd).catch(() => {});
        }
        
        if (guildDB.jailedUsers && guildDB.jailedUsers[member.id] && guildDB.jail && guildDB.jail.role && member.guild.roles.cache.has(guildDB.jail.role)) {
            await member.roles.set([]).catch(() => {});
            await member.roles.add(guildDB.jail.role).catch(() => {});
            return sendLog(member.guild, 'security', createEmbed(isEn ? `🚨 ${member.user.tag} rejoined while jailed - role reapplied.` : `🚨 ${member.user.tag} حاول الهروب من السجن - تم إعادة الرتبة.`, colors.error));
        }
        
        if (guildDB.security) {
            if (guildDB.security.antiAlt && (Date.now() - member.user.createdTimestamp) < 7 * 24 * 60 * 60 * 1000) {
                await member.timeout(7 * 24 * 60 * 60 * 1000, 'Anti-Alt: Account too new').catch(() => {});
                await sendLog(member.guild, 'security', createEmbed(isEn ? `🚨 Suspicious account: ${member.user.tag} (Created <7 days ago) - Timed out.` : `🚨 حساب مشبوه: ${member.user.tag} (أنشئ منذ أقل من 7 أيام) - تم إعطاء تايم أوت.`, colors.warning));
            }
            
            if (guildDB.security.antiRaid) {
                if (raidMode.get(member.guild.id) && (Date.now() - member.user.createdTimestamp) < 30 * 24 * 60 * 60 * 1000) {
                    if (member.kickable) await member.kick('Anti-Raid: Lockdown active, account under 30 days').catch(() => {});
                    return sendLog(member.guild, 'security', createEmbed(isEn ? `🛡️ Kicked ${member.user.tag} (account <30 days) during raid lockdown.` : `🛡️ تم طرد ${member.user.tag} (حساب أقل من 30 يوم) أثناء حالة الطوارئ.`, colors.error));
                } else {
                    if (!joinTracker.has(member.guild.id)) joinTracker.set(member.guild.id, []);
                    const joins = joinTracker.get(member.guild.id);
                    joins.push(Date.now());
                    const recentJoins = joins.filter(t => Date.now() - t < 30 * 1000);
                    joinTracker.set(member.guild.id, recentJoins);
                    
                    if (recentJoins.length >= 10) {
                        raidMode.set(member.guild.id, true);
                        joinTracker.delete(member.guild.id);
                        await sendLog(member.guild, 'security', createEmbed(isEn ? `🚨 RAID DETECTED! Lockdown initiated.` : `🚨 تم اكتشاف غزو! تم تفعيل الطوارئ.`, colors.error));
                        await alertRoots(member.guild, isEn ? '🚨 Raid detected! Lockdown active for 7 minutes.' : '🚨 تم اكتشاف غزو! الطوارئ فعالة لمدة 7 دقائق.', []);
                        
                        const invites = await member.guild.invites.fetch().catch(() => []);
                        invites.forEach(inv => inv.delete().catch(() => {}));
                        
                        const everyoneRole = member.guild.roles.everyone;
                        await everyoneRole.setPermissions(everyoneRole.permissions.remove(PermissionsBitField.Flags.CreateInstantInvite)).catch(() => {});
                        
                        setTimeout(async () => {
                            raidMode.delete(member.guild.id);
                            await everyoneRole.setPermissions(everyoneRole.permissions.add(PermissionsBitField.Flags.CreateInstantInvite)).catch(() => {});
                            await sendLog(member.guild, 'security', createEmbed(isEn ? `✅ Lockdown lifted. Server back to normal.` : `✅ تم رفع الطوارئ. السيرفر عاد للطبيعي.`, colors.success));
                            await alertRoots(member.guild, isEn ? '✅ Lockdown lifted. Server is safe.' : '✅ تم رفع الطوارئ. السيرفر آمن.', []);
                        }, 7 * 60 * 1000);
                    }
                }
            }
        }
        
        await sendLog(member.guild, 'members', new EmbedBuilder().setColor(colors.success).setTitle(isEn ? '📥 Member Joined' : '📥 عضو جديد').addFields({ name: isEn ? 'User' : 'العضو', value: `<@${member.id}>`, inline: true }, { name: isEn ? 'Account Created' : 'تاريخ الإنشاء', value: `<t:${Math.floor(member.user.createdTimestamp / 1000)}:R>`, inline: true }).setThumbnail(member.user.displayAvatarURL()).setTimestamp());
    });

};