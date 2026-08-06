const https = require('https');
const PROXY = 'proxy.hosty.qzz.io';

function patchOpt(opt) {
    if (typeof opt === 'string') return opt.replace(/discord\.com/g, PROXY).replace(/app\.discord\.com/g, PROXY);
    if (opt && opt.hostname && opt.hostname.includes('discord.com')) opt.hostname = PROXY;
    if (opt && opt.host && opt.host.includes('discord.com')) opt.host = PROXY;
    return opt;
}

const origReq = https.request;
https.request = function(opt, ...args) { return origReq.call(this, patchOpt(opt), ...args); };

const origGet = https.get;
https.get = function(opt, ...args) { return origGet.call(this, patchOpt(opt), ...args); };

if (global.fetch) {
    const origFetch = global.fetch;
    global.fetch = function(url, opt) {
        if (typeof url === 'string') url = url.replace(/discord\.com/g, PROXY).replace(/app\.discord\.com/g, PROXY);
        else if (url && url.hostname && url.hostname.includes('discord.com')) url.hostname = PROXY;
        return origFetch(url, opt);
    };
}
