const { getGuildDB, GLOBAL_DEVELOPER_ID } = require('./database');

const checkRolePerm = (member, roleArray) => {
    if (!member || !member.roles) return false;
    return member.roles.cache.some((role) => roleArray.includes(role.id));
};

const isDev = (member) => {
    if (!member) return false;
    return member.id === GLOBAL_DEVELOPER_ID;
};

const isGuildOwnerOrDev = (member) => {
    if (!member || !member.guild) return false;
    if (member.id === member.guild.ownerId) return true;
    return isDev(member);
};

const isRoot = (member) => {
    if (!member) return false;
    if (isDev(member)) return true;
    if (member.guild && member.id === member.guild.ownerId) return true;
    
    const guildDB = getGuildDB(member.guild.id);
    return guildDB.users.root.includes(member.id);
};

const isDanger = (member) => {
    if (!member) return false;
    if (isRoot(member)) return true;
    
    const guildDB = getGuildDB(member.guild.id);
    if (guildDB.users.danger.includes(member.id)) return true;
    return checkRolePerm(member, guildDB.roles.danger);
};

const isRoleMaster = (member) => {
    if (!member) return false;
    if (isRoot(member)) return true;
    
    const guildDB = getGuildDB(member.guild.id);
    if (guildDB.users.role_master.includes(member.id)) return true;
    return checkRolePerm(member, guildDB.roles.role_master);
};

const isAdmin = (member) => {
    if (!member) return false;
    if (isRoot(member)) return true;
    
    const guildDB = getGuildDB(member.guild.id);
    if (guildDB.users.admin.includes(member.id)) return true;
    return checkRolePerm(member, guildDB.roles.admin);
};

const isMod = (member) => {
    if (!member) return false;
    if (isAdmin(member)) return true;
    
    const guildDB = getGuildDB(member.guild.id);
    if (guildDB.users.mod.includes(member.id)) return true;
    return checkRolePerm(member, guildDB.roles.mod);
};

const isHelper = (member) => {
    if (!member) return false;
    if (isMod(member)) return true;
    
    const guildDB = getGuildDB(member.guild.id);
    if (guildDB.users.helper.includes(member.id)) return true;
    return checkRolePerm(member, guildDB.roles.helper);
};

const isBuilder = (member) => {
    if (!member) return false;
    if (isAdmin(member)) return true;
    
    const guildDB = getGuildDB(member.guild.id);
    if (guildDB.users.builder.includes(member.id)) return true;
    return checkRolePerm(member, guildDB.roles.builder);
};

const isImmune = (member) => {
    if (!member) return false;
    if (isDev(member)) return true;
    
    const guildDB = getGuildDB(member.guild.id);
    if (guildDB.users.immune.includes(member.id)) return true;
    if (checkRolePerm(member, guildDB.roles.immune)) return true;
    return checkRolePerm(member, guildDB.roles.protected);
};

const isHigherHierarchy = (executor, target) => {
    if (!target) return true;
    if (isDev(executor)) return true;
    if (executor.id === executor.guild.ownerId) return true;
    if (executor.id === target.id) return false;
    if (isRoot(target) || isImmune(target)) return false; 
    
    return executor.roles.highest.position > target.roles.highest.position;
};

module.exports = {
    checkRolePerm, isDev, isGuildOwnerOrDev, isRoot, isDanger, isRoleMaster,
    isAdmin, isMod, isHelper, isBuilder, isImmune, isHigherHierarchy
};