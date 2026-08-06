const PROXY_URL = 'proxy.hosty.qzz.io';
console.log('\n[Hosty Network] 🌐 Global Interceptor Active!');
const origExit = process.exit;
process.exit = function(code) { console.log('\n[Hosty Shield] 🛡️ تم منع البوت من إغلاق نفسه (Exit Code: ' + code + ')'); };
process.on('unhandledRejection', (e) => { if (e && e.message && e.message.includes('Timeout')) console.log('\n[Hosty Network] ⏳ البروكسي تأخر، يتم إعادة المحاولة...'); });
process.on('uncaughtException', (e) => {});
try { const d = require('discord.js'); if (d.Options && d.Options.DefaultRestOptions) d.Options.DefaultRestOptions.api = 'https://' + PROXY_URL + '/api'; if (d.Constants && d.Constants.DefaultOptions && d.Constants.DefaultOptions.http) d.Constants.DefaultOptions.http.api = 'https://' + PROXY_URL + '/api'; if (d.Client) { const Orig = d.Client; d.Client = new Proxy(Orig, { construct(target, args) { const c = new target(...args); c.on('error', () => {}); return c; } }); require.cache[require.resolve('discord.js')].exports = d; } } catch(e) {}
try { const rest = require('@discordjs/rest'); if (rest && rest.DefaultRestOptions) rest.DefaultRestOptions.api = 'https://' + PROXY_URL + '/api'; } catch(e) {}
try { require('./index.js'); } catch(e) { console.log('\n[Hosty] ❌ حدث خطأ في كود البوت الخاص بك:\n', e); }
