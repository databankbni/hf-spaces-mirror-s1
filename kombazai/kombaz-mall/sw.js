<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,viewport-fit=cover">
<link rel="manifest" href="/manifest.json">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="KOMBAZ">
<meta name="theme-color" content="#005288">
<link rel="apple-touch-icon" href="/static/icon-192.png">

<title>Mars 2045 | KOMBAZ.ME</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<script async src="https://www.googletagmanager.com/gtag/js?id=G-1X8X94RVYT"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}gtag('js',new Date());gtag('config','G-1X8X94RVYT')</script>
<style>
:root{--m:#e8622a;--c:#00d4ff;--g:#00ff88;--o:#f5c842;--bg:#020408;--gl:rgba(6,12,24,.92);--bd:rgba(0,212,255,.2);--ts:rgba(220,235,255,.78);--tt:rgba(180,200,230,.5);--sb:env(safe-area-inset-bottom,0);--st:env(safe-area-inset-top,0)}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{background:var(--bg);font-family:Inter,sans-serif;color:#fff;min-height:100vh;overflow-x:hidden}
canvas{position:fixed;inset:0;z-index:0;pointer-events:none}
.hdr{position:fixed;top:0;left:0;right:0;z-index:100;padding:calc(10px + var(--st)) 12px 8px;background:linear-gradient(to bottom,rgba(2,4,8,.97),transparent);display:flex;align-items:center;justify-content:space-between;gap:6px;flex-wrap:wrap}
.lg{display:flex;gap:4px;flex-wrap:wrap}
.l{padding:3px 7px;border-radius:6px;font-family:Orbitron,monospace;font-size:.5rem;font-weight:700;text-decoration:none;letter-spacing:.5px;white-space:nowrap}
.l-x{background:rgba(0,82,136,.28);border:1px solid rgba(0,82,136,.5);color:#7ec8ff}
.l-n{background:rgba(224,60,49,.14);border:1px solid rgba(224,60,49,.3);color:#ff9988}
.l-w{background:rgba(176,96,255,.12);border:1px solid rgba(176,96,255,.28);color:#cc88ff}
.l-co{background:rgba(212,165,116,.12);border:1px solid rgba(212,165,116,.28);color:#d4a574}
.hr{display:flex;align-items:center;gap:6px}
.live{display:flex;align-items:center;gap:5px;padding:4px 9px;background:rgba(255,0,0,.1);border:1px solid rgba(255,0,0,.25);border-radius:14px}
.dot{width:6px;height:6px;background:#f33;border-radius:50%;animation:p 1.5s infinite}
@keyframes p{50%{opacity:.3;transform:scale(1.4)}}
.lt{font-family:Orbitron,monospace;font-size:.46rem;font-weight:700;color:#ff8080;letter-spacing:1.5px}
.tt{text-align:center;line-height:1}
.tt h1{font-family:Orbitron,monospace;font-size:.7rem;font-weight:700;background:linear-gradient(90deg,#fff,var(--c));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.tt p{font-size:.42rem;color:var(--tt);margin-top:2px}
.main{padding-top:calc(72px + var(--st));padding-bottom:calc(210px + var(--sb));min-height:100vh;position:relative;z-index:1}
.hero{text-align:center;padding:14px 0 8px}
.yr{font-family:Orbitron,monospace;font-size:clamp(3rem,15vw,6rem);font-weight:900;line-height:1;background:linear-gradient(135deg,var(--m),#ff7040,#ffaa60);-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:yp 4s infinite}
@keyframes yp{50%{opacity:.82}}
.ph{font-size:.58rem;color:var(--tt);letter-spacing:2.5px;text-transform:uppercase;margin-top:6px}
.pb{width:min(160px,38vw);height:2px;background:rgba(255,255,255,.1);border-radius:1px;overflow:hidden;margin:8px auto 0}
.pbf{height:100%;background:linear-gradient(90deg,#005288,var(--c));transition:width .6s}
.vs{display:flex;gap:6px;padding:0 12px 8px;overflow-x:auto;scrollbar-width:none}
.vs::-webkit-scrollbar{display:none}
.vc{flex-shrink:0;background:var(--gl);border:1px solid var(--bd);border-radius:10px;padding:6px 10px;backdrop-filter:blur(14px);min-width:155px}
.vh{font-family:Orbitron,monospace;font-size:.45rem;font-weight:700;color:var(--c);margin-bottom:4px}
.vr{display:flex;justify-content:space-between;gap:10px;margin-bottom:2px}
.vl{font-size:.36rem;color:var(--tt);text-transform:uppercase}
.vv{font-family:Orbitron,monospace;font-size:.5rem;font-weight:700;color:#fff}
.vg{color:var(--g)}
.vo{color:var(--o)}
.vm{margin-top:4px;font-size:.4rem;padding:2px 6px;border-radius:8px;background:rgba(245,200,66,.1);border:1px solid rgba(245,200,66,.25);color:var(--o)}
.z{display:flex;align-items:center;gap:7px;margin:0 12px 6px;padding:5px 8px;background:rgba(0,212,255,.06);border:1px solid rgba(0,212,255,.1);border-radius:8px}
.zl{font-family:Orbitron,monospace;font-size:.45rem;color:var(--tt);white-space:nowrap}
.zb{flex:1;height:3px;background:rgba(255,255,255,.08);border-radius:2px;overflow:hidden}
.zf{height:100%;background:linear-gradient(90deg,var(--c),var(--g));border-radius:2px;transition:width 1s}
.zn{font-family:Orbitron,monospace;font-size:.46rem;color:var(--c);white-space:nowrap}
.cb{display:flex;gap:5px;align-items:center;justify-content:center;flex-wrap:wrap;padding:0 10px 8px}
.b{padding:7px 12px;border-radius:18px;border:1px solid;font-size:.6rem;font-weight:600;cursor:pointer;font-family:Inter,sans-serif;min-height:38px;white-space:nowrap;background:transparent;color:var(--ts)}
.b-n{border-color:rgba(255,255,255,.15);background:rgba(255,255,255,.06)}
.yd{font-family:Orbitron,monospace;font-size:.9rem;font-weight:900;color:var(--c);min-width:48px;text-align:center}
.b-a{border-color:rgba(0,255,136,.2);background:rgba(0,255,136,.05);color:rgba(0,255,136,.8)}
.b-a.on{background:rgba(0,255,136,.16);border-color:rgba(0,255,136,.5);color:var(--g)}
.b-m{border-color:rgba(245,200,66,.22);background:rgba(245,200,66,.06);color:var(--o)}
.ft{display:flex;gap:4px;padding:0 12px 8px;overflow-x:auto;scrollbar-width:none}
.ft::-webkit-scrollbar{display:none}
.ftb{flex-shrink:0;padding:5px 10px;border-radius:12px;font-size:.54rem;font-weight:600;cursor:pointer;border:1px solid rgba(255,255,255,.09);background:rgba(255,255,255,.04);color:var(--ts);white-space:nowrap;min-height:28px;display:flex;align-items:center}
.ftb.on{background:rgba(0,82,136,.55);border-color:var(--c);color:var(--c)}
.cs{display:flex;gap:8px;padding:0 12px;overflow-x:auto;scrollbar-width:none;-webkit-overflow-scrolling:touch}
.cs::-webkit-scrollbar{display:none}
.cd{flex-shrink:0;width:clamp(170px,50vw,210px);background:linear-gradient(145deg,rgba(6,14,32,.96),rgba(10,20,44,.92));border:1px solid rgba(0,212,255,.14);border-radius:16px;cursor:pointer;overflow:hidden;transition:transform .2s}
.cd:active{transform:scale(.96)}
.cd.cu{border-color:rgba(0,212,255,.35)}
.cd.do{border-color:rgba(0,255,136,.3)}
.cd.lk{opacity:.3;cursor:default}
.ac{height:3px;width:100%}
.a-x{background:linear-gradient(90deg,#005288,var(--c))}
.a-n{background:linear-gradient(90deg,#e03c31,#ff8866)}
.a-c{background:linear-gradient(90deg,#22aa66,var(--g))}
.a-i{background:linear-gradient(90deg,var(--o),#ff9922)}
.a-r{background:linear-gradient(90deg,#6644cc,#9966ff)}
.a-p{background:linear-gradient(90deg,#c87020,#f5a840)}
.a-cr{background:linear-gradient(90deg,#ff3860,#ff8844)}
.cb2{padding:10px 11px}
.st{display:inline-flex;align-items:center;gap:4px;font-size:.4rem;padding:2px 7px;border-radius:14px;font-weight:700;margin-bottom:5px}
.st-c{background:rgba(0,212,255,.15);color:var(--c);border:1px solid rgba(0,212,255,.3)}
.st-c::before{content:'';display:inline-block;width:4px;height:4px;border-radius:50%;background:var(--c);animation:p 1.4s infinite}
.st-d{background:rgba(0,255,136,.12);color:var(--g);border:1px solid rgba(0,255,136,.3)}
.st-l{background:rgba(255,255,255,.04);color:rgba(255,255,255,.28);border:1px solid rgba(255,255,255,.08)}
.my{font-family:Orbitron,monospace;font-size:.48rem;font-weight:700;color:var(--m);margin-bottom:3px}
.mn{font-weight:700;font-size:.74rem;color:#fff;margin-bottom:4px;line-height:1.25}
.md{font-size:.54rem;color:var(--tt);line-height:1.4;margin-bottom:7px}
.mp{height:3px;background:rgba(255,255,255,.07);border-radius:2px;overflow:hidden}
.mpf{height:100%;background:linear-gradient(90deg,#005288,var(--c));transition:width 1s}
.tab{position:fixed;top:calc(78px + var(--st));right:0;z-index:50;display:flex;flex-direction:column;gap:2px}
.tb{min-width:40px;height:42px;border-radius:10px 0 0 10px;display:flex;align-items:center;justify-content:center;font-size:.85rem;cursor:pointer;border:1px solid;border-right:none;backdrop-filter:blur(14px);background:rgba(6,12,24,.9);padding:0 8px}
.tb-m{border-color:rgba(193,68,14,.5);color:var(--m)}
.tb-m.on{background:rgba(193,68,14,.3)}
.tb-w{border-color:rgba(0,200,160,.4);color:#00d4a0}
.tb-w.on{background:rgba(0,200,160,.2)}
.tb-b{border-color:rgba(150,100,255,.4);color:#aa88ff}
.tb-b.on{background:rgba(100,68,220,.25)}
.bot{position:fixed;bottom:calc(var(--sb) + 8px);left:60px;z-index:90;display:flex;gap:5px}
.bmc{background:#FFDD00;color:#000;border-radius:16px;padding:5px 10px;font-size:.56rem;font-weight:800;text-decoration:none;display:flex;align-items:center;gap:3px}
.wa{background:#25D366;color:#fff;border-radius:16px;padding:5px 10px;font-size:.56rem;font-weight:700;text-decoration:none;display:flex;align-items:center;gap:3px}
.lin{background:rgba(0,119,181,.88);color:#fff;border-radius:16px;padding:5px 10px;font-size:.56rem;font-weight:700;text-decoration:none;display:flex;align-items:center;gap:3px}
#a11y{position:fixed;bottom:calc(var(--sb) + 40px);left:8px;width:42px;height:42px;border-radius:50%;z-index:9990;background:linear-gradient(135deg,#005288,var(--c));border:2px solid rgba(0,212,255,.45);cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 18px rgba(0,212,255,.3)}
#a11y svg{width:22px;height:22px;pointer-events:none}
.pn{position:fixed;inset:0;z-index:500;background:rgba(2,4,8,.97);display:none;flex-direction:column;padding:14px;overflow-y:auto}
.pn.on{display:flex}
.pt{font-family:Orbitron,monospace;font-size:.95rem;font-weight:900;letter-spacing:2px;margin-bottom:10px;text-align:center}
.pc{align-self:flex-start;border-radius:8px;padding:7px 14px;cursor:pointer;font-family:Orbitron,monospace;font-size:.6rem;font-weight:700;margin-bottom:12px;border:1px solid;background:transparent}
.ms{width:min(360px,82vw);height:min(360px,82vw);border-radius:50%;border:2px solid rgba(193,68,14,.4);box-shadow:0 0 40px rgba(193,68,14,.2)}
.mw{position:relative;display:flex;justify-content:center;margin-bottom:12px}
.ml{position:absolute;display:flex;flex-direction:column;align-items:center;gap:2px;cursor:pointer;transform:translate(-50%,-50%)}
.mld{width:9px;height:9px;border-radius:50%;border:2px solid rgba(255,255,255,.8)}
.mll{font-family:Orbitron,monospace;font-size:.4rem;color:#fff;background:rgba(0,0,0,.85);padding:2px 4px;border-radius:3px;white-space:nowrap}
.d1{background:#ff5020;animation:p 2.5s infinite}
.d2{background:#c87844}
.d3{background:#8899aa}
.d4{background:#f5c842;animation:p 1.8s infinite}
.d5{background:#00ff88;animation:p 1.5s infinite}
.li{background:rgba(193,68,14,.08);border:1px solid rgba(193,68,14,.2);border-radius:10px;padding:11px;margin-bottom:12px;font-size:.7rem;color:var(--ts);line-height:1.6;display:none}
.fg{display:grid;grid-template-columns:repeat(auto-fit,minmax(95px,1fr));gap:7px}
.f{background:rgba(193,68,14,.07);border:1px solid rgba(193,68,14,.18);border-radius:8px;padding:9px;text-align:center}
.fv{font-family:Orbitron,monospace;font-size:.78rem;font-weight:700;color:var(--m)}
.fl{font-size:.46rem;color:var(--tt);margin-top:2px}
.wg{display:grid;grid-template-columns:repeat(auto-fit,minmax(115px,1fr));gap:9px;margin-bottom:12px}
.w{background:rgba(0,200,160,.06);border:1px solid rgba(0,200,160,.2);border-radius:10px;padding:11px;text-align:center}
.wv{font-family:Orbitron,monospace;font-size:.9rem;font-weight:700;color:#00d4a0;margin-bottom:3px}
.wl{font-size:.48rem;color:var(--tt);letter-spacing:1px;text-transform:uppercase}
.ws{font-size:.55rem;color:var(--ts);margin-top:3px}
.bc{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:9px 11px;display:flex;gap:9px;align-items:flex-start;margin-bottom:7px}
.bi{font-size:1.2rem;flex-shrink:0}
.bn{font-family:Orbitron,monospace;font-size:.54rem;font-weight:700;color:#fff;margin-bottom:2px}
.bo{font-size:.46rem;color:var(--tt);margin-bottom:3px}
.bd{font-size:.55rem;color:var(--ts);line-height:1.5}
.bs{font-family:Orbitron,monospace;font-size:.54rem;font-weight:700;letter-spacing:1.5px;margin:10px 0 7px;padding:4px 9px;border-radius:4px}
.bs1{color:var(--m);background:rgba(193,68,14,.1);border-right:3px solid var(--m)}
.bs2{color:#aa88ff;background:rgba(100,68,220,.1);border-right:3px solid #aa88ff}
.sh{position:fixed;inset:0;z-index:60;background:rgba(2,4,8,.82);backdrop-filter:blur(8px);display:none;align-items:flex-end}
.sh.on{display:flex}
.shi{width:100%;max-height:88vh;background:rgba(6,12,32,.99);border-radius:20px 20px 0 0;border-top:1px solid rgba(0,212,255,.22);overflow-y:auto;padding-bottom:calc(18px + var(--sb))}
.shh{width:34px;height:4px;background:rgba(255,255,255,.14);border-radius:2px;margin:12px auto 12px}
.sc{padding:0 18px}
.sy{font-family:Orbitron,monospace;font-size:.58rem;color:var(--m);font-weight:700}
.stl{font-family:Orbitron,monospace;font-size:1rem;font-weight:900;color:#fff;margin:5px 0 4px}
.ssb{font-size:.56rem;color:var(--tt);margin-bottom:11px}
.sd{font-size:.72rem;line-height:1.65;color:rgba(220,235,255,.82);margin-bottom:11px}
.sst{display:flex;flex-direction:column;gap:7px;margin-bottom:11px}
.sse{display:flex;gap:9px;align-items:flex-start}
.sn{width:19px;height:19px;border-radius:50%;flex-shrink:0;background:rgba(0,82,136,.44);border:1px solid var(--c);display:flex;align-items:center;justify-content:center;font-size:.5rem;font-weight:700;color:var(--c)}
.stx{font-size:.66rem;line-height:1.5;color:rgba(200,220,255,.75)}
.sq{background:rgba(245,200,66,.06);border:1px solid rgba(245,200,66,.18);border-radius:10px;padding:11px;margin-bottom:11px}
.sqt{font-size:.66rem;font-style:italic;color:rgba(245,200,66,.85);line-height:1.5}
.scl{width:100%;padding:12px;border-radius:13px;margin-top:13px;background:rgba(0,212,255,.1);border:1px solid rgba(0,212,255,.25);color:var(--c);font-size:.75rem;font-weight:600;cursor:pointer;font-family:Inter,sans-serif}
.mq{font-size:.78rem;font-style:italic;color:rgba(245,210,120,.92);line-height:1.65;border-right:3px solid var(--o);padding-right:11px;margin-bottom:11px}
#tst{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:rgba(6,12,32,.97);border:1px solid var(--c);border-radius:20px;padding:9px 18px;font-size:.66rem;z-index:88;display:none;white-space:nowrap;backdrop-filter:blur(14px)}
@keyframes ss{0%{opacity:0;transform:scaleX(0)}15%{opacity:1;transform:scaleX(1)}100%{opacity:0;transform:scaleX(1) translateX(200px)}}
.ss{position:fixed;height:1.5px;border-radius:50%;z-index:3;pointer-events:none;transform-origin:left center;background:linear-gradient(90deg,transparent,rgba(255,255,255,.9),rgba(200,220,255,.3));animation:ss .7s forwards}

.gb{position:fixed;top:calc(72px + var(--st) + 138px);right:0;z-index:50;min-width:40px;height:42px;border-radius:10px 0 0 10px;display:flex;align-items:center;justify-content:center;font-size:.85rem;cursor:pointer;border:1px solid rgba(255,200,40,.5);border-right:none;backdrop-filter:blur(14px);background:rgba(6,12,24,.9);color:#ffc828;padding:0 8px;animation:gp 2s infinite}
@keyframes gp{50%{box-shadow:-4px 0 18px rgba(255,200,40,.5)}}
.gb.on{background:rgba(255,200,40,.25)}
.gx{font-size:.5rem;margin-right:3px}
#gm{position:fixed;inset:0;z-index:600;background:linear-gradient(135deg,rgba(8,4,24,.98),rgba(20,8,4,.98));display:none;flex-direction:column;overflow-y:auto;padding:calc(20px + var(--st)) 14px calc(20px + var(--sb))}
#gm.on{display:flex}
.gcl{position:absolute;top:calc(14px + var(--st));left:14px;width:38px;height:38px;border-radius:50%;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.15);color:#fff;font-size:1.1rem;cursor:pointer;z-index:601}
.gt{font-family:Orbitron,monospace;font-size:1.2rem;font-weight:900;text-align:center;background:linear-gradient(90deg,#ffc828,var(--m),var(--c));-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px;letter-spacing:2px}
.gst{font-size:.55rem;color:var(--tt);text-align:center;letter-spacing:2px;margin-bottom:18px}
.gstat{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:14px}
.gs{background:linear-gradient(135deg,rgba(255,200,40,.08),rgba(255,200,40,.02));border:1px solid rgba(255,200,40,.25);border-radius:12px;padding:11px 6px;text-align:center}
.gsv{font-family:Orbitron,monospace;font-size:1.1rem;font-weight:900;background:linear-gradient(135deg,#ffc828,#ff8800);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.gsl{font-size:.42rem;color:var(--tt);letter-spacing:1px;text-transform:uppercase;margin-top:3px}
.gsi{font-size:.85rem;margin-bottom:2px}
.glv{background:rgba(0,212,255,.06);border:1px solid rgba(0,212,255,.15);border-radius:12px;padding:12px;margin-bottom:14px}
.glvh{display:flex;justify-content:space-between;align-items:center;margin-bottom:7px}
.glvn{font-family:Orbitron,monospace;font-size:.7rem;font-weight:700;color:var(--c)}
.glvx{font-size:.5rem;color:var(--tt)}
.glvb{height:6px;background:rgba(255,255,255,.08);border-radius:3px;overflow:hidden}
.glvf{height:100%;background:linear-gradient(90deg,var(--c),var(--g));border-radius:3px;transition:width 1s}
.dq{background:linear-gradient(135deg,rgba(0,255,136,.08),rgba(0,255,136,.02));border:1px solid rgba(0,255,136,.25);border-radius:12px;padding:13px;margin-bottom:14px}
.dqh{display:flex;align-items:center;gap:6px;margin-bottom:5px}
.dqt{font-family:Orbitron,monospace;font-size:.55rem;color:var(--g);font-weight:700;letter-spacing:1.5px}
.dqq{font-size:.78rem;font-weight:600;color:#fff;margin-bottom:7px;line-height:1.4}
.dqp{height:5px;background:rgba(255,255,255,.08);border-radius:2px;overflow:hidden;margin-bottom:4px}
.dqpf{height:100%;background:linear-gradient(90deg,var(--g),#88ff88);border-radius:2px;transition:width 1s}
.dqx{font-size:.5rem;color:var(--tt);text-align:right}
.qzh{font-family:Orbitron,monospace;font-size:.6rem;font-weight:700;color:#fff;margin-bottom:10px;display:flex;align-items:center;gap:6px}
.qz{background:rgba(176,96,255,.06);border:1px solid rgba(176,96,255,.2);border-radius:12px;padding:13px;margin-bottom:14px}
.qzq{font-size:.85rem;font-weight:600;color:#fff;margin-bottom:11px;line-height:1.4;text-align:center}
.qza{display:grid;grid-template-columns:1fr 1fr;gap:7px}
.qab{padding:11px;border-radius:10px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);color:#fff;font-size:.66rem;font-weight:600;cursor:pointer;font-family:Inter,sans-serif;transition:all .2s;text-align:center;min-height:50px}
.qab:active{transform:scale(.95)}
.qab.ok{background:rgba(0,255,136,.25);border-color:var(--g);animation:wn .5s}
.qab.no{background:rgba(255,56,96,.25);border-color:#ff3860}
@keyframes wn{0%,100%{transform:scale(1)}50%{transform:scale(1.08)}}
.ach{display:grid;grid-template-columns:repeat(auto-fit,minmax(80px,1fr));gap:7px;margin-bottom:14px}
.acit{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:10px 5px;text-align:center;transition:all .25s;cursor:pointer}
.acit.un{background:linear-gradient(135deg,rgba(255,200,40,.12),rgba(255,140,40,.06));border-color:rgba(255,200,40,.4);box-shadow:0 0 12px rgba(255,200,40,.15)}
.acit.un .aci{filter:none}
.aci{font-size:1.6rem;margin-bottom:4px;filter:grayscale(1) opacity(.3)}
.acn{font-size:.4rem;color:var(--ts);font-weight:600;line-height:1.2}
.shx{width:100%;padding:13px;border-radius:14px;background:linear-gradient(135deg,#25D366,#128C7E);color:#fff;font-size:.78rem;font-weight:700;cursor:pointer;border:none;font-family:Inter,sans-serif;display:flex;align-items:center;justify-content:center;gap:6px}
.cob{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);font-family:Orbitron,monospace;font-size:2.5rem;font-weight:900;color:#ffc828;text-shadow:0 0 30px #ffc828;z-index:999;pointer-events:none;opacity:0}
.cob.go{animation:co 1.5s forwards}
@keyframes co{0%{opacity:0;transform:translate(-50%,-50%) scale(.5)}30%{opacity:1;transform:translate(-50%,-50%) scale(1.3)}70%{opacity:1;transform:translate(-50%,-100%) scale(1)}100%{opacity:0;transform:translate(-50%,-150%) scale(.8)}}

/* ONBOARDING */
#onb{position:fixed;inset:0;z-index:9999;background:rgba(2,4,8,.96);backdrop-filter:blur(20px);display:none;flex-direction:column;align-items:center;justify-content:center;padding:20px}
#onb.on{display:flex}
.ob-card{background:linear-gradient(145deg,rgba(6,14,32,.98),rgba(10,20,44,.95));border:1px solid rgba(0,212,255,.3);border-radius:24px;padding:24px 22px;max-width:340px;width:100%;text-align:center;box-shadow:0 20px 60px rgba(0,212,255,.15)}
.ob-emj{font-size:3rem;margin-bottom:10px;animation:bnc 2s infinite}
@keyframes bnc{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
.ob-t{font-family:Orbitron,monospace;font-size:1.1rem;font-weight:900;background:linear-gradient(90deg,#fff,var(--c),var(--m));-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px;letter-spacing:1.5px}
.ob-d{font-size:.78rem;color:var(--ts);line-height:1.65;margin-bottom:16px}
.ob-l{text-align:right;background:rgba(0,212,255,.05);border:1px solid rgba(0,212,255,.12);border-radius:12px;padding:11px 13px;margin-bottom:14px}
.ob-li{display:flex;align-items:center;gap:8px;font-size:.66rem;color:var(--ts);margin-bottom:6px;line-height:1.4}
.ob-li:last-child{margin-bottom:0}
.ob-ic{font-size:.95rem;width:22px;text-align:center;flex-shrink:0}
.ob-btn{width:100%;padding:12px;border-radius:14px;background:linear-gradient(135deg,#005288,var(--c));border:none;color:#fff;font-size:.82rem;font-weight:700;cursor:pointer;font-family:Inter,sans-serif;margin-bottom:8px;box-shadow:0 4px 18px rgba(0,212,255,.3)}
.ob-skp{background:transparent;border:none;color:var(--tt);font-size:.62rem;cursor:pointer;text-decoration:underline}
.ob-dt{display:flex;justify-content:center;gap:6px;margin-bottom:14px}
.ob-d2{width:7px;height:7px;border-radius:50%;background:rgba(255,255,255,.2);transition:all .3s}
.ob-d2.on{background:var(--c);width:24px;border-radius:4px}
/* HELP BUTTON */
#hlp{position:fixed;top:calc(72px + var(--st) + 92px);right:0;z-index:50;min-width:40px;height:42px;border-radius:10px 0 0 10px;display:flex;align-items:center;justify-content:center;font-size:.85rem;cursor:pointer;border:1px solid rgba(0,255,136,.4);border-right:none;backdrop-filter:blur(14px);background:rgba(6,12,24,.9);color:var(--g);padding:0 8px}
#hlp:active{background:rgba(0,255,136,.2)}
/* TOOLTIP */
.tt-h{position:fixed;background:rgba(0,212,255,.95);color:#000;border-radius:8px;padding:7px 11px;font-size:.6rem;font-weight:700;z-index:9998;pointer-events:none;animation:tth .4s;white-space:nowrap;box-shadow:0 4px 20px rgba(0,212,255,.4)}
@keyframes tth{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.tt-h::before{content:'';position:absolute;border:6px solid transparent}
.tt-h.r::before{right:-12px;top:50%;transform:translateY(-50%);border-left-color:rgba(0,212,255,.95)}
@media(max-width:380px){.vs{display:none}}
</style>
</head>
<body>
<canvas id="bg"></canvas>
<header class="hdr">
<div class="lg">
<span class="l l-x">SpaceX</span>
<span class="l l-n">NASA</span>
<a href="https://kombaz.net" target="_blank" class="l l-w">NET ↗</a>
<a href="https://kombaz.co" target="_blank" class="l l-co">CO ↗</a>
</div>
<div class="hr">
<div class="tt"><h1>MARS 2045</h1><p>KOMBAZ.ME</p></div>
<div class="live"><div class="dot"></div><span class="lt">LIVE</span></div>
</div>
</header>
<div class="tab">
<button class="tb tb-m" id="tb-m" onclick="tp('p-m','tb-m')">🗺</button>
<button class="tb tb-w" id="tb-w" onclick="tp('p-w','tb-w')">🌡</button>
<button class="tb tb-b" id="tb-b" onclick="tp('p-b','tb-b')">🏗</button>
</div>
<div id="p-m" class="pn">
<button class="pc" onclick="tp('p-m','tb-m')" style="background:rgba(193,68,14,.1);border-color:rgba(193,68,14,.3);color:var(--m)">✕ סגור</button>
<div class="pt" style="color:var(--m)">🔴 מפת מאדים</div>
<div class="mw">
<svg class="ms" viewBox="0 0 400 400"><defs><radialGradient id="mg" cx="38%" cy="35%"><stop offset="0%" stop-color="#e8622a"/><stop offset="45%" stop-color="#c1440e"/><stop offset="100%" stop-color="#6a1e04"/></radialGradient></defs>
<circle cx="200" cy="200" r="195" fill="url(#mg)"/>
<ellipse cx="200" cy="26" rx="55" ry="22" fill="rgba(232,236,240,.9)"/>
<path d="M110 200 Q155 196 195 201 Q235 206 288 198" stroke="#7a2808" stroke-width="7" fill="none" stroke-linecap="round" opacity=".8"/>
<ellipse cx="280" cy="290" rx="55" ry="38" fill="#7a1e04" opacity=".55"/>
<circle cx="110" cy="165" r="22" fill="#d04020" opacity=".65"/>
<ellipse cx="232" cy="152" rx="58" ry="33" fill="#d06030" opacity=".22"/>
</svg>
<div class="ml" style="left:27.5%;top:41.3%" onclick="sl('o')"><div class="mld d1"></div><div class="mll">Olympus</div></div>
<div class="ml" style="left:49%;top:50.5%" onclick="sl('v')"><div class="mld d2"></div><div class="mll">Valles</div></div>
<div class="ml" style="left:70%;top:72.5%" onclick="sl('h')"><div class="mld d3"></div><div class="mll">Hellas</div></div>
<div class="ml" style="left:61%;top:46%" onclick="sl('j')"><div class="mld d4"></div><div class="mll">🔭 Jezero</div></div>
<div class="ml" style="left:37%;top:59%" onclick="sl('c')"><div class="mld d5"></div><div class="mll">🏙 Colony</div></div>
</div>
<div id="li" class="li"></div>
<div class="fg">
<div class="f"><div class="fv">-63°C</div><div class="fl">טמפ'</div></div>
<div class="f"><div class="fv">0.6 hPa</div><div class="fl">לחץ</div></div>
<div class="f"><div class="fv">24h 37m</div><div class="fl">Sol</div></div>
<div class="f"><div class="fv">21.9 km</div><div class="fl">Olympus</div></div>
<div class="f"><div class="fv">4,000 km</div><div class="fl">Valles</div></div>
<div class="f"><div class="fv" id="sf">1876</div><div class="fl">Sol נוכחי</div></div>
</div>
</div>
<div id="p-w" class="pn">
<button class="pc" onclick="tp('p-w','tb-w')" style="background:rgba(0,200,160,.08);border-color:rgba(0,200,160,.25);color:#00d4a0">✕ סגור</button>
<div class="pt" style="color:#00d4a0">🌡 מזג אוויר Jezero</div>
<div class="wg">
<div class="w"><div class="wv" id="wt">-60°C</div><div class="wl">טמפרטורה</div><div class="ws">מקס: -20°C</div></div>
<div class="w"><div class="wv" id="wp">750 Pa</div><div class="wl">לחץ</div><div class="ws">Jezero</div></div>
<div class="w"><div class="wv" id="ws">1876</div><div class="wl">Sol</div><div class="ws">ימים</div></div>
<div class="w"><div class="wv">CO₂ 95%</div><div class="wl">אטמוספירה</div><div class="ws">N₂ 2.6%</div></div>
<div class="w"><div class="wv">~5 m/s</div><div class="wl">רוח</div><div class="ws">NNE</div></div>
<div class="w"><div class="wv">0 mm</div><div class="wl">משקעים</div><div class="ws">עונת CO₂</div></div>
</div>
<div style="font-size:.66rem;color:var(--ts);padding:9px;background:rgba(245,200,66,.05);border:1px solid rgba(245,200,66,.15);border-radius:8px">📡 NASA InSight + Perseverance MEDA</div>
</div>
<div id="p-b" class="pn">
<button class="pc" onclick="tp('p-b','tb-b')" style="background:rgba(100,68,220,.08);border-color:rgba(150,100,255,.25);color:#aa88ff">✕ סגור</button>
<div class="pt" style="color:#aa88ff">🏗️ בוני עיר מאדים</div>
<div class="bs bs1">🏗 הדפסה תלת-ממדית</div>
<div class="bc"><div class="bi">🏗</div><div><div class="bn">ICON Vulcan</div><div class="bo">🇺🇸 Austin · NASA</div><div class="bd">Project Olympus.</div></div></div>
<div class="bc"><div class="bi">🏛</div><div><div class="bn">COBOD BOD2</div><div class="bo">🇩🇰 Denmark</div><div class="bd">בניינים 100m+.</div></div></div>
<div class="bs bs2">🤖 רובוטים</div>
<div class="bc"><div class="bi">⚡</div><div><div class="bn">Tesla Optimus</div><div class="bo">🇺🇸 1,000+ units</div><div class="bd">$20K target.</div></div></div>
<div class="bc"><div class="bi">🦾</div><div><div class="bn">Figure 02</div><div class="bo">🇺🇸 BMW + OpenAI</div><div class="bd">1M units 2030.</div></div></div>
<div class="bc"><div class="bi">🏃</div><div><div class="bn">Boston Atlas</div><div class="bo">🇺🇸 Hyundai</div><div class="bd">Electric autonomous.</div></div></div>
<div class="bc"><div class="bi">🐕</div><div><div class="bn">Unitree G1</div><div class="bo">🇨🇳 $16K</div><div class="bd">Mars workforce.</div></div></div>
</div>
<div class="bot">
<a href="https://buymeacoffee.com/kombaz" target="_blank" class="bmc">☕ Support</a>
<a href="https://www.linkedin.com/in/shai-kombaz-bb373a353" target="_blank" class="lin">🔗 LinkedIn</a>
<a href="https://wa.me/972XXXXXXXXX?text=%D7%94%D7%99%D7%99%20%D7%A9%D7%99%2C%20%D7%A8%D7%90%D7%99%D7%AA%D7%99%20%D7%90%D7%AA%20KOMBAZ.ME%20%F0%9F%9A%80" target="_blank" class="wa">💬 WhatsApp</a>
</div>
<button id="a11y" onclick="tst('♿ זמין ב-Desktop')"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="5" r="1.8"/><path d="M12 7v5M8 10l4 2 4-2M9 22l1.5-5M15 22l-1.5-5M5 11h4M15 11h4"/></svg></button>
<main class="main">
<div class="hero">
<div class="yr" id="yb">2026</div>
<div class="ph" id="yp">טרום-מאדים</div>
<div class="pb"><div class="pbf" id="yf" style="width:0%"></div></div>
</div>
<div class="vs">
<div class="vc"><div class="vh">🛸 VOYAGER 1</div>
<div class="vr"><span class="vl">AU</span><span class="vv vg" id="v1a">172.6</span></div>
<div class="vr"><span class="vl">km</span><span class="vv" id="v1k">25.8B</span></div>
<div class="vr"><span class="vl">אות</span><span class="vv vo" id="v1d">23h 54m</span></div>
<div class="vm" id="v1m">⏳ יום-אור בעוד 210 ימים</div></div>
<div class="vc"><div class="vh">🛸 VOYAGER 2</div>
<div class="vr"><span class="vl">AU</span><span class="vv vg" id="v2a">143.1</span></div>
<div class="vr"><span class="vl">אות</span><span class="vv vo" id="v2d">19h 53m</span></div></div>
<div class="vc"><div class="vh">🔭 PERSEVERANCE</div>
<div class="vr"><span class="vl">Sol</span><span class="vv vo" id="ps">1876</span></div>
<div class="vr"><span class="vl">דגימות</span><span class="vv vg">24</span></div>
<div class="vr"><span class="vl">MOXIE</span><span class="vv vg">✅</span></div></div>
</div>
<div class="z"><div class="zl">פעילות</div><div class="zb"><div class="zf" id="zf" style="width:0%"></div></div><div class="zn" id="zn">0/17</div></div>
<div class="cb">
<button class="b b-n" onclick="cy(-1)">◀ קודם</button>
<div class="yd" id="yd">2026</div>
<button class="b b-n" onclick="cy(1)">הבא ▶</button>
<button class="b b-a" id="ab" onclick="ta()">⚡ Auto</button>
<button class="b b-m" onclick="om()">💬 מאסק</button>
</div>
<div class="ft">
<div class="ftb on" onclick="sf('all',this)">🌐 הכל</div>
<div class="ftb" onclick="sf('spacex',this)">🚀 SpaceX</div>
<div class="ftb" onclick="sf('nasa',this)">🛸 NASA</div>
<div class="ftb" onclick="sf('colony',this)">🏙 מושבה</div>
<div class="ftb" onclick="sf('infra',this)">⚡ תשתית</div>
<div class="ftb" onclick="sf('robots',this)">🤖 רובוטים</div>
<div class="ftb" onclick="sf('perseverance',this)">🔭 Rover</div>
</div>
<div class="cs" id="cs"></div>
</main>
<div class="sh" id="dt" onclick="if(event.target===this)cd()"><div class="shi"><div class="shh"></div><div class="sc">
<div class="sy" id="sy"></div>
<h2 class="stl" id="stt"></h2>
<div class="ssb" id="ssb"></div>
<p class="sd" id="sd"></p>
<div class="sst" id="sst"></div>
<div class="sq"><p class="sqt" id="sqt"></p></div>
<button class="scl" onclick="cd()">סגור ✕</button>
</div></div></div>
<div class="sh" id="mk" onclick="if(event.target===this)cm()"><div class="shi"><div class="shh"></div><div class="sc">
<div style="font-family:Orbitron,monospace;font-size:.65rem;font-weight:700;color:var(--o);margin-bottom:12px">💬 אילון מאסק</div>
<div class="mq" id="mq"></div>
<div style="font-size:.54rem;color:var(--tt)">— Elon Musk, SpaceX CEO</div>
<div style="display:flex;gap:6px;margin-top:11px;justify-content:center" id="md"></div>
<button class="scl" style="background:rgba(245,200,66,.08);border-color:rgba(245,200,66,.2);color:var(--o)" onclick="cm()">סגור ✕</button>
</div></div></div>
<div id="tst"></div>

<button id="hlp" onclick="oo()" title="עזרה">❓</button>

<div id="onb">
<div class="ob-card" id="ob-c"></div>
</div>


<button class="gb" id="gb" onclick="og()">🎮<span class="gx">משחק</span></button>

<div id="gm">
<button class="gcl" onclick="cgm()">✕</button>
<div class="gt">🚀 MISSION MARS</div>
<div class="gst">המשחק של KOMBAZ</div>

<div class="gstat">
<div class="gs"><div class="gsi">💎</div><div class="gsv" id="gs-c">0</div><div class="gsl">KOMBAZ</div></div>
<div class="gs"><div class="gsi">🔥</div><div class="gsv" id="gs-s">0</div><div class="gsl">Streak</div></div>
<div class="gs"><div class="gsi">⭐</div><div class="gsv" id="gs-l">1</div><div class="gsl">Level</div></div>
</div>

<div class="glv">
<div class="glvh"><span class="glvn" id="lv-n">🌍 Earthling</span><span class="glvx" id="lv-x">0 / 100 XP</span></div>
<div class="glvb"><div class="glvf" id="lv-f" style="width:0%"></div></div>
</div>

<div class="dq">
<div class="dqh"><span style="font-size:1rem">🎯</span><span class="dqt">משימה יומית</span></div>
<div class="dqq" id="dq-q">לחץ על 3 משימות שונות</div>
<div class="dqp"><div class="dqpf" id="dq-f" style="width:0%"></div></div>
<div class="dqx" id="dq-x">0/3 · פרס: 50 💎</div>
</div>

<div class="qz">
<div class="qzh">🧠 חידון מהיר <span style="color:var(--o);font-size:.5rem">+25 💎</span></div>
<div class="qzq" id="qz-q">טוען...</div>
<div class="qza" id="qz-a"></div>
</div>

<div class="qzh">🏆 הישגים <span id="ach-x" style="color:var(--tt);font-size:.5rem">0/12</span></div>
<div class="ach" id="ach"></div>

<button class="shx" onclick="shr()">💬 שתף ב-WhatsApp</button>
</div>

<div class="cob" id="cob"></div>

<script>
const cv=document.getElementById('bg'),x=cv.getContext('2d');
function rs(){cv.width=innerWidth;cv.height=innerHeight;ds()}
function ds(){x.clearRect(0,0,cv.width,cv.height);const n=innerWidth<480?500:1200;for(let i=0;i<n;i++){const xa=Math.random()*cv.width,ya=Math.random()*cv.height,r=Math.random(),s=r>.97?2.2:r>.9?1.4:.7,a=.4+Math.random()*.6;x.fillStyle=r>.93?`rgba(255,220,150,${a})`:r>.86?`rgba(180,200,255,${a})`:`rgba(220,235,255,${a})`;x.beginPath();x.arc(xa,ya,s,0,Math.PI*2);x.fill()}}
addEventListener('resize',rs);rs();
setInterval(()=>{const xa=Math.random()*cv.width,ya=Math.random()*cv.height,s=1+Math.random()*2;x.fillStyle=`rgba(255,255,255,${.3+Math.random()*.7})`;x.beginPath();x.arc(xa,ya,s,0,Math.PI*2);x.fill();setTimeout(()=>x.clearRect(xa-s-1,ya-s-1,s*2+2,s*2+2),600)},80);
function ssp(){const s=document.createElement('div');s.className='ss';s.style.cssText=`width:${60+Math.random()*140}px;top:${Math.random()*innerHeight*.4}px;left:${Math.random()*innerWidth*.65}px;transform:rotate(${Math.random()*40-20}deg)`;document.body.appendChild(s);setTimeout(()=>s.remove(),800)}
setInterval(()=>{Math.random()<.35&&ssp()},2800);
const V1A=172.59,V1S=17.043,V2A=143.10,V2S=15.40,AU=149597870.7,LK=299792.458,RM=Date.UTC(2026,3,19),MS=Date.UTC(2026,10,15);
function uv(){const n=Date.now(),s=(n-RM)/1000,v1k=V1A*AU+V1S*s,v1a=v1k/AU,v1d=v1k/LK,v2k=V2A*AU+V2S*s,v2a=v2k/AU,v2d=v2k/LK,fh=t=>Math.floor(t/3600)+'h '+String(Math.floor((t%3600)/60)).padStart(2,'0')+'m',fk=k=>k>=1e9?(k/1e9).toFixed(2)+'B':(k/1e6).toFixed(0)+'M';
document.getElementById('v1a').textContent=v1a.toFixed(2);
document.getElementById('v1k').textContent=fk(v1k);
document.getElementById('v1d').textContent=fh(v1d);
document.getElementById('v2a').textContent=v2a.toFixed(2);
document.getElementById('v2d').textContent=fh(v2d);
const m=document.getElementById('v1m'),dl=Math.max(0,Math.round((MS-n)/86400000));m.textContent=n>MS?'🎉 הגיע ליום-אור!':`⏳ יום-אור בעוד ${dl} ימים`}
uv();setInterval(uv,30000);
const LD=new Date('2021-02-18T20:55:00Z').getTime(),SM=88775244;
function gs(){return Math.floor((Date.now()-LD)/SM)}
function us(){const s=gs().toLocaleString();['ps','ws','sf'].forEach(i=>{const e=document.getElementById(i);if(e)e.textContent=s});const r=gs(),si=Math.sin(r/668*2*Math.PI),et=document.getElementById('wt'),ep=document.getElementById('wp');if(et)et.textContent=Math.round(-60+si*18)+'°C';if(ep)ep.textContent=Math.round(750+si*90)+' Pa'}
us();setInterval(us,60000);
fetch('https://api.nasa.gov/mars-photos/api/v1/rovers/perseverance/latest_photos?api_key=DEMO_KEY',{signal:AbortSignal.timeout(6000)}).then(r=>r.json()).then(d=>{if(d.latest_photos&&d.latest_photos[0]){const s=d.latest_photos[0].sol.toLocaleString();['ps','ws','sf'].forEach(i=>{const e=document.getElementById(i);if(e)e.textContent=s})}}).catch(()=>{});
const M=[
{id:'pv',y:2026,c:'perseverance',n:'🔭 Perseverance Live',d:'Rover ב-Jezero Crater. Sol 1,876+. 24 דגימות סלע. MOXIE פעיל.',s:['Jezero Crater','24 דגימות','MOXIE: O₂ ✅','Ingenuity: 72 טיסות'],q:'Perseverance is proof Mars is within reach.',t:['nasa','critical']},
{id:'mx',y:2026,c:'perseverance',n:'⚗️ MOXIE — O₂ ממאדים',d:'ייצור חמצן מ-CO₂. פריצת דרך היסטורית.',s:['16 הפעלות','98% purity','Proven ISRU'],q:'MOXIE is the first ISRU on Mars.',t:['nasa','infra']},
{id:'op',y:2026,c:'robots',n:'🤖 Tesla Optimus Gen 2',d:'1,000+ units 2026. גרסת מאדים בפיתוח.',s:['1,000+ units','$20K target','Bipedal'],q:'Optimus will be more valuable than the car business.',t:['robots']},
{id:'at',y:2026,c:'robots',n:'⚡ Boston Dynamics Atlas',d:'Electric Atlas 2024. Hyundai. Benchmark עולמי.',s:['Electric autonomous','Hyundai factory','Most agile'],q:'Atlas shows what robots can do.',t:['robots']},
{id:'sx',y:2026,c:'spacex',n:'🚀 Starship — שלמות מלאה',d:'130 מנועי Raptor 3. 100+ טון מטען.',s:['130+ Raptor 3','24h turnaround','LEO transfer'],q:'Starship is the most important development in space.',t:['spacex','critical']},
{id:'sl',y:2026,c:'infra',n:'🛰️ Starlink V3',d:'10,000 לוויני V3. אינטרנט גלובלי.',s:['10,000 sats','Laser mesh','<30ms latency'],q:'Starlink funds Mars.',t:['spacex','infra']},
{id:'fg',y:2027,c:'robots',n:'🦾 Figure 02',d:'BMW + OpenAI. 1M units by 2030.',s:['BMW partner','OpenAI brain','Mars-ready'],q:'Humanoid robots are the future.',t:['robots']},
{id:'ic',y:2027,c:'robots',n:'🏗️ ICON Print 3D',d:'Project Olympus. NASA contract.',s:['NASA contract','Regolith','24h habitat'],q:'We will print structures on Mars.',t:['robots','colony']},
{id:'ar',y:2027,c:'nasa',n:'🌙 Artemis IV',d:'Starship HLS מנחיתה. בסיס ירח קבע.',s:['Starship HLS','Lunar ISRU','6-month hab'],q:'The Moon is stepping stone to Mars.',t:['nasa']},
{id:'pr',y:2028,c:'spacex',n:'🛸 Precursor',d:'2 Starships אוטומטיים. ייצור מתאן ראשון.',s:['2 uncrewed','Aerobraking','ISRU deployed'],q:'Without ISRU, one-way trip.',t:['spacex','critical']},
{id:'fl',y:2029,c:'spacex',n:'📦 Cargo Fleet',d:'5 Starships. ציוד ל-2 שנים.',s:['5 cargo Starships','Nuclear 40MW','Rovers'],q:'You want redundancy.',t:['spacex','colony']},
{id:'hu',y:2030,c:'colony',n:'🧑‍🚀 בני-אדם ראשונים!',d:'12 אנשים נוחתים. 7 חודשי מעבר.',s:['Crew of 12','7-month transit','Landing'],q:'The first to Mars will be the bravest ever.',t:['spacex','critical']},
{id:'is',y:2031,c:'infra',n:'⚗️ ISRU דלק',d:'מפעל מתאן+O₂. Starships חוזרות.',s:['CO₂ electrolysis','Water mining','10t CH₄/day'],q:'Propellant on Mars = accessibility.',t:['spacex','critical']},
{id:'c1',y:2033,c:'colony',n:'🏙️ Mars City P1',d:'100 תושבים. מבנים מ-regolith.',s:['ICON printers','Tunnels','40% food','40MW'],q:'First Mars city built by robots.',t:['colony','robots']},
{id:'k1',y:2038,c:'colony',n:'🏛️ 1,000 תושבים',d:'אלף תושבים. כלכלה ראשונה.',s:['10 Starships/window','80% food','First economy'],q:'1,000 people = civilization begins.',t:['colony']},
{id:'tr',y:2040,c:'infra',n:'🔥 Terraforming',d:'מראות מסלוליות + גזי חממה.',s:['Space mirrors','CO₂ sublime','+5°C'],q:'We should terraform Mars.',t:['infra']},
{id:'mi',y:2050,c:'colony',n:'🌍 מיליון בני-אדם!',d:'מיליון תושבים עצמאיים.',s:['1,000 Starships','Self-sustaining','Constitution'],q:'Die on Mars — not on impact.',t:['colony','critical']}
];
const Q=['"אם לא נהפוך לציוויליזציה רב-כוכבית, כל הביצים בסל אחד."','"Starship הוא כלי התחבורה החשוב ביותר שנבנה."','"אני רוצה למות על מאדים — רק לא בפגיעה."','"מאדים הוא פוליסת הביטוח של האנושות."','"בלי ISRU — כרטיסייה לכיוון אחד בלבד."'];
const PH={2026:'טרום-מאדים',2028:'Precursor',2030:'בני-אדם ראשונים!',2033:'מושבה ראשונה',2038:'גדילה',2045:'עיר מאדים',2050:'🏆 מיליון!'};
const CM={spacex:{a:'a-x',i:'🚀'},nasa:{a:'a-n',i:'🛸'},colony:{a:'a-c',i:'🏙'},infra:{a:'a-i',i:'⚡'},robots:{a:'a-r',i:'🤖'},perseverance:{a:'a-p',i:'🔭'}};
let cy_=2026,cf='all',ao=false,at_,mi=0;
const dn=new Set();
function gm(m){if(dn.has(m.id))return'd';if(m.c==='robots'||m.c==='perseverance')return'c';if(cy_>=m.y-1)return'c';return'l'}
function gp(y){let p='טרום-מאדים';for(const[k,v]of Object.entries(PH))if(y>=+k)p=v;return p}
function rc(){const g=document.getElementById('cs');g.innerHTML='';M.filter(m=>cf==='all'||m.c===cf).forEach(m=>{const st=gm(m),pg=st==='d'?100:st==='c'?Math.min(100,Math.floor(((cy_-2025)/(m.y-2025))*100)):0,cm=CM[m.c]||{a:'a-x',i:'🚀'},ac=m.t.includes('critical')&&st!=='d'?'a-cr':cm.a,d=m.d,ct=d.substring(0,68),i=ct.lastIndexOf(' '),pv=(i>30?ct.substring(0,i):ct)+'…',dv=document.createElement('div');dv.className='cd'+(st==='c'?' cu':'')+(st==='d'?' do':'')+(st==='l'?' lk':'');dv.innerHTML='<div class="ac '+ac+'"></div><div class="cb2"><div class="st st-'+st+'">'+(st==='d'?'✓ הושלם':st==='c'?'פעיל':'נעול')+'</div><div class="my">'+cm.i+' '+m.y+'</div><div class="mn">'+m.n+'</div><div class="md">'+pv+'</div><div class="mp"><div class="mpf" style="width:'+pg+'%"></div></div></div>';if(st!=='l'){dv.onclick=()=>od(m);dv.addEventListener('touchstart',()=>navigator.vibrate&&navigator.vibrate(8),{passive:true})}g.appendChild(dv)});uz()}
function uz(){const a=M.filter(m=>gm(m)==='c'&&!dn.has(m.id)).length;document.getElementById('zf').style.width=(a/M.length*100)+'%';document.getElementById('zn').textContent=a+'/'+M.length}
function sf(f,e){cf=f;document.querySelectorAll('.ftb').forEach(t=>t.classList.remove('on'));e.classList.add('on');rc()}
function cy(d){cy_=Math.max(2026,Math.min(2052,cy_+d));M.forEach(m=>{if(m.y<=cy_-1)dn.add(m.id)});const ph=gp(cy_),pc=Math.min(100,((cy_-2026)/24)*100);document.getElementById('yb').textContent=cy_;document.getElementById('yd').textContent=cy_;document.getElementById('yp').textContent=ph;document.getElementById('yf').style.width=pc+'%';const w=M.filter(m=>m.y>cy_&&!dn.has(m.id)).length;tst('📅 '+cy_+' — '+ph+(w?' · '+w+' ממתינות':''));navigator.vibrate&&navigator.vibrate(6);rc()}
function ta(){ao=!ao;document.getElementById('ab').classList.toggle('on',ao);if(ao){at_=setInterval(()=>cy(1),1800);tst('⚡ Auto פעיל')}else{clearInterval(at_);tst('⏹ Auto עצר')}}
function od(m){document.getElementById('sy').textContent=m.y;document.getElementById('stt').textContent=m.n;document.getElementById('ssb').textContent=m.c+' — KOMBAZ.ME';document.getElementById('sd').textContent=m.d;document.getElementById('sqt').textContent='"'+m.q+'"';document.getElementById('sst').innerHTML=m.s.map((x,i)=>'<div class="sse"><div class="sn">'+(i+1)+'</div><div class="stx">'+x+'</div></div>').join('');document.getElementById('dt').classList.add('on')}
function cd(){document.getElementById('dt').classList.remove('on')}
function om(){rm();document.getElementById('mk').classList.add('on');clearInterval(window._mt);window._mt=setInterval(()=>{mi=(mi+1)%Q.length;rm()},4500)}
function cm(){document.getElementById('mk').classList.remove('on');clearInterval(window._mt)}
function rm(){document.getElementById('mq').textContent=Q[mi];document.getElementById('md').innerHTML=Q.map((_,i)=>'<button style="width:7px;height:7px;border-radius:50%;background:'+(i===mi?'var(--o)':'rgba(245,200,66,.22)')+';border:none" onclick="mi='+i+';rm()"></button>').join('')}
function tp(id,bi){const p=document.getElementById(id),io=p.classList.contains('on');document.querySelectorAll('.pn').forEach(x=>x.classList.remove('on'));document.querySelectorAll('.tb').forEach(x=>x.classList.remove('on'));if(!io){p.classList.add('on');document.getElementById(bi).classList.add('on')}}
function sl(i){const D={o:{n:'Olympus Mons',t:'גובה: 21.9 km. הר הגעש הגדול.'},v:{n:'Valles Marineris',t:'אורך: 4,000 km. עומק: 7 km.'},h:{n:'Hellas Planitia',t:'קוטר: 2,300 km. אידיאלי לישוב.'},j:{n:'Jezero Crater 🔭',t:'Sol: '+gs().toLocaleString()+'. 24 דגימות.'},c:{n:'Colony 2045 🏙',t:'מיקום מושבה מתוכנן.'}}[i];if(!D)return;const e=document.getElementById('li');e.style.display='block';e.innerHTML='<strong style="color:var(--m);font-family:Orbitron,monospace;font-size:.6rem">'+D.n+'</strong><br><br>'+D.t}
let tt_;function tst(m){const e=document.getElementById('tst');e.textContent=m;e.style.display='block';clearTimeout(tt_);tt_=setTimeout(()=>e.style.display='none',4000)}
['dt','mk'].forEach(id=>{let sy=0;const e=document.getElementById(id);e.addEventListener('touchstart',ev=>sy=ev.touches[0].clientY,{passive:true});e.addEventListener('touchmove',ev=>{if(ev.touches[0].clientY-sy>70)e.classList.remove('on')},{passive:true})});
document.addEventListener('keydown',e=>{const op=document.querySelector('.pn.on');if(op&&e.key==='Escape'){op.classList.remove('on');document.querySelectorAll('.tb').forEach(b=>b.classList.remove('on'));return}if(document.getElementById('dt').classList.contains('on')&&e.key==='Escape'){cd();return}if(document.getElementById('mk').classList.contains('on')&&e.key==='Escape'){cm();return}if(e.key==='ArrowLeft')cy(-1);if(e.key==='ArrowRight')cy(1);if(e.key===' '){e.preventDefault();ta()}if(e.key.toLowerCase()==='m')om();if(e.key.toLowerCase()==='w')tp('p-w','tb-w');if(e.key.toLowerCase()==='b')tp('p-b','tb-b')});
rc();setTimeout(()=>tst('🚀 KOMBAZ.ME | 🎮 משחק חדש!'),500);

// ═══ ONBOARDING ═══
const OB=[
{e:'🚀',t:'ברוך הבא ל-KOMBAZ',d:'MARS 2045 — מעקב אמיתי אחרי המסע למאדים',l:[
  {i:'📊',x:'נתונים חיים מ-NASA'},
  {i:'🛸',x:'Voyager 1 & 2 — מרחק אמיתי'},
  {i:'🔭',x:'Perseverance Rover — Sol נוכחי'}
]},
{e:'🎮',t:'איך זה עובד?',d:'שחק עם הזמן וגלה את העתיד',l:[
  {i:'◀▶',x:'כפתורי שנה — דלג קדימה'},
  {i:'⚡',x:'Auto — מתקדם אוטומטית'},
  {i:'🃏',x:'לחץ על כרטיסיה לפרטים'}
]},
{e:'🗺️',t:'גלה מאדים',d:'3 פאנלים מיוחדים בצד ימין',l:[
  {i:'🗺',x:'מפת מאדים + הר Olympus'},
  {i:'🌡',x:'מזג אוויר ב-Jezero Crater'},
  {i:'🏗',x:'חברות שבונות את העתיד'}
]},
{e:'🏆',t:'משחק עם הישגים',d:'כפתור 🎮 פותח עולם שלם',l:[
  {i:'💎',x:'אסוף KOMBAZ Coins'},
  {i:'⭐',x:'עלה רמות — 🌍→👑'},
  {i:'🔥',x:'נכנס כל יום = Streak'},
  {i:'🏆',x:'12 הישגים לפתוח'}
]},
{e:'📱',t:'התקן כאפליקציה',d:'נראה כמו אפליקציה אמיתית',l:[
  {i:'🏠',x:'אייקון במסך הבית'},
  {i:'⚡',x:'נטען מהיר גם offline'},
  {i:'🎨',x:'מסך מלא — בלי דפדפן'},
  {i:'💬',x:'שתף עם חברים בוואטסאפ'}
]}
];
let obi=0;
function ro(){const o=OB[obi],e=document.getElementById('ob-c');e.innerHTML='<div class="ob-emj">'+o.e+'</div><div class="ob-t">'+o.t+'</div><div class="ob-d">'+o.d+'</div><div class="ob-l">'+o.l.map(x=>'<div class="ob-li"><span class="ob-ic">'+x.i+'</span><span>'+x.x+'</span></div>').join('')+'</div><div class="ob-dt">'+OB.map((_,i)=>'<div class="ob-d2'+(i===obi?' on':'')+'"></div>').join('')+'</div><button class="ob-btn" onclick="nob()">'+(obi<OB.length-1?'הבא ←':'🚀 בוא נתחיל!')+'</button>'+(obi<OB.length-1?'<button class="ob-skp" onclick="cob2()">דלג</button>':'')}
function nob(){if(obi<OB.length-1){obi++;ro()}else cob2()}
function cob2(){document.getElementById('onb').classList.remove('on');try{localStorage.setItem('kbob','1')}catch(e){}}
function oo(){obi=0;document.getElementById('onb').classList.add('on');ro()}
// Show onboarding first time
try{if(!localStorage.getItem('kbob'))setTimeout(()=>{document.getElementById('onb').classList.add('on');ro()},700)}catch(e){}
// First-time tooltips on key elements
function fth(){try{if(localStorage.getItem('kbtt'))return;localStorage.setItem('kbtt','1');const ts=[{s:'#gb',t:'🎮 משחק עם הישגים',d:1500},{s:'#hlp',t:'❓ עזרה ומדריך',d:3500},{s:'.tb-m',t:'🗺 מפת מאדים',d:5500}];ts.forEach(t=>setTimeout(()=>{const el=document.querySelector(t.s);if(!el)return;const r=el.getBoundingClientRect(),h=document.createElement('div');h.className='tt-h r';h.textContent=t.t;h.style.top=(r.top+r.height/2-15)+'px';h.style.right=(window.innerWidth-r.left+8)+'px';document.body.appendChild(h);setTimeout(()=>h.remove(),2500)},t.d))}catch(e){}}
setTimeout(fth,2000);


// ═══ GAME SYSTEM ═══
const GA={
coins:0,streak:0,xp:0,level:1,dqp:0,dqg:3,qzi:0,
ach:{f1:0,t5:0,t10:0,sx:0,na:0,rb:0,mx:0,p3:0,wk:0,mn:0,mil:0,wzr:0}
};
const LVS=[{n:'🌍 Earthling',x:0},{n:'🧑‍🚀 Trainee',x:100},{n:'🚀 Pioneer',x:300},{n:'🏙️ Colonist',x:700},{n:'🏛️ Citizen',x:1500},{n:'👑 Mars Lord',x:3000}];
const QZS=[
{q:'מה זה MOXIE?',a:['חמצן מ-CO₂','דלק טילים','רובוט','לוויין'],c:0},
{q:'באיזו שנה נחתת Perseverance?',a:['2018','2021','2023','2025'],c:1},
{q:'גובה Olympus Mons?',a:['9 km','21.9 km','30 km','45 km'],c:1},
{q:'כמה זמן לוקח אור משמש למאדים?',a:['8 דק','13 דק','22 דק','45 דק'],c:1},
{q:'איפה Voyager 1 כרגע?',a:['חגורת אסטרואידים','בין-כוכבי','מאדים','שבתאי'],c:1},
{q:'מי בנה את Starship?',a:['NASA','SpaceX','Blue Origin','ULA'],c:1},
{q:'כמה מנועי Raptor יש ב-Starship?',a:['9','33','42','130'],c:1},
{q:'מה מספר הSol של Perseverance?',a:['~500','~1000','~1500','~1876'],c:3},
{q:'מטרה ל-2050:',a:['100 איש','1,000','100K','1,000,000'],c:3},
{q:'מהירות Voyager 1?',a:['10 km/s','17 km/s','25 km/s','100 km/s'],c:1},
{q:'מי המייסד של SpaceX?',a:['Bezos','Musk','Branson','Zuckerberg'],c:1},
{q:'אטמוספירת מאדים מכילה בעיקר:',a:['חמצן','CO₂','חנקן','מתאן'],c:1}
];
const ACHS=[
{id:'f1',n:'התחלה',i:'🎯',d:'שחק לראשונה'},
{id:'t5',n:'5 שנים',i:'⏰',d:'התקדם 5 שנים'},
{id:'t10',n:'10 שנים',i:'⏰',d:'התקדם 10 שנים'},
{id:'sx',n:'SpaceX',i:'🚀',d:'5 משימות SpaceX'},
{id:'na',n:'NASA',i:'🛸',d:'5 משימות NASA'},
{id:'rb',n:'רובוטיקה',i:'🤖',d:'3 משימות רובוטים'},
{id:'mx',n:'מאסק',i:'💬',d:'5 ציטוטים'},
{id:'p3',n:'חוקר',i:'🗺️',d:'פתח 3 פאנלים'},
{id:'wk',n:'שבוע',i:'🔥',d:'Streak 7 ימים'},
{id:'mn',n:'מיליון',i:'💎',d:'1,000 KOMBAZ'},
{id:'mil',n:'מאדים',i:'🏙️',d:'הגע ל-2050'},
{id:'wzr',n:'גאון',i:'🧠',d:'5 תשובות נכונות'}
];
function ldg(){try{const s=localStorage.getItem('kbgame');if(s){const d=JSON.parse(s);Object.assign(GA,d);const t=localStorage.getItem('kbday'),td=new Date().toDateString();if(t!==td){if(t&&((new Date(td)-new Date(t))/86400000===1)){GA.streak++;cob('🔥 +Day '+GA.streak)}else GA.streak=1;GA.dqp=0;qzn();localStorage.setItem('kbday',td)}}else{GA.streak=1;localStorage.setItem('kbday',new Date().toDateString());qzn()}}catch(e){}svg()}
function svg(){try{localStorage.setItem('kbgame',JSON.stringify(GA))}catch(e){}}
function ax(p){GA.xp+=p;GA.coins+=Math.floor(p/2);let nl=1;for(let i=LVS.length-1;i>=0;i--)if(GA.xp>=LVS[i].x){nl=i+1;break}if(nl>GA.level){GA.level=nl;cob('⭐ LEVEL '+nl+'!')}cob('+'+p+' XP');svg();ugu()}
function ac(id){if(!GA.ach[id]){GA.ach[id]=1;const a=ACHS.find(x=>x.id===id);if(a){cob('🏆 '+a.n);ax(50)}svg();ugu()}}
function ugu(){if(!document.getElementById('gm').classList.contains('on'))return;document.getElementById('gs-c').textContent=GA.coins.toLocaleString();document.getElementById('gs-s').textContent=GA.streak;document.getElementById('gs-l').textContent=GA.level;const lv=LVS[GA.level-1],nx=LVS[GA.level]||{x:GA.xp};document.getElementById('lv-n').textContent=lv.n;document.getElementById('lv-x').textContent=GA.xp+' / '+(nx.x||GA.xp)+' XP';document.getElementById('lv-f').style.width=Math.min(100,(GA.xp-lv.x)/(nx.x-lv.x)*100||100)+'%';document.getElementById('dq-f').style.width=(GA.dqp/GA.dqg*100)+'%';document.getElementById('dq-x').textContent=GA.dqp+'/'+GA.dqg+' · פרס: 50 💎';if(GA.dqp>=GA.dqg){document.getElementById('dq-q').textContent='✅ הושלם! חזור מחר';GA.coins+=50;GA.dqp=GA.dqg+1;cob('🎁 +50 💎');svg()}let u=0;document.getElementById('ach').innerHTML=ACHS.map(a=>{const un=GA.ach[a.id];if(un)u++;return'<div class="acit'+(un?' un':'')+'" title="'+a.d+'"><div class="aci">'+a.i+'</div><div class="acn">'+a.n+'</div></div>'}).join('');document.getElementById('ach-x').textContent=u+'/'+ACHS.length}
function qzn(){GA.qzi=Math.floor(Math.random()*QZS.length);const q=QZS[GA.qzi];if(!document.getElementById('qz-q'))return;document.getElementById('qz-q').textContent=q.q;document.getElementById('qz-a').innerHTML=q.a.map((x,i)=>'<button class="qab" onclick="qza('+i+')">'+x+'</button>').join('')}
function qza(i){const q=QZS[GA.qzi],bs=document.querySelectorAll('.qab');bs.forEach(b=>b.disabled=true);if(i===q.c){bs[i].classList.add('ok');ax(50);GA.qzc=(GA.qzc||0)+1;if(GA.qzc>=5)ac('wzr');setTimeout(qzn,1200)}else{bs[i].classList.add('no');bs[q.c].classList.add('ok');setTimeout(qzn,1500)}}
function cob(t){const e=document.getElementById('cob');e.textContent=t;e.classList.remove('go');setTimeout(()=>e.classList.add('go'),10);setTimeout(()=>e.classList.remove('go'),1600)}
function og(){ac('f1');document.getElementById('gm').classList.add('on');ugu();if(navigator.vibrate)navigator.vibrate(20)}
function cgm(){document.getElementById('gm').classList.remove('on')}
function shr(){const t='השגתי Level '+GA.level+' ב-KOMBAZ עם '+GA.coins+' 💎! 🚀 נסה: https://kombaz.me';const u='https://wa.me/?text='+encodeURIComponent(t);location.href=u}
// Hook into existing actions
const _cy=cy;cy=function(d){_cy(d);ax(10);if(cy_-2026>=5)ac('t5');if(cy_-2026>=10)ac('t10');if(cy_>=2050)ac('mil');GA.dqp=Math.min(GA.dqg,GA.dqp+1);svg()};
const _od=od;od=function(m){_od(m);ax(15);if(m.t.includes('spacex')){GA.sxc=(GA.sxc||0)+1;if(GA.sxc>=5)ac('sx')}if(m.t.includes('nasa')){GA.nac=(GA.nac||0)+1;if(GA.nac>=5)ac('na')}if(m.c==='robots'){GA.rbc=(GA.rbc||0)+1;if(GA.rbc>=3)ac('rb')}};
const _om=om;om=function(){_om();ax(5);GA.mxc=(GA.mxc||0)+1;if(GA.mxc>=5)ac('mx')};
const _tp=tp;tp=function(id,bi){_tp(id,bi);ax(5);GA.p3c=GA.p3c||new Set();GA.p3c=new Set([...(GA.p3c||[]),id]);if(GA.p3c.size>=3)ac('p3')};
if(GA.streak>=7)ac('wk');if(GA.coins>=1000)ac('mn');
ldg();

</script>

<script>
if('serviceWorker' in navigator){
  navigator.serviceWorker.register('/sw.js').catch(()=>{});
}

// "Install App" button
let dfp;
window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault();
  dfp = e;
  const b = document.createElement('button');
  b.textContent = '📱 התקן כאפליקציה';
  b.style.cssText = 'position:fixed;bottom:calc(var(--sb)+90px);left:50%;transform:translateX(-50%);z-index:9000;background:linear-gradient(135deg,#005288,#00d4ff);color:#fff;border:none;border-radius:24px;padding:10px 18px;font-size:.7rem;font-weight:700;cursor:pointer;font-family:Inter,sans-serif;box-shadow:0 4px 20px rgba(0,212,255,.4);animation:p 2s infinite';
  b.onclick = () => {
    dfp.prompt();
    dfp.userChoice.then(c => {
      if(c.outcome === 'accepted') tst('🎉 KOMBAZ הותקן!');
      b.remove();
    });
  };
  document.body.appendChild(b);
});
</script>
</body>
</html>
