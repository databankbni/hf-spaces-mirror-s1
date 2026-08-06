(()=>{
  const NS='http://www.w3.org/2000/svg';
  const makeIcon=(name,cls='cali-icon')=>{const svg=document.createElementNS(NS,'svg');svg.setAttribute('class',cls);svg.setAttribute('aria-hidden','true');const use=document.createElementNS(NS,'use');use.setAttribute('href','/static/brand/icons.svg#'+name);svg.append(use);return svg};
  const navIcons={'/warroom':'warroom','/':'content','/page-token':'token','/team':'rpa','/audience':'audience'};
  const glyphs={'🤖':'spark','✨':'spark','➕':'add','💡':'idea','📅':'calendar','🕒':'calendar','📌':'pin','📍':'pin','💾':'save','✔':'approve','✓':'approve','⚠':'warning','↻':'refresh'};
  function decorate(root=document){
    root.querySelectorAll?.('a[href]').forEach(a=>{if(a.dataset.caliNav)return;const path=new URL(a.href,location.href).pathname,name=navIcons[path];if(!name)return;a.dataset.caliNav='1';a.firstChild&&a.firstChild.nodeType===3&&(a.firstChild.nodeValue=a.firstChild.nodeValue.replace(/^\s*\d+\.\s*/,''));a.prepend(makeIcon(name,'cali-icon cali-nav-icon'))});
    root.querySelectorAll?.('.brand,.system-side>b,.side>b,form.box h1').forEach(el=>{if(el.dataset.caliBrand)return;el.dataset.caliBrand='1';const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);let n;while(n=walker.nextNode())n.nodeValue=n.nodeValue.replace(/🔥\s*/g,'');const img=document.createElement('img');img.src='/static/brand/california-emblem.png';img.alt='';img.className='cali-brand-mark';el.prepend(img);el.classList.add('cali-brand')});
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT),nodes=[];let n;while(n=walker.nextNode())if(n.nodeValue.includes('🔥')||Object.keys(glyphs).some(g=>n.nodeValue.includes(g)))nodes.push(n);
    nodes.forEach(node=>{const re=/(🔥|🤖|✨|➕|💡|📅|🕒|📌|📍|💾|✔|✓|⚠|↻)/g,parts=node.nodeValue.split(re);if(parts.length<2)return;const frag=document.createDocumentFragment();parts.forEach(p=>{if(p==='🔥'){const img=document.createElement('img');img.src='/static/brand/california-emblem.png';img.alt='';img.className='cali-brand-mark';frag.append(img)}else if(glyphs[p])frag.append(makeIcon(glyphs[p]));else frag.append(p)});node.replaceWith(frag)});
  }
  document.addEventListener('DOMContentLoaded',()=>{decorate();new MutationObserver(ms=>ms.forEach(m=>m.addedNodes.forEach(n=>n.nodeType===1&&decorate(n)))).observe(document.body,{childList:true,subtree:true})});
})();
