const $=s=>document.querySelector(s);
let current=null;

const shotCounts={6:4,10:5,15:6,20:8,30:10};

const visualBeats=[
  ["Hook","Open with the strongest product or talent image immediately. Make the first frame readable without context."],
  ["Reveal","Reveal the product clearly and establish the world around it."],
  ["Detail","Move into tactile product detail: material, texture, interface, finish, or hero feature."],
  ["Use","Show the product naturally in action with believable human interaction."],
  ["Benefit","Visualize the key benefit instead of explaining it literally."],
  ["Hero","Create the strongest aspirational product/talent composition of the film."],
  ["Proof","Add a secondary use-case or close detail that supports credibility."],
  ["Shift","Change angle, location, or energy to prevent visual repetition."],
  ["Resolve","Bring the visual language back to the core product promise."],
  ["End Card","Finish on a clean hero frame with brand/message/CTA space."]
];

const cameraByTone={
  "Cinematic premium":["controlled dolly-in","smooth tracking shot","low-angle hero push","precise lateral slider","subtle handheld realism"],
  "UGC natural":["phone-camera handheld","casual selfie framing","quick reframing","natural walking follow","static phone setup"],
  "Luxury minimal":["locked-off composition","slow architectural push","macro detail drift","symmetrical hero frame","clean side profile"],
  "Energetic commercial":["fast push-in","snap pan into subject","dynamic tracking","wide-to-close movement","orbit around product"],
  "Editorial fashion":["confident runway tracking","off-axis fashion framing","low-angle walk-up","clean profile tracking","editorial close-up"]
};

function v(id){return $("#"+id).value.trim()}
function esc(s){return String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]))}
function pace(d){return d<=10?"Fast":d<=20?"Balanced":"Story-led"}
function download(name,text,type="text/plain"){const b=new Blob([text],{type});const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}

function timeRanges(duration,count){
  const base=duration/count, out=[];
  for(let i=0;i<count;i++){
    const start=(i*base).toFixed(1).replace(".0","");
    const end=((i+1)*base).toFixed(1).replace(".0","");
    out.push(`${start}s–${end}s`);
  }
  return out;
}

function build(){
  const duration=Number(v("duration"));
  const count=shotCounts[duration]||6;
  const tone=v("tone"), cams=cameraByTone[tone]||cameraByTone["Cinematic premium"];
  const product=v("product")||"Untitled Product";
  const message=v("message")||"Show the product promise visually.";
  const direction=v("direction")||"Premium product-focused environment with clean styling and believable movement.";
  const cta=v("cta")||"Discover more";
  const audio=v("audio")||"Modern instrumental track with clear rhythmic edit points.";
  const objective=v("objective"), platform=v("platform"), format=v("format"), audience=v("audience")||"Target consumer";
  const times=timeRanges(duration,count);

  const selected=[];
  for(let i=0;i<count;i++){
    let beat;
    if(i===count-1) beat=visualBeats[9];
    else beat=visualBeats[Math.min(i,8)];
    const camera=cams[i%cams.length];
    const end=i===count-1;
    const text=end?`${message} · ${cta}`:(i===0?message:"No on-screen text unless required.");
    const action=end
      ? `Hold on a confident final composition of ${product}; leave clean negative space for the CTA.`
      : `${beat[1]} Keep the action physically plausible and maintain continuity with the previous shot.`;
    const prompt=`${tone} advertising shot for ${product}. ${action} ${direction} Camera: ${camera}. Format ${format}. Natural anatomy, consistent product design, coherent lighting, no unwanted logos, no watermarks, no accidental text.`;

    selected.push({
      shot:i+1,
      time:times[i],
      beat:beat[0],
      visual:action,
      camera,
      action:end?`Resolve into final hero pose / product lockup.`:`Primary subject action supports: ${message}`,
      audio:i===0?`Music starts immediately. ${audio}`:(end?`Music resolves; optional sonic logo / clean finish.`:`Cut on beat; preserve musical continuity.`),
      text,
      prompt
    });
  }

  current={product,objective,duration,format,platform,tone,audience,message,direction,cta,audio,shots:selected};
  render();
}

function render(){
  const d=current;
  $("#result").hidden=false;
  $("#resultTitle").textContent=d.product;
  $("#resultMeta").textContent=`${d.objective} · ${d.platform} · ${d.tone} · Audience: ${d.audience}`;
  $("#shotCount").textContent=d.shots.length;
  $("#durationOut").textContent=`${d.duration}s`;
  $("#formatOut").textContent=d.format;
  $("#pacingOut").textContent=pace(d.duration);

  $("#shots").innerHTML=d.shots.map(s=>`
    <article class="shot">
      <div class="shot-top">
        <div class="shot-number"><div class="badge">${s.shot}</div><div><h3>${esc(s.beat)}</h3><div class="time">${esc(s.time)}</div></div></div>
        <div class="time">${esc(d.format)} · ${esc(d.platform)}</div>
      </div>
      <div class="shot-grid">
        <div class="field"><span>VISUAL</span><p>${esc(s.visual)}</p></div>
        <div class="field"><span>CAMERA</span><p>${esc(s.camera)}</p></div>
        <div class="field"><span>AUDIO / TEXT</span><p>${esc(s.audio)}<br><br><b>${esc(s.text)}</b></p></div>
      </div>
      <div class="prompt"><span>AI VIDEO PROMPT</span><p>${esc(s.prompt)}</p></div>
    </article>`).join("");

  $("#productionNotes").innerHTML=`<ul>
    <li><b>Continuity:</b> keep product design, wardrobe, talent identity and lighting direction consistent across every shot.</li>
    <li><b>Pacing:</b> ${pace(d.duration)} edit rhythm for a ${d.duration}-second ${d.platform} placement.</li>
    <li><b>Message discipline:</b> every shot should support “${esc(d.message)}”; remove anything that does not.</li>
    <li><b>Final frame:</b> reserve clean negative space for “${esc(d.cta)}”.</li>
    <li><b>Generation safety:</b> avoid accidental brand marks, watermarks, malformed anatomy and unintended text.</li>
  </ul>`;
  $("#result").scrollIntoView({behavior:"smooth",block:"start"});
}

function toMarkdown(){
  const d=current;
  let out=`# ${d.product} — Ad Storyboard\n\n`;
  out+=`- Objective: ${d.objective}\n- Duration: ${d.duration}s\n- Format: ${d.format}\n- Platform: ${d.platform}\n- Tone: ${d.tone}\n- Audience: ${d.audience}\n- Key message: ${d.message}\n- CTA: ${d.cta}\n\n`;
  for(const s of d.shots){
    out+=`## Shot ${s.shot} — ${s.beat} (${s.time})\n\n`;
    out+=`**Visual:** ${s.visual}\n\n**Camera:** ${s.camera}\n\n**Audio:** ${s.audio}\n\n**On-screen text:** ${s.text}\n\n**AI video prompt:**\n\n${s.prompt}\n\n`;
  }
  return out;
}


function asciiPdfText(value){
  return String(value??"")
    .replace(/İ/g,"I").replace(/ı/g,"i")
    .replace(/Ğ/g,"G").replace(/ğ/g,"g")
    .replace(/Ş/g,"S").replace(/ş/g,"s")
    .replace(/Ç/g,"C").replace(/ç/g,"c")
    .replace(/Ö/g,"O").replace(/ö/g,"o")
    .replace(/Ü/g,"U").replace(/ü/g,"u")
    .normalize("NFKD").replace(/[\u0300-\u036f]/g,"")
    .replace(/[^\x20-\x7E]/g," ");
}
function pdfEscape(value){
  return asciiPdfText(value).replace(/\\/g,"\\\\").replace(/\(/g,"\\(").replace(/\)/g,"\\)");
}
function pdfWrap(text,maxChars){
  const words=asciiPdfText(text).replace(/\s+/g," ").trim().split(" ");
  const lines=[]; let line="";
  for(const word of words){
    const test=line?`${line} ${word}`:word;
    if(test.length>maxChars && line){lines.push(line);line=word}
    else line=test;
  }
  if(line)lines.push(line);
  return lines.length?lines:[""];
}
function makeStoryboardPdf(data){
  const W=595,H=842,M=48;
  const pages=[];
  let commands=[], y=H-M;

  const newPage=()=>{
    if(commands.length)pages.push(commands.join("\n"));
    commands=[];
    y=H-M;
    commands.push("0.12 0.12 0.12 rg");
    commands.push(`${M} ${H-56} ${W-M*2} 1 re f`);
    y=H-78;
  };
  const ensure=(height)=>{if(y-height<M+20)newPage()};
  const text=(value,x,size=10,bold=false)=>{
    const safe=pdfEscape(value);
    commands.push(`BT /${bold?"F2":"F1"} ${size} Tf ${x} ${y} Td (${safe}) Tj ET`);
  };
  const line=(x1,x2,yy)=>commands.push(`0.28 0.28 0.28 RG 0.6 w ${x1} ${yy} m ${x2} ${yy} l S`);
  const wrapped=(label,value,size=9,maxChars=88)=>{
    const lines=pdfWrap(value,maxChars);
    ensure(18+lines.length*(size+3));
    if(label){text(label,M,8,true);y-=13}
    for(const l of lines){text(l,M,size,false);y-=size+4}
    y-=4;
  };

  newPage();
  text("SOLRICKS AD STORYBOARD",M,9,true); y-=27;
  text(data.product||"Untitled campaign",M,24,true); y-=24;
  text("From brief to shot list.",M,10,false); y-=20;
  line(M,W-M,y); y-=22;

  const meta=[
    `Objective: ${data.objective}`,
    `Duration: ${data.duration}s`,
    `Format: ${data.format}`,
    `Platform: ${data.platform}`,
    `Tone: ${data.tone}`,
    `Audience: ${data.audience}`,
  ];
  for(const m of meta){text(m,M,9,false);y-=14}
  y-=6;
  wrapped("KEY MESSAGE",data.message,10,78);
  wrapped("CREATIVE DIRECTION",data.direction,9,88);
  wrapped("CALL TO ACTION",data.cta,9,88);
  wrapped("MUSIC / AUDIO",data.audio,9,88);

  for(const s of data.shots){
    ensure(210);
    line(M,W-M,y);y-=24;
    text(`SHOT ${s.shot}  /  ${s.beat}  /  ${s.time}`,M,14,true);y-=22;
    wrapped("VISUAL",s.visual,9,88);
    wrapped("CAMERA",s.camera,9,88);
    wrapped("ACTION",s.action,9,88);
    wrapped("AUDIO",s.audio,9,88);
    wrapped("ON-SCREEN TEXT",s.text,9,88);
    wrapped("AI VIDEO PROMPT",s.prompt,8,98);
  }

  ensure(150);
  line(M,W-M,y);y-=24;
  text("PRODUCTION NOTES",M,13,true);y-=22;
  const notes=[
    `Continuity: keep product design, wardrobe, talent identity and lighting direction consistent across every shot.`,
    `Pacing: ${pace(data.duration)} edit rhythm for a ${data.duration}-second ${data.platform} placement.`,
    `Message discipline: every shot should support "${data.message}".`,
    `Final frame: reserve clean negative space for "${data.cta}".`,
    `Generation safety: avoid accidental brand marks, watermarks, malformed anatomy and unintended text.`
  ];
  for(const n of notes)wrapped("-",n,8,96);

  if(commands.length)pages.push(commands.join("\n"));

  // PDF object assembly: Catalog, Pages, Helvetica, Helvetica-Bold, then page/content pairs.
  const objects=[null];
  objects.push("<< /Type /Catalog /Pages 2 0 R >>");
  objects.push(""); // pages tree filled later
  objects.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");
  objects.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>");

  const kids=[];
  for(const content of pages){
    const pageObj=objects.length;
    const contentObj=pageObj+1;
    kids.push(`${pageObj} 0 R`);
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${W} ${H}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents ${contentObj} 0 R >>`);
    const stream=content+"\n";
    objects.push(`<< /Length ${stream.length} >>\nstream\n${stream}endstream`);
  }
  objects[2]=`<< /Type /Pages /Count ${pages.length} /Kids [${kids.join(" ")}] >>`;

  let pdf="%PDF-1.4\n%SOLRICKS\n";
  const offsets=[0];
  for(let i=1;i<objects.length;i++){
    offsets[i]=pdf.length;
    pdf+=`${i} 0 obj\n${objects[i]}\nendobj\n`;
  }
  const xref=pdf.length;
  pdf+=`xref\n0 ${objects.length}\n`;
  pdf+="0000000000 65535 f \n";
  for(let i=1;i<objects.length;i++){
    pdf+=String(offsets[i]).padStart(10,"0")+" 00000 n \n";
  }
  pdf+=`trailer\n<< /Size ${objects.length} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return new Blob([pdf],{type:"application/pdf"});
}

$("#generateBtn").addEventListener("click",build);
$("#clearBtn").addEventListener("click",()=>{document.querySelectorAll("input,textarea").forEach(x=>x.value="");$("#result").hidden=true;current=null});
$("#sampleBtn").addEventListener("click",()=>{
  $("#product").value="ELARVÉ Jeans";
  $("#objective").value="Luxury brand film";
  $("#duration").value="15";
  $("#format").value="9:16";
  $("#platform").value="TikTok / Reels";
  $("#tone").value="Editorial fashion";
  $("#audience").value="Style-conscious women, 20–35";
  $("#message").value="Perfect fit. Every move.";
  $("#direction").value="Confident woman walking through a contemporary city interior. Focus on fit, fabric movement and silhouette. Premium but natural; no slow motion.";
  $("#cta").value="Discover ELARVÉ";
  $("#audio").value="Modern fashion beat, instrumental, no vocals";
});
$("#copyBtn").addEventListener("click",async()=>{if(!current)return;await navigator.clipboard.writeText(toMarkdown());$("#copyBtn").textContent="Copied";setTimeout(()=>$("#copyBtn").textContent="Copy Shot List",1200)});

$("#pdfBtn").addEventListener("click",()=>{
  if(!current)return;
  const blob=makeStoryboardPdf(current);
  const a=document.createElement("a");
  a.href=URL.createObjectURL(blob);
  a.download=`${current.product.replace(/[^\w-]+/g,"-")}-storyboard.pdf`;
  a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href),1000);
});

$("#mdBtn").addEventListener("click",()=>{if(current)download(`${current.product.replace(/[^\w-]+/g,"-")}-storyboard.md`,toMarkdown(),"text/markdown")});
$("#jsonBtn").addEventListener("click",()=>{if(current)download(`${current.product.replace(/[^\w-]+/g,"-")}-storyboard.json`,JSON.stringify(current,null,2),"application/json")});
