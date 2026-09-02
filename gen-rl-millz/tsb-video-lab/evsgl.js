/* The resolve, on the GPU.
 *
 * The receiver gets ADDRESSES, not pixels and not carriers. Turning an address
 * set into a frame is three stages, and none of them looks at another frame:
 *
 *   1. scatter   — every coefficient event lands on its own texel (gl.POINTS)
 *   2. butterfly — 2·log2(tile) ping-pong passes resolve every block at once
 *   3. resolve   — scale back by a SHIFT, add the block mean, YCbCr → RGB
 *
 * ── Every format from one address set ────────────────────────────────────────
 * For a separable ±1 spectrum, the coefficients whose row AND column
 * indices are both multiples of f are EXACTLY the spectrum of the f×f
 * box-averaged image. So a smaller output is a subset filter on the address —
 * done here in the scatter's vertex shader, one comparison — followed by a
 * smaller transform. No decode. No re-encode. No second copy of the clip.
 *
 * Level 1 reads a quarter of the addresses, level 2 a sixteenth. Sixteen
 * quarter-size views therefore cost what one native view costs, which is what
 * makes the mosaic honest rather than a trick.
 *
 * Integer end to end. Right-shift of a negative is implementation-defined in
 * GLSL ES 3.00, so the scale-back branches instead of trusting it — that branch
 * is what makes verifyLuma() come back exact rather than close.
 */
const LAW = new URLSearchParams(location.search).get("law") || "";

/* ── THE STAGE SPLIT, and why it is a URL knob rather than a timer ────────────
 *
 * This page has one honest cost measurement and it is the achieved frame
 * interval: GL calls RETURN ON SUBMISSION, so timing `resolvePaint` reported
 * 0.3 ms while the page managed 5.9 fps. Any per-stage timer built here would
 * measure how fast we can ASK, not how fast it is done.
 *
 * So the split is made by REMOVING a stage and re-reading the one number that
 * cannot lie. `?stage=` selects how far the pipeline runs:
 *
 *   decode    (player.js) never calls the GPU at all — the wire + wasm ceiling
 *   none      paint the accumulator as it stands — no upload, no scatter, no
 *             transform. Picture is stale; the RATE is the frame plumbing alone.
 *   scatter   upload the addresses and rasterise them, then paint. Picture is
 *             the raw spectrum, not an image — deliberately.
 *   full      everything (the default)
 *
 * Successive differences are the stage costs, measured on the device that has
 * the problem. `stage=none` and `stage=scatter` DO NOT PRODUCE A CORRECT
 * PICTURE and are not a rendering mode; they exist so that a wrong guess about
 * where the time goes can be falsified in four page loads. */
const STAGE = new URLSearchParams(location.search).get("stage") || "full";

const QUAD_VS = `#version 300 es
in vec2 p; void main(){ gl_Position = vec4(p,0.,1.); }`;

const SCATTER_VS = `#version 300 es
in int aXY; in int aVal;
uniform int PWS;      // padded width at NATIVE scale — how aXY was encoded
uniform int BS, BSH;  // block edge and its log2
uniform int LEVEL;    // 0 = native, each step halves both axes
uniform vec2 RES;     // the accumulator's active size at this level
uniform int AY0, AYN;  // the band: first output row it holds, and how many
flat out int vVal;
void main(){
  int x0 = aXY % PWS, y0 = aXY / PWS;
  int ic = x0 & (BS-1), ir = y0 & (BS-1);
  int f = 1 << LEVEL;
  if ((( ic | ir ) & (f - 1)) != 0){      // not on the f-grid: simply not read
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    gl_PointSize = 1.0; vVal = 0; return;
  }
  int tile = BS >> LEVEL;
  int x = (x0 >> BSH) * tile + (ic >> LEVEL);
  int y = (y0 >> BSH) * tile + (ir >> LEVEL);
  // The accumulator holds one BAND of output rows, not the whole field. A block
  // never straddles a band boundary, so this is a partition, not an approximation
  // — every address lands in exactly one band and is dropped by all the others.
  y -= AY0;
  if (y < 0 || y >= AYN){
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    gl_PointSize = 1.0; vVal = 0; return;
  }
  gl_Position = vec4((float(x)+0.5)/RES.x*2.0-1.0, (float(y)+0.5)/RES.y*2.0-1.0, 0.0, 1.0);
  gl_PointSize = 1.0;
  vVal = aVal;
}`;

const SCATTER_FS = `#version 300 es
precision highp int; precision highp float;
flat in int vVal;
out ivec4 o;
void main(){ o = ivec4(vVal, vVal, vVal, 0); }`;

/* one stage of the transform, on all three channels at once */
/* RADIX-4: two butterfly levels in one pass.
 *
 * Each pass costs one full-texture WRITE, and writes are the traffic that cannot
 * be cached away. Doing levels H and 2H together halves the number of passes and
 * therefore halves the writes; the four reads it needs are neighbours inside the
 * same block and hit cache. Same transform, same result, fewer round trips.
 *
 * Composing the two levels by hand, with this file's convention that the LOW
 * element of a pair emits sum and the HIGH emits (low - high):
 *   after H:   p(0,·) = x0+x1        p(1,·) = x0-x1
 *   after 2H:  q(·,0) = p(·,0)+p(·,1)   q(·,1) = p(·,0)-p(·,1)
 */
const BFLY4_FS = `#version 300 es
precision highp int; precision highp float;
uniform highp isampler2D SRC;
uniform int H;      // the lower of the two strides; the upper is 2H
uniform int AXIS;   // 0 = across the block's columns, 1 = across its rows
uniform int MASK;   // tile - 1
out ivec4 o;
ivec4 at(ivec2 q, int local, int want){
  ivec2 p = q;
  if (AXIS == 0) p.x = (q.x & ~MASK) | want; else p.y = (q.y & ~MASK) | want;
  return texelFetch(SRC, p, 0);
}
void main(){
  ivec2 q = ivec2(gl_FragCoord.xy);
  int local = (AXIS == 0) ? (q.x & MASK) : (q.y & MASK);
  int H2 = H << 1;
  int base = local & ~(H | H2);
  ivec4 x0 = at(q, local, base);
  ivec4 x1 = at(q, local, base | H);
  ivec4 x2 = at(q, local, base | H2);
  ivec4 x3 = at(q, local, base | H | H2);
  ivec4 s01 = x0 + x1, d01 = x0 - x1, s23 = x2 + x3, d23 = x2 - x3;
  bool b1 = (local & H) != 0, b2 = (local & H2) != 0;
  o = b2 ? (b1 ? d01 - d23 : s01 - s23)
         : (b1 ? d01 + d23 : s01 + s23);
}`;

const BFLY_FS = `#version 300 es
precision highp int; precision highp float;
uniform highp isampler2D SRC;
uniform int H;      // stride within the block axis
uniform int AXIS;   // 0 = across the block's columns, 1 = across its rows
uniform int MASK;   // tile - 1
out ivec4 o;
void main(){
  ivec2 q = ivec2(gl_FragCoord.xy);
  int local = (AXIS == 0) ? (q.x & MASK) : (q.y & MASK);
  ivec2 pq = q;
  if (AXIS == 0) pq.x = (q.x & ~MASK) | (local ^ H); else pq.y = (q.y & ~MASK) | (local ^ H);
  ivec4 a = texelFetch(SRC, q, 0);
  ivec4 b = texelFetch(SRC, pq, 0);
  o = ((local & H) == 0) ? a + b : b - a;
}`;

/* THE OTHER LAW — one pass, no ping-pong, no transform.
 *
 * `H[i][j] = (−1)^popcount(i AND j)`, so a block's samples can be evaluated
 * straight from the addresses it carries. The butterfly costs `N·log2 N` per
 * block whatever the block holds; this costs `k·N` for the `k` addresses that
 * are actually there. The crossover is `k = log2 N` — and on a GPU the ratio
 * that matters is not the arithmetic but the WRITES: the butterfly is 6 to 12
 * full-texture round trips plus the scatter, this is one.
 *
 * The addresses arrive sorted by block with a per-block (start, count), so a
 * fragment reads only its own block's list. That sort is the counting sort in
 * `packDirect` — O(addresses), on data already in hand.
 *
 * GLSL ES 3.00 has no `bitCount`, so the parity is the XOR fold. `i` is at most
 * 12 bits (4096 samples is the largest block this format admits), and the fold
 * is exact over that width.
 */
const DIRECT_FS = `#version 300 es
precision highp int; precision highp float;
uniform highp isampler2D COEF;   // (index | channel<<12, value), block-major
uniform highp isampler2D BOFF;   // (start, count) per block, band-local
uniform int TILEH;               // log2(tile)
uniform int BWL;                 // blocks across the field
uniform int CW, OW;              // data-texture widths
out ivec4 o;
int par(int x){ x ^= x >> 8; x ^= x >> 4; x ^= x >> 2; x ^= x >> 1; return x & 1; }
void main(){
  ivec2 q = ivec2(gl_FragCoord.xy);
  int mask = (1 << TILEH) - 1;
  int b = (q.y >> TILEH) * BWL + (q.x >> TILEH);
  int j = ((q.y & mask) << TILEH) | (q.x & mask);
  ivec2 bo = texelFetch(BOFF, ivec2(b % OW, b / OW), 0).xy;
  ivec3 a = ivec3(0);
  for(int n = 0; n < bo.y; n++){
    int p = bo.x + n;
    ivec2 c = texelFetch(COEF, ivec2(p % CW, p / CW), 0).xy;
    int v = (par((c.x & 4095) & j) == 1) ? -c.y : c.y;
    int ch = c.x >> 12;
    a += ivec3(ch == 0 ? v : 0, ch == 1 ? v : 0, ch == 2 ? v : 0);
  }
  o = ivec4(a, 0);
}`;

const RESOLVE_FS = `#version 300 es
precision highp int; precision highp float;
uniform highp isampler2D ACC;
uniform int VX, VY, VW, VH;       // the viewport this panel occupies
uniform int SN;                   // log2(block area) — the scale-back shift
uniform int SW, SH;               // the resolved field's size at this level
uniform int AY0;                  // first field row this accumulator band holds
uniform int VERIFY;               // >=0 : emit the raw channel byte, no colour
out vec4 o;

/* Scale-back by the block area — the SAME shift at every level, because the mask
   and the smaller transform cancel exactly. >> on a negative signed value is
   implementation-defined in GLSL ES 3.00, so this branches rather than trusts. */
int sb(int v){ int n = 1 << SN; return v >= 0 ? (v >> SN) : -((-v + n - 1) >> SN); }

void main(){
  // Map the panel to the FIELD. At a reduced level the field is smaller than the
  // panel, so this magnifies; without it the shader walked off the end of the
  // resolved area and sampled cleared texels — which is what made every output
  // below native look wrong.
  ivec2 p = ivec2(int(gl_FragCoord.x) - VX, (VY + VH - 1) - int(gl_FragCoord.y));
  ivec2 q = ivec2(p.x * SW / VW, p.y * SH / VH - AY0);
  ivec4 acc = texelFetch(ACC, q, 0);
  int hf = 1 << (SN - 1);
  int Y  = clamp(sb(acc.r + hf), 0, 255);
  int Cb = clamp(sb(acc.g + hf), 0, 255);
  int Cr = clamp(sb(acc.b + hf), 0, 255);
  if (VERIFY >= 0){
    int v = VERIFY == 0 ? Y : (VERIFY == 1 ? Cb : Cr);
    o = vec4(vec3(float(v)/255.0), 1.0);
    return;
  }
  // A block outside a focus window is never read, so its accumulator stays at
  // zero — and zero chroma is not neutral chroma, it is full green. Absent data
  // must render as absent, not as a colour. Both channels resolving to exactly 0
  // means nothing was scattered there; a block that carries chroma reconstructs
  // near 128 because its DC alone is ~128·area.
  int u = (Cb == 0 && Cr == 0) ? 0 : Cb - 128;
  int w = (Cb == 0 && Cr == 0) ? 0 : Cr - 128;
  o = vec4(float(clamp(Y + (91881*w >> 16), 0, 255))/255.0,
           float(clamp(Y - (22554*u >> 16) - (46802*w >> 16), 0, 255))/255.0,
           float(clamp(Y + (116130*u >> 16), 0, 255))/255.0, 1.0);
}`;

export function makeEVSGL(canvas){
  /* `preserveDrawingBuffer` was set so the boot check could `readPixels` the
     canvas. It costs a FULL FRAMEBUFFER COPY EVERY FRAME, forever, to support a
     check that runs once — measured at 720p: GPU resolve 0.3 ms, decode 23 fps,
     display 5 fps. The whole gap was here.
     It is unnecessary: `verifyLuma` reads back synchronously in the same task as
     the draw that produced the pixels, which is before the compositor can
     discard them. `desynchronized` additionally lets the canvas present without
     waiting on the compositor's cadence. */
  const gl = canvas.getContext("webgl2", {antialias:false, depth:false, alpha:false,
                                          desynchronized:true,
                                          powerPreference:"high-performance"});
  if(!gl) return null;

  const sh=(t,s)=>{const o=gl.createShader(t);gl.shaderSource(o,s);gl.compileShader(o);
    if(!gl.getShaderParameter(o,gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(o)+"\n"+s); return o;};
  const prog=(vs,fs)=>{const p=gl.createProgram();
    gl.attachShader(p,sh(gl.VERTEX_SHADER,vs)); gl.attachShader(p,sh(gl.FRAGMENT_SHADER,fs));
    gl.linkProgram(p);
    if(!gl.getProgramParameter(p,gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p)); return p;};

  const pScatter=prog(SCATTER_VS,SCATTER_FS), pBfly=prog(QUAD_VS,BFLY_FS),
        pBfly4=prog(QUAD_VS,BFLY4_FS), pResolve=prog(QUAD_VS,RESOLVE_FS),
        pDirect=prog(QUAD_VS,DIRECT_FS);

  const quad=gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER,quad);
  gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),gl.STATIC_DRAW);
  const ptsBuf=gl.createBuffer();
  const vaoB=gl.createVertexArray(), vaoB4=gl.createVertexArray(),
        vaoR=gl.createVertexArray(), vaoP=gl.createVertexArray(),
        vaoD=gl.createVertexArray();
  // Each program gets its own VAO: attribute locations are assigned at LINK time
  // and two programs sharing a vertex shader are not guaranteed to agree on them.
  for(const [vao,p] of [[vaoB,pBfly],[vaoB4,pBfly4],[vaoR,pResolve],[vaoD,pDirect]]){
    gl.bindVertexArray(vao); gl.bindBuffer(gl.ARRAY_BUFFER,quad);
    const l=gl.getAttribLocation(p,"p"); gl.enableVertexAttribArray(l);
    gl.vertexAttribPointer(l,2,gl.FLOAT,false,0,0);
  }
  gl.bindVertexArray(vaoP); gl.bindBuffer(gl.ARRAY_BUFFER,ptsBuf);
  const lXY=gl.getAttribLocation(pScatter,"aXY"), lV=gl.getAttribLocation(pScatter,"aVal");
  gl.enableVertexAttribArray(lXY); gl.vertexAttribIPointer(lXY,1,gl.INT,8,0);
  gl.enableVertexAttribArray(lV);  gl.vertexAttribIPointer(lV,1,gl.INT,8,4);
  gl.bindVertexArray(null);

  const U=(p,n)=>gl.getUniformLocation(p,n);
  const uS={PWS:U(pScatter,"PWS"),LEVEL:U(pScatter,"LEVEL"),RES:U(pScatter,"RES"),
            BS:U(pScatter,"BS"),BSH:U(pScatter,"BSH"),
            AY0:U(pScatter,"AY0"),AYN:U(pScatter,"AYN")};
  const uB={SRC:U(pBfly,"SRC"),H:U(pBfly,"H"),AXIS:U(pBfly,"AXIS"),MASK:U(pBfly,"MASK")};
  const uB4={SRC:U(pBfly4,"SRC"),H:U(pBfly4,"H"),AXIS:U(pBfly4,"AXIS"),MASK:U(pBfly4,"MASK")};
  const uR={ACC:U(pResolve,"ACC"),VX:U(pResolve,"VX"),VY:U(pResolve,"VY"),
            VW:U(pResolve,"VW"),VH:U(pResolve,"VH"),SW:U(pResolve,"SW"),SH:U(pResolve,"SH"),
            SN:U(pResolve,"SN"),VERIFY:U(pResolve,"VERIFY"),AY0:U(pResolve,"AY0")};

  const uD={COEF:U(pDirect,"COEF"),BOFF:U(pDirect,"BOFF"),TILEH:U(pDirect,"TILEH"),
            BWL:U(pDirect,"BWL"),CW:U(pDirect,"CW"),OW:U(pDirect,"OW")};

  let PWS=0, PHS=0, W=0, H=0, BW=0, BH=0, BS=8, BSH=3, SN=6, tex=[null,null], fbo=[null,null], src=0;
  let BAND=0;              // block rows per accumulator band
  let PASSES=0, MOVED=0;   // measured per frame, so the traffic claim is visible
  let DIRECT=0, BFLY=0;    // bands taken by each law, so the choice is reported
  /* Every GPU texture this path has ever allocated. It must STOP RISING within a
     few seconds of opening a clip; a counter that keeps climbing is the decay
     defect, visible before it is felt. */
  let ALLOCS=0;

  /* The two data textures the direct law reads, and the CPU-side sort that fills
     them. Grown to a high-water mark and never shrunk — the same discipline the
     rest of this file keeps, for the same reason. */
  let coefTex=null, boffTex=null;
  const coefDim=[0,0], boffDim=[0,0];
  let coefBuf=new Int32Array(0), boffBuf=new Int32Array(0), cnt=new Int32Array(0);

  /* Counting-sort a band's addresses into per-block runs.
   *
   * Returns the number of coefficients placed, or -1 if the band is better off
   * on the butterfly. The test is the crossover itself — mean addresses per
   * block against log2(block area) — computed from the count this pass already
   * has to make, so choosing costs nothing beyond the choice. */
  function packDirect(pts, level, tile, row0, rows){
    const nb = tile*tile, lg = Math.log2(nb)|0, blocks = BW*rows, f = 1<<level;
    if(cnt.length < blocks+1) cnt = new Int32Array(blocks+1);
    else cnt.fill(0, 0, blocks+1);
    let n = 0;
    for(let ch=0; ch<3; ch++){
      const a = pts[ch];
      for(let p=0; p<a.length; p+=2){
        const xy=a[p], x0=xy%PWS, y0=(xy/PWS)|0;
        const ic=x0&(BS-1), ir=y0&(BS-1);
        if(((ic|ir)&(f-1))!==0) continue;          // not on this rung's grid
        const by=(y0>>BSH)-row0;
        if(by<0||by>=rows) continue;                // another band's block
        cnt[(by*BW+(x0>>BSH))+1]++; n++;
      }
    }
    // Mean k against log2 N. Above it the transform is the cheaper law and this
    // band goes back to the butterfly — per band, because a draw call runs one
    // program, and the shader is already per-block within it.
    if(n >= blocks*lg) return -1;
    for(let b=0; b<blocks; b++) cnt[b+1]+=cnt[b];
    /* Size to the TEXTURE, not to `n`. A 2048-wide RG32I texture holding `n`
       texels has `ceil(n/2048)*2048` of them, and `texImage2D` rejects a view
       shorter than the full rectangle — silently, from the shader's point of
       view, which is a whole frame of wrong picture for a rounding error. */
    const need = 2*2048*Math.ceil(Math.max(1,n)/2048);
    if(coefBuf.length < need) coefBuf = new Int32Array(need);
    const th = Math.log2(tile)|0;
    for(let ch=0; ch<3; ch++){
      const a = pts[ch], tag = ch<<12;
      for(let p=0; p<a.length; p+=2){
        const xy=a[p], x0=xy%PWS, y0=(xy/PWS)|0;
        const ic=x0&(BS-1), ir=y0&(BS-1);
        if(((ic|ir)&(f-1))!==0) continue;
        const by=(y0>>BSH)-row0;
        if(by<0||by>=rows) continue;
        const at = cnt[by*BW+(x0>>BSH)]++;
        coefBuf[2*at]   = ((((ir>>level)<<th)|(ic>>level)) | tag);
        coefBuf[2*at+1] = a[p+1];
      }
    }
    // cnt[b] now holds the END of block b, so (start, count) reads back as
    // (end - count, count) with the count recovered from its neighbour.
    const oneed = 2*2048*Math.ceil(blocks/2048);
    if(boffBuf.length < oneed) boffBuf = new Int32Array(oneed);
    let prev = 0;
    for(let b=0; b<blocks; b++){
      const end = cnt[b];
      boffBuf[2*b] = prev; boffBuf[2*b+1] = end - prev; prev = end;
    }
    return n;
  }

  /* Paint one band's slice of the panel, from whichever accumulator holds it.
     The band covers field rows [ay0, ay0+ah); scissor to that slice so bands
     never overwrite each other. Shared by both laws — the resolve stage does not
     know or care which one produced the accumulator, which is exactly why the
     verify gate can compare them. */
  function paintBand(ay0, ah, level, vx, vy, vw, vh, verify){
    const SWl=W>>level, SHl=H>>level;
    const py0=Math.floor(ay0*vh/SHl), py1=Math.min(vh, Math.ceil((ay0+ah)*vh/SHl));
    if(py1<=py0) return;
    gl.bindFramebuffer(gl.FRAMEBUFFER,null);
    gl.viewport(vx,vy,vw,vh);
    gl.enable(gl.SCISSOR_TEST);
    // canvas y is bottom-up; the field row range maps to the top of the panel
    gl.scissor(vx, vy + (vh - py1), vw, py1-py0);
    gl.useProgram(pResolve);
    gl.bindVertexArray(vaoR);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D,tex[src]);
    gl.uniform1i(uR.ACC,0);
    gl.uniform1i(uR.VX,vx); gl.uniform1i(uR.VY,vy);
    gl.uniform1i(uR.VW,vw); gl.uniform1i(uR.VH,vh);
    gl.uniform1i(uR.SW,SWl); gl.uniform1i(uR.SH,SHl);
    gl.uniform1i(uR.SN,SN); gl.uniform1i(uR.VERIFY,verify);
    gl.uniform1i(uR.AY0,ay0);
    gl.drawArrays(gl.TRIANGLES,0,3);
    gl.bindVertexArray(null);
    gl.disable(gl.SCISSOR_TEST);
  }

  /* GROW-ONLY, never per frame.
   *
   * The address count changes from one frame to the next, so sizing a texture to
   * it means DELETING AND RECREATING two GPU textures every band of every frame.
   * That is the same allocation-churn defect that made the page decay from
   * smooth to stopped the first time, re-introduced on the GPU side — measured
   * as "slowing down" within a minute of it shipping.
   *
   * So the width is FIXED (which also keeps the shader's `p % CW` indexing
   * stable) and the height only ever grows, rounded to a power of two so it
   * settles after a handful of frames. Each frame uploads only the rows it
   * actually filled. */
  const DW = 2048;
  function dataTex(t, rows, buf, have){
    const need = 1 << Math.ceil(Math.log2(Math.max(1, rows)));
    if(!t || have[0] < need){
      if(t) gl.deleteTexture(t);
      t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D,t);
      for(const p of [gl.TEXTURE_MIN_FILTER,gl.TEXTURE_MAG_FILTER]) gl.texParameteri(gl.TEXTURE_2D,p,gl.NEAREST);
      for(const p of [gl.TEXTURE_WRAP_S,gl.TEXTURE_WRAP_T]) gl.texParameteri(gl.TEXTURE_2D,p,gl.CLAMP_TO_EDGE);
      have[0]=need;
      gl.texImage2D(gl.TEXTURE_2D,0,gl.RG32I,DW,need,0,gl.RG_INTEGER,gl.INT,null);
      ALLOCS++;
    } else {
      gl.bindTexture(gl.TEXTURE_2D,t);
    }
    gl.texSubImage2D(gl.TEXTURE_2D,0,0,0,DW,rows,gl.RG_INTEGER,gl.INT,buf);
    return t;
  }

  function itex(w,h){
    const t=gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D,t);
    gl.texStorage2D(gl.TEXTURE_2D,1,gl.RGBA32I,w,h);
    for(const p of [gl.TEXTURE_MIN_FILTER,gl.TEXTURE_MAG_FILTER]) gl.texParameteri(gl.TEXTURE_2D,p,gl.NEAREST);
    for(const p of [gl.TEXTURE_WRAP_S,gl.TEXTURE_WRAP_T]) gl.texParameteri(gl.TEXTURE_2D,p,gl.CLAMP_TO_EDGE);
    return t;
  }

  /* THE ACCUMULATOR BUDGET.
   *
   * The resolve scatters into an RGBA32I texture the size of the whole padded
   * field, ping-ponged for the butterfly — so it costs 32 BYTES PER PIXEL of
   * VRAM, not 4. At 4096x2176 that is 285 MB for the pair, which is heavy but
   * fine. At 8192x4320 it is 1.13 GB at a width sitting exactly on the 8192 cap
   * most GPUs report, and the allocation either fails into a software path or
   * thrashes. Either way the frame rate goes to zero with no error, which is the
   * worst possible way for a limit to announce itself.
   *
   * So the largest rung is CHOSEN against what the device will actually hold,
   * rather than attempted and hoped for. A smaller rung is not a degraded
   * picture here — it is a smaller output, which the format produces natively
   * from the same addresses.
   */
  const VRAM_BUDGET = 192 << 20;          // bytes for the ping-pong PAIR

  /* How many BLOCK ROWS one band may hold, so the pair fits the budget.
   *
   * A block never straddles a band boundary, so banding the accumulator is a
   * partition of the work and not an approximation — the output is identical to
   * resolving the whole field at once, which is the gate. What changes is that
   * memory becomes O(band) instead of O(field), so an 8K field no longer needs
   * 1.13 GB to resolve natively; it needs whatever one band costs.
   *
   * This does NOT reduce traffic: every band still runs its 2·log2(tile) passes.
   * It removes the wall, not the cost. */
  function bandRows(bw, bs, level, bhTotal){
    const tile = bs >> level, aw = bw * tile;
    const perRow = aw * tile * 16 * 2;              // one block row, both textures
    return Math.max(1, Math.min(bhTotal, Math.floor(VRAM_BUDGET / Math.max(1, perRow))));
  }

  /* The finest rung the device can hold AT ALL — width must fit MAX_TEXTURE_SIZE,
     since banding shrinks height but never width. */
  function maxLevel(bw, bh, bs, levels){
    const cap = gl.getParameter(gl.MAX_TEXTURE_SIZE);
    for(let L=0; L<levels; L++){
      const tile = bs >> L;
      if(bw * tile <= cap && tile <= cap) return L;
    }
    return levels - 1;
  }

  return {
    gl,
    /* The coarsest rung this device can actually resolve, and why. The player
       starts here instead of at native, so a field larger than the GPU can hold
       opens at a size it can rather than at zero frames a second. */
    limits(bw,bh,bs,levels){
      const L = maxLevel(bw,bh,bs,levels);
      const tile = bs >> L, rows = bandRows(bw,bs,L,bh);
      return { level:L,
               cap: gl.getParameter(gl.MAX_TEXTURE_SIZE),
               rows,
               bands: Math.ceil(bh/rows),
               vram: 2 * (bw*tile) * (rows*tile) * 16,
               acc: `${bw*tile}x${rows*tile}` };
    },
    /* `minLevel` is the FINEST rung this device agreed to hold. `PWS` stays at
       native regardless, because it is how the receiver encoded the scatter
       position and has nothing to do with how much VRAM we have — conflating the
       two would silently misplace every address. Only the ALLOCATION shrinks. */
    setup(w,h,bw,bh,bs,minLevel){
      W=w;H=h;BW=bw;BH=bh;BS=bs;BSH=Math.log2(bs)|0;SN=2*BSH;PWS=bw*bs;PHS=bh*bs;
      const ml=minLevel|0, atile=bs>>ml;
      BAND=bandRows(bw,bs,ml,bh);
      const AW=bw*atile, AH=BAND*atile;
      for(let i=0;i<2;i++){
        if(tex[i])gl.deleteTexture(tex[i]); if(fbo[i])gl.deleteFramebuffer(fbo[i]);
        tex[i]=itex(AW,AH);
        fbo[i]=gl.createFramebuffer();
        gl.bindFramebuffer(gl.FRAMEBUFFER,fbo[i]);
        gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,tex[i],0);
        const st=gl.checkFramebufferStatus(gl.FRAMEBUFFER);
        if(st!==gl.FRAMEBUFFER_COMPLETE) throw new Error("integer FBO incomplete: 0x"+st.toString(16));
      }
      gl.bindFramebuffer(gl.FRAMEBUFFER,null);
      return {PWS,PHS,AW,AH,minLevel:ml,band:BAND,bands:Math.ceil(bh/BAND)};
    },

    /* Resolve and paint, one BAND at a time.
     *
     * Resolve and paint are fused because a band's accumulator is overwritten by
     * the next band — there is no moment at which the whole field exists in
     * memory, which is the entire point. Blocks never straddle a band boundary,
     * so this is a partition of the same work: the output is identical to
     * resolving the field whole, and that is gated rather than asserted.
     */
    resolvePaint(pts, level, vx, vy, vw, vh, verify=-1){
      const tile=BS>>level, aw=BW*tile;
      const bands=Math.ceil(BH/BAND);
      PASSES=0; MOVED=0; DIRECT=0; BFLY=0;
      gl.disable(gl.SCISSOR_TEST);
      for(let b=0;b<bands;b++){
        const row0=b*BAND, rows=Math.min(BAND, BH-row0);
        const ay0=row0*tile, ah=rows*tile;

        /* ── the address's own law, when it is the cheaper one ──
           One pass, straight from the addresses, no scatter and no ping-pong. */
        /* WHICH LAW, FORCEABLE FROM THE URL.
           `?law=butterfly` pins the transform, `?law=direct` pins the row
           evaluation, absent lets the crossover choose. This exists because the
           crossover was measured on SwiftShader — a CPU rasteriser, where PASSES
           dominate and texture locality is free. A real GPU is the other way
           round: the butterfly reads coherent neighbours that hit texture cache,
           the direct law does one DEPENDENT fetch per coefficient per pixel.
           Two passes can be slower than fourteen on hardware I cannot measure
           from here, so the owner's device decides and the switch is one URL
           parameter, not another build. */
        // A stage cut is a cut through the BUTTERFLY path, so it pins that law —
        // otherwise `stage=scatter` would silently measure the direct law, which
        // has no scatter, and report a number about the wrong pipeline.
        const n = (LAW === "butterfly" || STAGE !== "full")
          ? -1 : packDirect(pts, level, tile, row0, rows);
        if(n >= 0){
          const blocks = BW*rows;
          const chh = Math.ceil(Math.max(1,n)/DW), oh = Math.ceil(blocks/DW);
          gl.activeTexture(gl.TEXTURE0);
          coefTex = dataTex(coefTex, chh, coefBuf, coefDim);
          gl.activeTexture(gl.TEXTURE1);
          boffTex = dataTex(boffTex, oh, boffBuf, boffDim);
          gl.bindFramebuffer(gl.FRAMEBUFFER,fbo[0]);
          gl.viewport(0,0,aw,ah);
          gl.useProgram(pDirect);
          gl.bindVertexArray(vaoD);
          gl.uniform1i(uD.COEF,0); gl.uniform1i(uD.BOFF,1);
          gl.uniform1i(uD.TILEH,Math.log2(tile)|0); gl.uniform1i(uD.BWL,BW);
          gl.uniform1i(uD.CW,DW); gl.uniform1i(uD.OW,DW);
          gl.drawArrays(gl.TRIANGLES,0,3);
          gl.bindVertexArray(null);
          src=0; PASSES++; DIRECT++; MOVED += aw*ah*16;
          gl.activeTexture(gl.TEXTURE0);
          paintBand(ay0, ah, level, vx, vy, vw, vh, verify);
          continue;
        }
        BFLY++;

        /* stage=none — paint what is already in the accumulator. No address
           upload, no rasterisation, no transform. What is left is the frame
           plumbing plus one full-screen resolve, and if THAT alone cannot hold
           the rate then nothing in this file is the problem. */
        if(STAGE === "none"){ paintBand(ay0, ah, level, vx, vy, vw, vh, verify); continue; }

        // ── scatter this band ──
        gl.bindFramebuffer(gl.FRAMEBUFFER,fbo[0]);
        gl.viewport(0,0,aw,ah);
        gl.clearBufferiv(gl.COLOR,0,new Int32Array([0,0,0,0]));
        gl.useProgram(pScatter);
        gl.uniform1i(uS.PWS,PWS); gl.uniform1i(uS.LEVEL,level); gl.uniform2f(uS.RES,aw,ah);
        gl.uniform1i(uS.BS,BS); gl.uniform1i(uS.BSH,BSH);
        gl.uniform1i(uS.AY0,ay0); gl.uniform1i(uS.AYN,ah);
        gl.bindVertexArray(vaoP);
        for(let ch=0;ch<3;ch++){
          if(!pts[ch].length) continue;
          gl.colorMask(ch===0,ch===1,ch===2,false);
          gl.bindBuffer(gl.ARRAY_BUFFER,ptsBuf);
          gl.bufferData(gl.ARRAY_BUFFER,pts[ch],gl.STREAM_DRAW);
          gl.drawArrays(gl.POINTS,0,pts[ch].length/2);
        }
        gl.colorMask(true,true,true,true);

        // ── butterfly this band ──
        gl.activeTexture(gl.TEXTURE0);
        src=0;
        if(STAGE === "scatter"){ paintBand(ay0, ah, level, vx, vy, vw, vh, verify); continue; }
        for(const axis of [0,1]){
          let hh=1;
          while(hh<tile){
            // two levels at once whenever both fit; the last one on an odd
            // log2(tile) falls back to radix-2
            const four = (hh<<1) < tile;
            const P = four ? pBfly4 : pBfly, u = four ? uB4 : uB;
            gl.useProgram(P);
            gl.bindVertexArray(four ? vaoB4 : vaoB);
            gl.uniform1i(u.SRC,0); gl.uniform1i(u.MASK,tile-1);
            gl.bindFramebuffer(gl.FRAMEBUFFER,fbo[1-src]);
            gl.viewport(0,0,aw,ah);
            gl.bindTexture(gl.TEXTURE_2D,tex[src]);
            gl.uniform1i(u.H,hh); gl.uniform1i(u.AXIS,axis);
            gl.drawArrays(gl.TRIANGLES,0,3);
            src=1-src;
            PASSES++;
            // one WRITE per pass either way; writes are the traffic that cannot
            // be cached away, so they are counted separately from reads
            MOVED += aw*ah*16;
            hh <<= four ? 2 : 1;
          }
        }

        paintBand(ay0, ah, level, vx, vy, vw, vh, verify);
      }
      return {tile, w:W>>level, h:H>>level, bands, passes:PASSES, moved:MOVED,
              direct:DIRECT, bfly:BFLY};
    },

    /* What the last frame actually cost, so the traffic figure on the page is
       measured rather than asserted. */
    traffic(){ return {passes:PASSES, moved:MOVED, band:BAND, direct:DIRECT, bfly:BFLY,
                       allocs:ALLOCS, stage:STAGE, law:LAW||"auto"}; },

    clear(){ gl.bindFramebuffer(gl.FRAMEBUFFER,null);
             gl.viewport(0,0,canvas.width,canvas.height);
             gl.clearColor(0.027,0.031,0.051,1); gl.clear(gl.COLOR_BUFFER_BIT); },

    /* Prove the port: raw luma, no colour mapping, compared byte-for-byte against
       the compiled core's own resolve of the same addresses. */
    verifyLuma(refBytes, w, h, samples=20000){
      const px=new Uint8Array(w*h*4);
      gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,px);
      const step=Math.max(1,Math.floor((w*h)/samples));
      let checked=0,bad=0,worst=0;
      for(let i=0;i<w*h;i+=step){
        const x=i%w, y=(i/w)|0;
        const d=Math.abs(px[((h-1-y)*w+x)*4]-refBytes[y*w+x]);
        if(d>0){bad++; worst=Math.max(worst,d);}
        checked++;
      }
      return {checked,bad,worst};
    }
  };
}
