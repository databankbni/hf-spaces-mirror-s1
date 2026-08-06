import { useState, useEffect, useCallback } from "react";
import {
  MapContainer, TileLayer, Marker, Popup,
  useMapEvents, useMap, Rectangle,
} from "react-leaflet";
import axios from "axios";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar, RadarChart, Radar,
  PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine, Brush, Legend, ComposedChart,
} from "recharts";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl:"https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  iconUrl:      "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  shadowUrl:    "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

const USA_BOUNDS = [[24.396308,-125.0],[49.384358,-66.93457]];
const USA_CENTER = [37.0902,-95.7129];
const TILE_DARK  = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";
const TILE_LIGHT = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
const ATTR = '&copy; <a href="https://carto.com/">CARTO</a>';

const CORRIDORS = [
  {name:"Los Angeles — I-405 North",  lat:34.0522, lng:-118.2437, state:"CA"},
  {name:"San Francisco — US-101",     lat:37.7749, lng:-122.4194, state:"CA"},
  {name:"New York — I-95 Cross Bronx",lat:40.8522, lng:-73.8964,  state:"NY"},
  {name:"Washington DC — I-495",      lat:38.9072, lng:-77.0369,  state:"DC"},
  {name:"Miami — I-95 Express",       lat:25.7617, lng:-80.1918,  state:"FL"},
  {name:"Orlando — I-4 Corridor",     lat:28.5383, lng:-81.3792,  state:"FL"},
  {name:"Chicago — I-290 Eisenhower", lat:41.8781, lng:-87.6298,  state:"IL"},
  {name:"Seattle — I-5 NB",           lat:47.6062, lng:-122.3321, state:"WA"},
  {name:"Dallas — I-635 LBJ Fwy",     lat:32.7767, lng:-96.7970,  state:"TX"},
  {name:"Boston — I-93 Big Dig",      lat:42.3601, lng:-71.0589,  state:"MA"},
];

const DARK = {
  bg:"#050810", panel:"#090d1a", card:"#0d1220", cardHov:"#111829",
  border:"rgba(255,255,255,0.055)", borderHov:"rgba(99,179,237,0.4)",
  accent:"#63b3ed", accentDim:"rgba(99,179,237,0.1)", accentMid:"rgba(99,179,237,0.22)",
  orange:"#f6ad55", orangeDim:"rgba(246,173,85,0.1)",
  green:"#68d391", greenDim:"rgba(104,211,145,0.1)",
  red:"#fc8181", redDim:"rgba(252,129,129,0.1)",
  amber:"#f6e05e", amberDim:"rgba(246,224,94,0.1)",
  purple:"#b794f4", purpleDim:"rgba(183,148,244,0.1)",
  teal:"#4fd1c5", tealDim:"rgba(79,209,197,0.1)",
  text:"#e8f0fb", sub:"#4a6880", faint:"#141e30",
  shadow:"0 4px 28px rgba(0,0,0,0.6)", shadowHov:"0 10px 48px rgba(0,0,0,0.75)",
  glow:"0 0 30px rgba(99,179,237,0.15)",
};
const LIGHT = {
  bg:"#eef2f7", panel:"#ffffff", card:"#ffffff", cardHov:"#f4f8ff",
  border:"rgba(0,0,0,0.07)", borderHov:"rgba(49,130,206,0.35)",
  accent:"#2b6cb0", accentDim:"rgba(43,108,176,0.08)", accentMid:"rgba(43,108,176,0.18)",
  orange:"#c05621", orangeDim:"rgba(192,86,33,0.08)",
  green:"#276749", greenDim:"rgba(39,103,73,0.08)",
  red:"#c53030", redDim:"rgba(197,48,48,0.08)",
  amber:"#975a16", amberDim:"rgba(151,90,22,0.08)",
  purple:"#553c9a", purpleDim:"rgba(85,60,154,0.08)",
  teal:"#285e61", tealDim:"rgba(40,94,97,0.08)",
  text:"#0f1d2c", sub:"#4a6a88", faint:"#d8e6f3",
  shadow:"0 2px 18px rgba(0,0,0,0.07)", shadowHov:"0 6px 32px rgba(0,0,0,0.14)",
  glow:"none",
};

const riskColor  = (v,T) => v>=70?T.red:v>=40?T.orange:T.green;
const riskDim    = (v,T) => v>=70?T.redDim:v>=40?T.orangeDim:T.greenDim;
const riskLabel  = v     => v>=70?"Heavy Traffic":v>=40?"Moderate Traffic":"Roads Clear";
const speedColor = (drop, T) => drop >= 30 ? T.red : drop >= 15 ? T.orange : T.green;

const makeMock = (lat,lng) => {
  const seed=Math.abs(Math.sin(lat*7.3+lng*3.1)*100)%100;
  const cur=Math.round(seed);
  const temp=Math.round(10+((lat-25)/25)*15+Math.random()*6);
  const freeFlow=Math.round(60+Math.random()*30);
  const h0=new Date().getHours();
  const fc=Array.from({length:24},(_,i)=>{
    const h=(h0+i)%24;
    const pk=h>=7&&h<=9?1.7:h>=16&&h<=19?1.9:h>=22||h<=5?0.25:1;
    const r=Math.min(99,Math.max(3,Math.round(seed*pk+(Math.random()*14-7))));
    const rf=Math.min(99,Math.max(3,Math.round(r+(Math.random()*12-6))));
    const xg=Math.min(99,Math.max(3,Math.round(r+(Math.random()*12-6))));
    const drop=Math.round((r/100)*freeFlow*0.7+(Math.random()*5));
    return {
      time:`${String(h).padStart(2,"00")}:00`,
      risk_percent:r, rf_score:rf, xgb_score:xg,
      speed_drop_kmh:drop,
      predicted_speed_kmh:Math.max(0,freeFlow-drop),
    };
  });
  return {
    current_prediction:{
      current_risk:cur, ui_color_code:cur>=35?"RED":"GREEN",
      current_temp:temp, feels_like:temp-2,
      humidity:Math.round(38+Math.random()*44),
      wind_speed_kmh:Math.round(6+Math.random()*28),
      city_name:"Demo Mode", weather_desc:"Simulated data",
      free_flow_speed_kmh:freeFlow,
      speed_drop_kmh:Math.round((cur/100)*freeFlow*0.7),
      predicted_speed_kmh:Math.max(0,freeFlow-Math.round((cur/100)*freeFlow*0.7)),
    },
    forecast_24h:fc,
    model_metadata:{ensemble:true,rf_weight:0.45,xgb_weight:0.55,regression_active:true},
    // Mocking only if API fails, otherwise backend sends real data
    model_performance: {
        rf: {acc: 0.784, prec: 0.893, rec: 0.784, f1: 0.8190, auc: 0.85, confMatrix: [[1428, 180], [45, 135]]},
        xgb: {acc: 0.847, prec: 0.911, rec: 0.847, f1: 0.8675, auc: 0.92, confMatrix: [[1428, 180], [32, 148]]},
        reg: {mae: 3.59, rmse: 6.08, r2: 0.4164, mape: 0.08, evs: 0.42},
        importances: [
            {feature: "Hour Of Day", rf: 32, xgb: 28, reg: 35},
            {feature: "Rush Hour Flag", rf: 24, xgb: 31, reg: 27},
            {feature: "Temperature C", rf: 18, xgb: 15, reg: 13},
            {feature: "Humidity", rf: 12, xgb: 11, reg: 10},
            {feature: "Weekend Flag", rf: 8, xgb: 9, reg: 7},
            {feature: "Visibility", rf: 6, xgb: 6, reg: 8},
        ],
        trainingHistory: Array.from({length:20},(_,i)=>({epoch:i, rf_train:0.85, rf_val:0.81, xgb_train:0.9, xgb_val:0.86, reg_train:0.5, reg_val:0.41})),
        radarMetrics: [
            {metric: "Accuracy", rf: 78, xgb: 84}, {metric: "Precision", rf: 89, xgb: 91},
            {metric: "Recall", rf: 78, xgb: 84}, {metric: "F1 Score", rf: 82, xgb: 86},
            {metric: "Speed", rf: 60, xgb: 75}, {metric: "Stability", rf: 85, xgb: 80},
        ],
        residuals: Array.from({length:40},(_,i)=>({actual: 10, predicted: 12, residual: 2, idx: i}))
    }
  };
};

const MapClicker = ({onPick}) => { useMapEvents({click(e){onPick(e.latlng);}}); return null; };
const MaxBounds  = () => { const map=useMap(); useEffect(()=>{map.setMaxBounds(USA_BOUNDS);map.options.minZoom=4;},[map]); return null; };
const FlyTo      = ({target}) => { const map=useMap(); useEffect(()=>{if(target)map.flyTo(target,11,{animate:true,duration:1.3});},[target,map]); return null; };

const ChartTip = ({active,payload,label,T}) => {
  if(!active||!payload?.length) return null;
  const main=payload.find(p=>p.dataKey==="risk_percent");
  const rf=payload.find(p=>p.dataKey==="rf_score");
  const xgb=payload.find(p=>p.dataKey==="xgb_score");
  const v=main?.value??payload[0]?.value??0;
  const col=riskColor(v,T);
  return(
    <div style={{background:T.panel,border:`1px solid ${T.border}`,borderRadius:10,padding:"12px 16px",boxShadow:T.shadow,fontFamily:"inherit"}}>
      <div style={{color:T.sub,fontSize:10,marginBottom:4}}>{label}</div>
      <div style={{color:col,fontSize:22,fontWeight:900,lineHeight:1}}>{v}<span style={{fontSize:11,fontWeight:400}}>%</span></div>
      <div style={{color:col,fontSize:9,marginTop:3,letterSpacing:1}}>{riskLabel(v)}</div>
      {(rf||xgb)&&<div style={{marginTop:8,paddingTop:8,borderTop:`1px solid ${T.border}`,display:"flex",gap:14}}>
        {rf&&<span style={{fontSize:10,color:T.sub}}>Forest <b style={{color:T.accent}}>{rf.value}%</b></span>}
        {xgb&&<span style={{fontSize:10,color:T.sub}}>Booster <b style={{color:T.orange}}>{xgb.value}%</b></span>}
      </div>}
    </div>
  );
};

const SpeedTip = ({active,payload,label,T,freeFlow}) => {
  if(!active||!payload?.length) return null;
  const drop=payload.find(p=>p.dataKey==="speed_drop_kmh");
  const speed=payload.find(p=>p.dataKey==="predicted_speed_kmh");
  const dropVal=drop?.value??0;
  const col=speedColor(dropVal,T);
  return(
    <div style={{background:T.panel,border:`1px solid ${T.border}`,borderRadius:10,padding:"12px 16px",boxShadow:T.shadow,fontFamily:"inherit"}}>
      <div style={{color:T.sub,fontSize:10,marginBottom:6}}>{label}</div>
      {speed&&<div style={{marginBottom:4}}>
        <span style={{fontSize:10,color:T.sub}}>Pred Speed: </span>
        <b style={{fontSize:14,color:T.teal}}>{speed.value} km/h</b>
      </div>}
      {drop&&<div>
        <span style={{fontSize:10,color:T.sub}}>Speed Drop: </span>
        <b style={{fontSize:14,color:col}}>-{dropVal} km/h</b>
      </div>}
      {freeFlow&&<div style={{marginTop:6,paddingTop:6,borderTop:`1px solid ${T.border}`,fontSize:9,color:T.sub}}>
        Free Flow: <b style={{color:T.sub}}>{freeFlow} km/h</b>
      </div>}
    </div>
  );
};

const PerfTip = ({active,payload,label,T}) => {
  if(!active||!payload?.length) return null;
  return(
    <div style={{background:T.panel,border:`1px solid ${T.border}`,borderRadius:10,padding:"10px 14px",boxShadow:T.shadow,fontFamily:"inherit"}}>
      <div style={{color:T.sub,fontSize:10,marginBottom:6}}>{label}</div>
      {payload.map(p=>(
        <div key={p.dataKey} style={{display:"flex",justifyContent:"space-between",gap:18,fontSize:11,marginBottom:3}}>
          <span style={{color:T.sub}}>{p.name}</span>
          <b style={{color:p.color}}>{typeof p.value==="number"&&p.value<1.5?(p.value*100).toFixed(1)+"%":p.value}</b>
        </div>
      ))}
    </div>
  );
};

const SectionHeader = ({icon,title,sub,badge,badgeColor,T}) => (
  <div style={{marginBottom:14}}>
    <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:4}}>
      <span style={{fontSize:17}}>{icon}</span>
      <span style={{fontSize:13,fontWeight:700,color:T.text,letterSpacing:.3}}>{title}</span>
      {badge&&<span style={{fontSize:8,letterSpacing:1.5,color:badgeColor||T.accent,background:(badgeColor||T.accent)+"18",padding:"2px 8px",borderRadius:20,border:`1px solid ${(badgeColor||T.accent)}30`,fontWeight:700}}>{badge}</span>}
    </div>
    {sub&&<div style={{fontSize:9,color:T.sub,letterSpacing:1.2,paddingLeft:27}}>{sub}</div>}
  </div>
);

const StatCard = ({label,value,sub,color,icon,bar,T}) => (
  <div style={{background:T.card,border:`1px solid ${T.border}`,borderRadius:14,padding:"16px 18px",boxShadow:T.shadow,transition:"all .22s ease",borderLeft:`3px solid ${color}`,cursor:"default"}}
    onMouseEnter={e=>{e.currentTarget.style.transform="translateY(-3px)";e.currentTarget.style.boxShadow=T.shadowHov;}}
    onMouseLeave={e=>{e.currentTarget.style.transform="";e.currentTarget.style.boxShadow=T.shadow;}}>
    <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:8}}>
      <div style={{fontSize:8,letterSpacing:2,color:T.sub,textTransform:"uppercase"}}>{label}</div>
      <span style={{fontSize:16}}>{icon}</span>
    </div>
    <div style={{fontSize:26,fontWeight:900,color,lineHeight:1,marginBottom:5}}>{value}</div>
    {bar!=null&&<div style={{height:3,background:T.faint,borderRadius:2,overflow:"hidden",marginBottom:5}}>
      <div style={{height:"100%",width:`${Math.min(100,bar)}%`,background:color,borderRadius:2,transition:"width 1.2s ease"} }/>
    </div>}
    {sub&&<div style={{fontSize:9,color:T.sub,letterSpacing:.5}}>{sub}</div>}
  </div>
);

const ProgMetric = ({label,rfVal,xgbVal,T}) => {
  const rf=parseFloat((rfVal*100).toFixed(1));
  const xgb=parseFloat((xgbVal*100).toFixed(1));
  const winner=xgb>=rf?"xgb":"rf";
  return(
    <div style={{marginBottom:14}}>
      <div style={{display:"flex",justifyContent:"space-between",marginBottom:5}}>
        <span style={{fontSize:10,color:T.text,fontWeight:600}}>{label}</span>
        <div style={{display:"flex",gap:12}}>
          <span style={{fontSize:10,color:T.accent,fontWeight:700}}>{rf}%</span>
          <span style={{fontSize:10,color:T.orange,fontWeight:700}}>{xgb}%</span>
        </div>
      </div>
      <div style={{display:"flex",flexDirection:"column",gap:4}}>
        {[{key:"rf",label:"FOREST",color:T.accent,val:rf,win:winner==="rf"},{key:"xgb",label:"BOOSTER",color:T.orange,val:xgb,win:winner==="xgb"}].map(m=>(
          <div key={m.key} style={{display:"flex",alignItems:"center",gap:8}}>
            <div style={{width:52,fontSize:8,color:T.sub,letterSpacing:1}}>{m.label}</div>
            <div style={{flex:1,height:7,background:T.faint,borderRadius:4,overflow:"hidden"}}>
              <div style={{height:"100%",width:`${m.val}%`,background:m.color,borderRadius:4,transition:"width 1.2s ease",boxShadow:m.win?`0 0 8px ${m.color}60`:"none"} }/>
            </div>
            {m.win&&<span style={{fontSize:8,color:m.color}}>▲</span>}
          </div>
        ))}
      </div>
    </div>
  );
};

const ConfusionMatrix = ({matrix,title,color,T}) => {
  const cells=[
    {label:"TN",desc:"True Neg",val:matrix[0][0],good:true},
    {label:"FP",desc:"False Pos",val:matrix[0][1],good:false},
    {label:"FN",desc:"False Neg",val:matrix[1][0],good:false},
    {label:"TP",desc:"True Pos",val:matrix[1][1],good:true},
  ];
  return(
    <div>
      <div style={{fontSize:10,color:T.sub,letterSpacing:1.5,marginBottom:10,textTransform:"uppercase"}}>{title}</div>
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:4}}>
        {cells.map(c=>(
          <div key={c.label} style={{background:c.good?`${color}18`:`${T.red}10`,border:`1px solid ${c.good?color+30:T.red+20}`,borderRadius:8,padding:"10px 8px",textAlign:"center"}}>
            <div style={{fontSize:16,fontWeight:900,color:c.good?color:T.red}}>{c.val.toLocaleString()}</div>
            <div style={{fontSize:8,color:T.sub,letterSpacing:1}}>{c.desc}</div>
            <div style={{fontSize:7,color:c.good?color:T.red,marginTop:2,fontWeight:700}}>{c.label}</div>
          </div>
        ))}
      </div>
      <div style={{fontSize:9,color:T.sub,marginTop:6,textAlign:"center"}}>
        n = {(matrix[0][0]+matrix[0][1]+matrix[1][0]+matrix[1][1]).toLocaleString()} samples
      </div>
    </div>
  );
};

const RegMetricCard = ({label,value,sub,color,icon,T,unit=""}) => (
  <div style={{background:T.card,border:`1px solid ${color}22`,borderLeft:`3px solid ${color}`,borderRadius:14,padding:"16px 18px",boxShadow:T.shadow,transition:"all .22s ease",cursor:"default"}}
    onMouseEnter={e=>{e.currentTarget.style.transform="translateY(-3px)";e.currentTarget.style.boxShadow=T.shadowHov;}}
    onMouseLeave={e=>{e.currentTarget.style.transform="";e.currentTarget.style.boxShadow=T.shadow;}}>
    <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:8}}>
      <div style={{fontSize:8,letterSpacing:2,color:T.sub,textTransform:"uppercase"}}>{label}</div>
      <span style={{fontSize:16}}>{icon}</span>
    </div>
    <div style={{fontSize:26,fontWeight:900,color,lineHeight:1,marginBottom:5}}>
      {value}<span style={{fontSize:12,color:T.sub,fontWeight:400}}>{unit}</span>
    </div>
    {sub&&<div style={{fontSize:9,color:T.sub,letterSpacing:.5}}>{sub}</div>}
  </div>
);

export default function App() {
  const [dark,     setDark]    = useState(true);
  const [data,     setData]    = useState(null);
  const [loading,  setLoading] = useState(false);
  const [pin,      setPin]     = useState(null);
  const [flyTo,    setFlyTo]   = useState(null);
  const [searchQ,  setSearch]  = useState("");
  const [drop,     setDrop]    = useState(false);
  const [animIn,   setAnimIn]  = useState(false);
  const [chartMode,setChart]   = useState("area");
  const [activeTab,setTab]     = useState("forecast");
  const [perfTab,  setPerfTab] = useState("overview");

  const T = dark ? DARK : LIGHT;
  useEffect(()=>{ setTimeout(()=>setAnimIn(true),80); },[]);

  const filtered = CORRIDORS.filter(c=>{
    if(!searchQ.trim()) return false;
    const q=searchQ.toLowerCase();
    return c.name.toLowerCase().includes(q)||c.state.toLowerCase().includes(q);
  }).slice(0,7);

  const fetchData = useCallback(async(lat,lng)=>{
    setLoading(true); setData(null);
    try{
      const res=await axios.post("https://sheikhali4221-traffic-ml.hf.space/predict",{lat:parseFloat(lat),lng:parseFloat(lng)},{timeout:10000});
      setData(res.data);
    }catch{
      await new Promise(r=>setTimeout(r,900));
      setData(makeMock(lat,lng));
    }finally{ setLoading(false); }
  },[]);

  const pickLocation=(lat,lng)=>{setPin({lat,lng});setFlyTo([lat,lng]);fetchData(lat,lng);};
  const mapClick=({lat,lng})=>{ if(lat<24.4||lat>49.4||lng<-125||lng>-66.9) return; pickLocation(lat,lng); };

  const fc        = data?.forecast_24h??[];
  const score     = data ? Math.round(Number(data.current_prediction?.current_risk??0)) : 0;
  const isCon     = data?.current_prediction?.ui_color_code==="RED";
  const liveCol   = riskColor(score,T);
  const liveDim   = riskDim(score,T);
  const maxRisk   = fc.length ? Math.max(...fc.map(d=>d.risk_percent)) : 0;
  const minRisk   = fc.length ? Math.min(...fc.map(d=>d.risk_percent)) : 0;
  const avgRisk   = fc.length ? Math.round(fc.reduce((a,b)=>a+b.risk_percent,0)/fc.length) : 0;
  const peakH     = fc.find(d=>d.risk_percent===maxRisk)?.time??"--";
  const bestH     = fc.find(d=>d.risk_percent===minRisk)?.time??"--";
  const rfAvg     = fc.length ? Math.round(fc.reduce((a,b)=>a+(b.rf_score??0),0)/fc.length) : 0;
  const xgbAvg    = fc.length ? Math.round(fc.reduce((a,b)=>a+(b.xgb_score??0),0)/fc.length) : 0;
  const freeFlow  = data?.current_prediction?.free_flow_speed_kmh??65;
  const curDrop   = data?.current_prediction?.speed_drop_kmh??0;
  const curSpeed  = data?.current_prediction?.predicted_speed_kmh??freeFlow;
  const maxDrop   = fc.length ? Math.max(...fc.map(d=>d.speed_drop_kmh??0)) : 0;
  const avgSpeed  = fc.length ? Math.round(fc.reduce((a,b)=>a+(b.predicted_speed_kmh??0),0)/fc.length) : 0;
  const worstSpeedH = fc.find(d=>(d.speed_drop_kmh??0)===maxDrop)?.time??"--";

  const regActive = true; 

  const segments=[
    {label:"Early AM",hours:[0,1,2,3,4,5]},
    {label:"AM Rush", hours:[6,7,8,9]},
    {label:"Midday",  hours:[10,11,12,13,14]},
    {label:"PM Rush", hours:[15,16,17,18,19]},
    {label:"Night",   hours:[20,21,22,23]},
  ];
  const compData=segments.map(s=>{
    const rows=fc.filter(d=>s.hours.includes(parseInt(d.time)));
    const avg=arr=>arr.length?Math.round(arr.reduce((a,b)=>a+b,0)/arr.length):0;
    return {period:s.label,Forest:avg(rows.map(d=>d.rf_score??0)),Booster:avg(rows.map(d=>d.xgb_score??0)),Final:avg(rows.map(d=>d.risk_percent))};
  });

  const perf=data?.model_performance;

  const renderForecast = () => (
    <div style={{animation:"fadeUp .5s ease both"}}>

      <div style={{
        background:isCon?`linear-gradient(135deg,${T.redDim},${T.card})`:`linear-gradient(135deg,${T.greenDim},${T.card})`,
        border:`1px solid ${liveCol}28`,borderLeft:`4px solid ${liveCol}`,
        borderRadius:16,padding:"20px 26px",marginBottom:14,
        display:"flex",justifyContent:"space-between",alignItems:"center",flexWrap:"wrap",gap:14,
        boxShadow:T.shadow,
      }}>
        <div>
          <div style={{fontSize:9,color:T.sub,letterSpacing:2.5,marginBottom:5,textTransform:"uppercase"}}>
            {data.current_prediction?.city_name??"Selected Location"} · Live
          </div>
          <div style={{fontSize:22,fontWeight:900,color:liveCol,marginBottom:4}}>
            {isCon?"🔴  High Congestion Detected":"🟢  Traffic Conditions Clear"}
          </div>
          <div style={{fontSize:10,color:T.sub}}>
            {data.current_prediction?.weather_desc??"Live conditions"} &nbsp;·&nbsp; Feels {Math.round(data.current_prediction?.feels_like??data.current_prediction?.current_temp??0)}°C
          </div>
        </div>
        <div style={{display:"flex",gap:22,alignItems:"center",flexWrap:"wrap"}}>
          <div style={{textAlign:"center"}}>
            <div style={{width:88,height:88,borderRadius:"50%",border:`3px solid ${liveCol}40`,
              display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",background:liveDim}}>
              <div style={{fontSize:27,fontWeight:900,color:liveCol,lineHeight:1}}>{score}</div>
              <div style={{fontSize:7,color:T.sub,letterSpacing:1}}>/100</div>
            </div>
            <div style={{fontSize:8,color:T.sub,marginTop:4,letterSpacing:1}}>CONGESTION SCORE</div>
          </div>
          <div style={{display:"flex",flexDirection:"column",gap:7}}>
            {[
              {icon:"🌡",val:`${Math.round(data.current_prediction?.current_temp??0)}°C`,lbl:"Temp"},
              {icon:"💧",val:`${Math.round(data.current_prediction?.humidity??0)}%`,lbl:"Humidity"},
              {icon:"💨",val:`${Math.round(data.current_prediction?.wind_speed_kmh??0)} km/h`,lbl:"Wind"},
            ].map(s=>(
              <div key={s.lbl} style={{display:"flex",alignItems:"center",gap:8}}>
                <span style={{fontSize:12}}>{s.icon}</span>
                <span style={{fontSize:13,fontWeight:700,color:T.text}}>{s.val}</span>
                <span style={{fontSize:8,color:T.sub,letterSpacing:1}}>{s.lbl}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {regActive&&(
        <div style={{
          background:T.card,border:`1px solid ${T.teal}25`,borderLeft:`4px solid ${T.teal}`,
          borderRadius:14,padding:"14px 20px",marginBottom:14,
          display:"flex",gap:28,alignItems:"center",flexWrap:"wrap",
          boxShadow:T.shadow,
        }}>
          <div style={{fontSize:9,color:T.teal,letterSpacing:2,fontWeight:700,textTransform:"uppercase",minWidth:120}}>
            🚗 Speed Regressor
          </div>
          {[
            {lbl:"Free Flow",val:`${freeFlow} km/h`,col:T.green,icon:"🛣"},
            {lbl:"Speed Drop Now",val:`-${curDrop} km/h`,col:speedColor(curDrop,T),icon:"📉"},
            {lbl:"Predicted Speed",val:`${curSpeed} km/h`,col:T.teal,icon:"⚡"},
            {lbl:"Worst Drop",val:`-${maxDrop} km/h`,col:T.red,icon:"⚠️"},
            {lbl:"Avg 24h Speed",val:`${avgSpeed} km/h`,col:T.sub,icon:"📊"},
            {lbl:"Drop at",val:worstSpeedH,col:T.orange,icon:"🕐"},
          ].map(s=>(
            <div key={s.lbl} style={{textAlign:"center",minWidth:80}}>
              <div style={{fontSize:9,color:T.sub,marginBottom:3,letterSpacing:1}}>{s.icon} {s.lbl}</div>
              <div style={{fontSize:15,fontWeight:900,color:s.col}}>{s.val}</div>
            </div>
          ))}
        </div>
      )}

      <div style={{display:"grid",gridTemplateColumns:"repeat(6,1fr)",gap:10,marginBottom:14}}>
        <StatCard label="Peak Risk"    value={`${maxRisk}%`}     sub={`at ${peakH}`}                             color={riskColor(maxRisk,T)} icon="📈" bar={maxRisk} T={T}/>
        <StatCard label="Best Window"  value={bestH}             sub={`${minRisk}% risk`}                        color={T.green}              icon="✅" bar={minRisk} T={T}/>
        <StatCard label="Daily Avg"    value={`${avgRisk}%`}     sub="24h mean"                                  color={riskColor(avgRisk,T)} icon="📊" bar={avgRisk} T={T}/>
        <StatCard label="Forest Avg"   value={`${rfAvg}%`}       sub="Random Forest"                             color={T.accent}             icon="🌲" bar={rfAvg}   T={T}/>
        <StatCard label="Booster Avg"  value={`${xgbAvg}%`}      sub="XGBoost"                                   color={T.orange}             icon="⚡" bar={xgbAvg}  T={T}/>
        <StatCard label="Agreement"    value={`${Math.max(0,100-Math.abs(rfAvg-xgbAvg))}%`}
          sub={Math.abs(rfAvg-xgbAvg)<5?"Models aligned":"Divergence detected"}
          color={Math.abs(rfAvg-xgbAvg)<5?T.green:T.amber} icon="🤝"
          bar={Math.max(0,100-Math.abs(rfAvg-xgbAvg))} T={T}/>
      </div>

      {regActive&&(
        <div style={{background:T.card,border:`1px solid ${T.teal}22`,borderRadius:16,padding:"18px 20px",boxShadow:T.shadow,marginBottom:12}}>
          <SectionHeader icon="🚗" title="XGBoost Regressor — 24h Speed Prediction"
            sub="Predicted speed drop and actual road speed across the day" badge="REGRESSION" badgeColor={T.teal} T={T}/>
          <div style={{height:220}}>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={fc} margin={{top:4,right:4,left:-20,bottom:0}}>
                <defs>
                  <linearGradient id="gSpeed" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor={T.teal}  stopOpacity={.22}/>
                    <stop offset="95%" stopColor={T.teal}  stopOpacity={.01}/>
                  </linearGradient>
                  <linearGradient id="gDrop" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor={T.orange} stopOpacity={.18}/>
                    <stop offset="95%" stopColor={T.orange} stopOpacity={.01}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={dark?"rgba(255,255,255,.04)":"rgba(0,0,0,.05)"}/>
                <XAxis dataKey="time" stroke={T.sub} tick={{fill:T.sub,fontSize:9}}/>
                <YAxis yAxisId="speed" orientation="left"  stroke={T.sub} tick={{fill:T.sub,fontSize:9}} label={{value:"km/h",fill:T.sub,fontSize:8,angle:-90,position:"insideLeft"}}/>
                <YAxis yAxisId="drop"  orientation="right" stroke={T.sub} tick={{fill:T.sub,fontSize:9}} label={{value:"Drop",fill:T.sub,fontSize:8,angle:90,position:"insideRight"}}/>
                <Tooltip content={<SpeedTip T={T} freeFlow={freeFlow}/>}/>
                <ReferenceLine yAxisId="speed" y={freeFlow} stroke={T.green} strokeDasharray="5 3" strokeWidth={1.5}
                  label={{value:`Free Flow ${freeFlow}`,fill:T.green,fontSize:8,position:"insideTopRight"}}/>
                <Area  yAxisId="speed" type="monotone" dataKey="predicted_speed_kmh" stroke={T.teal}   strokeWidth={2.5} fill="url(#gSpeed)" dot={false}
                  activeDot={{r:5,stroke:T.teal,strokeWidth:2,fill:T.card}} animationDuration={1000} name="Predicted Speed"/>
                <Bar   yAxisId="drop"  dataKey="speed_drop_kmh" fill={T.orange} opacity={.55} radius={[2,2,0,0]} maxBarSize={14} name="Speed Drop"/>
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div style={{display:"flex",gap:20,marginTop:10,flexWrap:"wrap"}}>
            {[{col:T.teal,lbl:"Predicted Speed (km/h)",dash:false},{col:T.orange,lbl:"Speed Drop (km/h)",dot:true},{col:T.green,lbl:`Free Flow ${freeFlow} km/h`,dash:true}].map(({col,lbl,dash,dot})=>(
              <div key={lbl} style={{display:"flex",alignItems:"center",gap:6}}>
                {dot?<div style={{width:8,height:8,borderRadius:2,background:col}}/>:
                  <div style={{width:20,height:2.5,background:col,backgroundImage:dash?`repeating-linear-gradient(90deg,${col} 0,${col} 4px,transparent 4px,transparent 7px)`:"none"} }/>}
                <span style={{fontSize:8,color:T.sub,letterSpacing:1}}>{lbl}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,marginBottom:12}}>
        {[{key:"rf_score",label:"Random Forest",icon:"🌲",color:T.accent,dimColor:T.accentDim,gId:"g1",avg:rfAvg,wt:"45%"},
          {key:"xgb_score",label:"XGBoost Prediction",icon:"⚡",color:T.orange,dimColor:T.orangeDim,gId:"g2",avg:xgbAvg,wt:"55%"}
        ].map(m=>(
          <div key={m.key} style={{background:T.card,border:`1px solid ${T.border}`,borderRadius:16,padding:"18px 20px",boxShadow:T.shadow}}>
            <SectionHeader icon={m.icon} title={m.label}
              sub={m.key==="rf_score"?"150 trees, majority vote":"Gradient boosting on residuals"} T={T}/>
            <div style={{height:200}}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={fc} margin={{top:4,right:4,left:-28,bottom:0}}>
                  <defs>
                    <linearGradient id={m.gId} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor={m.color} stopOpacity={.28}/>
                      <stop offset="95%" stopColor={m.color} stopOpacity={.01}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={dark?"rgba(255,255,255,.04)":"rgba(0,0,0,.05)"}/>
                  <XAxis dataKey="time" stroke={T.sub} tick={{fill:T.sub,fontSize:8}} interval={3}/>
                  <YAxis domain={[0,100]} stroke={T.sub} tick={{fill:T.sub,fontSize:8}}/>
                  <Tooltip content={<ChartTip T={T}/>}/>
                  <ReferenceLine y={70} stroke={T.red}    strokeDasharray="4 3" strokeWidth={1.5}/>
                  <ReferenceLine y={40} stroke={T.orange} strokeDasharray="4 3" strokeWidth={1.5}/>
                  <Area type="monotone" dataKey={m.key} stroke={m.color} strokeWidth={2.5}
                    fill={`url(#${m.gId})`} dot={false}
                    activeDot={{r:5,stroke:m.color,strokeWidth:2,fill:T.card}} animationDuration={1000}/>
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div style={{marginTop:8,padding:"7px 11px",background:m.dimColor,borderRadius:7,fontSize:9,color:m.color,display:"flex",justifyContent:"space-between"}}>
              <span>Avg: <b>{m.avg}%</b></span><span>Ensemble weight: <b>{m.wt}</b></span>
            </div>
          </div>
        ))}
      </div>

      <div style={{background:T.card,border:`1px solid ${T.border}`,borderRadius:16,padding:"18px 20px",boxShadow:T.shadow,marginBottom:12}}>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:12,flexWrap:"wrap",gap:8}}>
          <SectionHeader icon="🔮" title="Combined 24-Hour Forecast" sub="45% Forest + 55% Booster ensemble blend" T={T}/>
          <div style={{display:"flex",gap:5,marginBottom:12}}>
            {["area","line"].map(m=>(
              <button key={m} onClick={()=>setChart(m)} style={{padding:"4px 12px",borderRadius:20,border:`1px solid ${chartMode===m?T.accent:T.border}`,
                background:chartMode===m?T.accentDim:"transparent",color:chartMode===m?T.accent:T.sub,
                cursor:"pointer",fontSize:9,letterSpacing:1.5,fontFamily:"inherit",transition:"all .2s"}}>{m.toUpperCase()}</button>
            ))}
          </div>
        </div>
        <div style={{height:240}}>
          <ResponsiveContainer width="100%" height="100%">
            {chartMode==="area"?(
              <AreaChart data={fc} margin={{top:4,right:4,left:-24,bottom:0}}>
                <defs>
                  {[["gMain",T.accent,.2],["gRf",T.accent,.07],["gXgb",T.orange,.07]].map(([id,c,o])=>(
                    <linearGradient key={id} id={id} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor={c} stopOpacity={o}/>
                      <stop offset="95%" stopColor={c} stopOpacity={.01}/>
                    </linearGradient>
                  ))}
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={dark?"rgba(255,255,255,.04)":"rgba(0,0,0,.05)"}/>
                <XAxis dataKey="time" stroke={T.sub} tick={{fill:T.sub,fontSize:9}}/>
                <YAxis domain={[0,100]} stroke={T.sub} tick={{fill:T.sub,fontSize:9}}/>
                <Tooltip content={<ChartTip T={T}/>}/>
                <ReferenceLine y={70} stroke={T.red}    strokeDasharray="5 3" strokeWidth={1.5}/>
                <ReferenceLine y={40} stroke={T.orange} strokeDasharray="5 3" strokeWidth={1.5}/>
                <Area type="monotone" dataKey="rf_score"    stroke={T.accent} strokeWidth={1} fill="url(#gRf)"   dot={false} strokeDasharray="4 3" opacity={.6}  animationDuration={800}/>
                <Area type="monotone" dataKey="xgb_score"   stroke={T.orange} strokeWidth={1} fill="url(#gXgb)"  dot={false} strokeDasharray="4 3" opacity={.6}  animationDuration={900}/>
                <Area type="monotone" dataKey="risk_percent" stroke={T.accent} strokeWidth={3} fill="url(#gMain)" dot={false}
                  activeDot={{r:6,stroke:T.accent,strokeWidth:2,fill:T.card}} animationDuration={1100}/>
                <Brush dataKey="time" height={16} stroke={T.border} fill={T.panel} travellerWidth={6}/>
              </AreaChart>
            ):(
              <LineChart data={fc} margin={{top:4,right:4,left:-24,bottom:0}}>
                <CartesianGrid strokeDasharray="3 3" stroke={dark?"rgba(255,255,255,.04)":"rgba(0,0,0,.05)"}/>
                <XAxis dataKey="time" stroke={T.sub} tick={{fill:T.sub,fontSize:9}}/>
                <YAxis domain={[0,100]} stroke={T.sub} tick={{fill:T.sub,fontSize:9}}/>
                <Tooltip content={<ChartTip T={T}/>}/>
                <ReferenceLine y={70} stroke={T.red}    strokeDasharray="5 3"/>
                <ReferenceLine y={40} stroke={T.orange} strokeDasharray="5 3"/>
                <Line type="monotone" dataKey="rf_score"    stroke={T.accent} strokeWidth={1.5} dot={false} strokeDasharray="4 3" animationDuration={800}/>
                <Line type="monotone" dataKey="xgb_score"   stroke={T.orange} strokeWidth={1.5} dot={false} strokeDasharray="4 3" animationDuration={900}/>
                <Line type="monotone" dataKey="risk_percent" stroke={T.accent} strokeWidth={3}
                  dot={{r:2.5,fill:T.accent,strokeWidth:0}} activeDot={{r:6,stroke:T.card,strokeWidth:2}} animationDuration={1100}/>
                <Brush dataKey="time" height={16} stroke={T.border} fill={T.panel} travellerWidth={6}/>
              </LineChart>
            )}
          </ResponsiveContainer>
        </div>
      </div>

      <div style={{background:T.card,border:`1px solid ${T.border}`,borderRadius:16,padding:"18px 20px",boxShadow:T.shadow}}>
        <SectionHeader icon="⚖️" title="Model Comparison — Time of Day"
          sub="Ensemble contribution across peak and off-peak periods" T={T}/>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,alignItems:"center"}}>
          <div style={{height:210}}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={compData} margin={{top:4,right:4,left:-28,bottom:0}} barGap={3}>
                <CartesianGrid strokeDasharray="3 3" stroke={dark?"rgba(255,255,255,.04)":"rgba(0,0,0,.05)"}/>
                <XAxis dataKey="period" stroke={T.sub} tick={{fill:T.sub,fontSize:8}}/>
                <YAxis domain={[0,100]} stroke={T.sub} tick={{fill:T.sub,fontSize:8}}/>
                <Tooltip content={<PerfTip T={T}/>}/>
                <Bar dataKey="Forest"  fill={T.accent} radius={[4,4,0,0]} maxBarSize={20} opacity={.85}/>
                <Bar dataKey="Booster" fill={T.orange} radius={[4,4,0,0]} maxBarSize={20} opacity={.85}/>
                <Bar dataKey="Final"   fill={T.green}  radius={[4,4,0,0]} maxBarSize={20} opacity={.85}/>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div style={{display:"flex",flexDirection:"column",gap:9}}>
            {[{col:T.accent,bg:T.accentDim,icon:"🌲",name:"Random Forest",wt:"45%",avg:rfAvg,desc:"Bagging ensemble, 150 trees"},
              {col:T.orange,bg:T.orangeDim,icon:"⚡",name:"XGBoost",wt:"55%",avg:xgbAvg,desc:"Gradient boosted trees"},
              {col:T.green, bg:T.greenDim, icon:"🎯",name:"Final Blend",wt:"—",avg:avgRisk,desc:"Weighted ensemble output"},
            ].map(m=>(
              <div key={m.name} style={{background:m.bg,border:`1px solid ${m.col}22`,borderRadius:10,padding:"11px 14px",borderLeft:`3px solid ${m.col}`}}>
                <div style={{display:"flex",justifyContent:"space-between",marginBottom:4}}>
                  <span style={{fontSize:10,fontWeight:700,color:m.col}}>{m.icon} {m.name}</span>
                  <span style={{fontSize:8,color:T.sub,background:T.card,padding:"1px 7px",borderRadius:9}}>{m.wt}</span>
                </div>
                <div style={{fontSize:9,color:T.sub}}>{m.desc}</div>
                <div style={{fontSize:17,fontWeight:900,color:m.col,marginTop:4}}>{m.avg}%<span style={{fontSize:9,color:T.sub,fontWeight:400}}> avg</span></div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );

  const renderPerformance = () => {
    if(!perf) return(
      <div style={{textAlign:"center",padding:"64px 0",background:T.card,border:`1px solid ${T.border}`,borderRadius:16}}>
        <div style={{fontSize:42,marginBottom:14}}>📊</div>
        <div style={{fontSize:12,color:T.text,fontWeight:700,marginBottom:6}}>No performance data yet</div>
        <div style={{fontSize:9,letterSpacing:2,color:T.sub}}>Click a location to load model metrics</div>
      </div>
    );

    const PERF_TABS = [
      {id:"overview",  label:"Overview"},
      {id:"confusion", label:"Confusion Matrix"},
      {id:"features",  label:"Feature Importance"},
      {id:"learning",  label:"Learning Curves"},
      {id:"radar",     label:"Radar"},
      {id:"regressor", label:"XGB Regressor"},   
    ];

    return(
      <div style={{animation:"fadeUp .5s ease both"}}>
        <div style={{display:"grid",gridTemplateColumns:"repeat(8,1fr)",gap:8,marginBottom:14}}>
          {[
            {label:"RF Accuracy",   val:(perf.rf.acc*100).toFixed(1)+"%",  color:T.accent},
            {label:"RF Precision",  val:(perf.rf.prec*100).toFixed(1)+"%", color:T.accent},
            {label:"RF Recall",     val:(perf.rf.rec*100).toFixed(1)+"%",  color:T.accent},
            {label:"RF F1",         val:(perf.rf.f1*100).toFixed(1)+"%",   color:T.accent},
            {label:"XGB Accuracy",  val:(perf.xgb.acc*100).toFixed(1)+"%", color:T.orange},
            {label:"XGB Precision", val:(perf.xgb.prec*100).toFixed(1)+"%",color:T.orange},
            {label:"XGB Recall",    val:(perf.xgb.rec*100).toFixed(1)+"%", color:T.orange},
            {label:"XGB F1",        val:(perf.xgb.f1*100).toFixed(1)+"%",  color:T.orange},
          ].map(k=>(
            <div key={k.label} style={{background:T.card,border:`1px solid ${T.border}`,borderRadius:10,padding:"11px 12px",boxShadow:T.shadow,textAlign:"center"}}>
              <div style={{fontSize:16,fontWeight:900,color:k.color}}>{k.val}</div>
              <div style={{fontSize:7.5,color:T.sub,letterSpacing:1,marginTop:3,textTransform:"uppercase"}}>{k.label}</div>
            </div>
          ))}
        </div>

        <div style={{display:"flex",gap:4,marginBottom:14,flexWrap:"wrap"}}>
          {PERF_TABS.map(pt=>(
            <button key={pt.id} onClick={()=>setPerfTab(pt.id)} style={{
              padding:"6px 16px",borderRadius:20,cursor:"pointer",fontFamily:"inherit",
              fontSize:9,letterSpacing:1.5,transition:"all .2s",
              border:`1px solid ${perfTab===pt.id?(pt.id==="regressor"?T.teal:T.accent):T.border}`,
              background:perfTab===pt.id?(pt.id==="regressor"?T.tealDim:T.accentDim):"transparent",
              color:perfTab===pt.id?(pt.id==="regressor"?T.teal:T.accent):T.sub,
            }}>{pt.label.toUpperCase()}{pt.id==="regressor"&&<span style={{marginLeft:5,fontSize:7,color:T.teal,background:`${T.teal}18`,padding:"1px 5px",borderRadius:8}}>REGRESSION</span>}</button>
          ))}
        </div>

        {perfTab==="overview"&&(
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12}}>
            <div style={{background:T.card,border:`1px solid ${T.border}`,borderRadius:16,padding:"20px 22px",boxShadow:T.shadow}}>
              <SectionHeader icon="📐" title="Head-to-Head Metrics" sub="Model comparison on held-out test set" T={T}/>
              <div style={{display:"flex",justifyContent:"flex-end",gap:16,marginBottom:16}}>
                <div style={{display:"flex",alignItems:"center",gap:5}}><div style={{width:10,height:3,background:T.accent,borderRadius:2}}/><span style={{fontSize:8,color:T.sub,letterSpacing:1}}>FOREST</span></div>
                <div style={{display:"flex",alignItems:"center",gap:5}}><div style={{width:10,height:3,background:T.orange,borderRadius:2}}/><span style={{fontSize:8,color:T.sub,letterSpacing:1}}>BOOSTER</span></div>
              </div>
              <ProgMetric label="Accuracy"  rfVal={perf.rf.acc}  xgbVal={perf.xgb.acc}  T={T}/>
              <ProgMetric label="Precision" rfVal={perf.rf.prec} xgbVal={perf.xgb.prec} T={T}/>
              <ProgMetric label="Recall"    rfVal={perf.rf.rec}  xgbVal={perf.xgb.rec}  T={T}/>
              <ProgMetric label="F1 Score"  rfVal={perf.rf.f1}   xgbVal={perf.xgb.f1}   T={T}/>
              <ProgMetric label="ROC-AUC"   rfVal={perf.rf.auc}  xgbVal={perf.xgb.auc}  T={T}/>
            </div>
            <div style={{display:"flex",flexDirection:"column",gap:10}}>
              {[{m:perf.rf,icon:"🌲",name:"Random Forest",col:T.accent,dim:T.accentDim,params:"150 trees · max_depth=10 · balanced"},
                {m:perf.xgb,icon:"⚡",name:"XGBoost Classifier",col:T.orange,dim:T.orangeDim,params:"300 rounds · lr=0.05 · depth=6"},
              ].map(({m,icon,name,col,dim,params})=>(
                <div key={name} style={{background:dim,border:`1px solid ${col}22`,borderRadius:14,padding:"16px 18px",borderLeft:`3px solid ${col}`,flex:1}}>
                  <div style={{fontSize:12,fontWeight:700,color:col,marginBottom:12}}>{icon} {name}</div>
                  <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:6,marginBottom:12}}>
                    {[["Accuracy",m.acc],["F1",m.f1],["Precision",m.prec],["AUC",m.auc]].map(([lbl,v])=>(
                      <div key={lbl} style={{textAlign:"center",background:T.card,borderRadius:8,padding:"8px 4px",border:`1px solid ${col}18`}}>
                        <div style={{fontSize:14,fontWeight:900,color:col}}>{(v*100).toFixed(1)}<span style={{fontSize:7}}>%</span></div>
                        <div style={{fontSize:7,color:T.sub,letterSpacing:1}}>{lbl}</div>
                      </div>
                    ))}
                  </div>
                  <div style={{fontSize:9,color:T.sub,fontFamily:"monospace",background:T.faint,padding:"6px 10px",borderRadius:6}}>{params}</div>
                </div>
              ))}
              <div style={{background:T.greenDim,border:`1px solid ${T.green}25`,borderRadius:10,padding:"10px 14px",borderLeft:`3px solid ${T.green}`}}>
                <div style={{fontSize:10,color:T.green,fontWeight:700,marginBottom:3}}>
                  🏆 {perf.xgb.f1>perf.rf.f1?"XGBoost":"Random Forest"} wins on F1
                </div>
                <div style={{fontSize:9,color:T.sub}}>
                  Δ F1 = {Math.abs((perf.xgb.f1-perf.rf.f1)*100).toFixed(2)}% · Ensemble still benefits from both
                </div>
              </div>
            </div>
          </div>
        )}

        {perfTab==="confusion"&&(
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12}}>
            {[{m:perf.rf,icon:"🌲",name:"Random Forest",col:T.accent},{m:perf.xgb,icon:"⚡",name:"XGBoost",col:T.orange}].map(({m,icon,name,col})=>(
              <div key={name} style={{background:T.card,border:`1px solid ${T.border}`,borderRadius:16,padding:"20px 22px",boxShadow:T.shadow}}>
                <SectionHeader icon={icon} title={`${name} — Confusion Matrix`} sub="Predicted vs actual labels on test set" T={T}/>
                <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:16,alignItems:"start"}}>
                  <ConfusionMatrix matrix={m.confMatrix} title="Test set results" color={col} T={T}/>
                  <div style={{display:"flex",flexDirection:"column",gap:8}}>
                    <div style={{background:dark?T.accentDim:T.faint,borderRadius:10,padding:"12px 14px",border:`1px solid ${col}22`}}>
                      {[["True Negatives",m.confMatrix[0][0],"Free flow correctly identified",true],
                        ["False Positives",m.confMatrix[0][1],"Free flow called congested",false],
                        ["False Negatives",m.confMatrix[1][0],"Congestion missed",false],
                        ["True Positives",m.confMatrix[1][1],"Congestion detected",true],
                      ].map(([lbl,val,desc,good])=>(
                        <div key={lbl} style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:6,paddingBottom:6,borderBottom:`1px solid ${T.border}`}}>
                          <div>
                            <div style={{fontSize:9,fontWeight:700,color:good?col:T.red}}>{lbl}</div>
                            <div style={{fontSize:7.5,color:T.sub}}>{desc}</div>
                          </div>
                          <div style={{fontSize:14,fontWeight:900,color:good?col:T.red}}>{val.toLocaleString()}</div>
                        </div>
                      ))}
                    </div>
                    <div style={{background:T.faint,borderRadius:8,padding:"10px 12px"}}>
                      {[["Accuracy",(m.acc*100).toFixed(1)+"%"],["F1 Score",(m.f1*100).toFixed(1)+"%"],["ROC-AUC",(m.auc*100).toFixed(1)+"%"]].map(([k,v])=>(
                        <div key={k} style={{display:"flex",justifyContent:"space-between",fontSize:10,marginBottom:4}}>
                          <span style={{color:T.sub}}>{k}</span><b style={{color:col}}>{v}</b>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {perfTab==="features"&&(
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12}}>
            {[{key:"rf",icon:"🌲",name:"Random Forest",col:T.accent},{key:"xgb",icon:"⚡",name:"XGBoost",col:T.orange}].map(model=>(
              <div key={model.key} style={{background:T.card,border:`1px solid ${T.border}`,borderRadius:16,padding:"20px 22px",boxShadow:T.shadow}}>
                <SectionHeader icon={model.icon} title={`${model.name} — Feature Importance`} sub="Real-time internal weights from the model" T={T}/>
                <div style={{height:200}}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={[...perf.importances].sort((a,b)=>b[model.key]-a[model.key])} layout="vertical" margin={{top:4,right:12,left:8,bottom:0}}>
                      <CartesianGrid strokeDasharray="3 3" stroke={dark?"rgba(255,255,255,.04)":"rgba(0,0,0,.05)"} horizontal={false}/>
                      <XAxis type="number" domain={[0,40]} stroke={T.sub} tick={{fill:T.sub,fontSize:8}}/>
                      <YAxis type="category" dataKey="feature" stroke={T.sub} tick={{fill:T.sub,fontSize:8}} width={90}/>
                      <Tooltip content={<PerfTip T={T}/>}/>
                      <Bar dataKey={model.key} fill={model.col} radius={[0,4,4,0]} opacity={.85}
                        label={{position:"right",fill:model.col,fontSize:8,formatter:v=>`${v}%`}}/>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div style={{marginTop:10}}>
                  {[...perf.importances].sort((a,b)=>b[model.key]-a[model.key]).map((f,i)=>(
                    <div key={f.feature} style={{display:"flex",alignItems:"center",gap:10,marginBottom:6}}>
                      <div style={{width:16,height:16,borderRadius:4,background:dark?T.accentDim:T.faint,border:`1px solid ${model.col}30`,
                        display:"flex",alignItems:"center",justifyContent:"center",fontSize:7,color:model.col,fontWeight:700}}>{i+1}</div>
                      <div style={{flex:1}}>
                        <div style={{display:"flex",justifyContent:"space-between",marginBottom:2}}>
                          <span style={{fontSize:9,color:T.text}}>{f.feature}</span>
                          <span style={{fontSize:9,fontWeight:700,color:model.col}}>{f[model.key]}%</span>
                        </div>
                        <div style={{height:4,background:T.faint,borderRadius:2,overflow:"hidden"}}>
                          <div style={{height:"100%",width:`${f[model.key]/40*100}%`,background:model.col,borderRadius:2}}/>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {perfTab==="learning"&&(
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12}}>
            {[{trainKey:"rf_train",valKey:"rf_val",icon:"🌲",name:"Random Forest",col:T.accent},
              {trainKey:"xgb_train",valKey:"xgb_val",icon:"⚡",name:"XGBoost",col:T.orange},
            ].map(m=>(
              <div key={m.name} style={{background:T.card,border:`1px solid ${T.border}`,borderRadius:16,padding:"20px 22px",boxShadow:T.shadow}}>
                <SectionHeader icon={m.icon} title={`${m.name} — Learning Curve`} sub="Train vs validation F1 over training rounds" T={T}/>
                <div style={{height:230}}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={perf.trainingHistory} margin={{top:4,right:4,left:-28,bottom:0}}>
                      <CartesianGrid strokeDasharray="3 3" stroke={dark?"rgba(255,255,255,.04)":"rgba(0,0,0,.05)"}/>
                      <XAxis dataKey="epoch" stroke={T.sub} tick={{fill:T.sub,fontSize:8}}/>
                      <YAxis domain={[0.5,1]} stroke={T.sub} tick={{fill:T.sub,fontSize:8}} tickFormatter={v=>`${(v*100).toFixed(0)}%`}/>
                      <Tooltip content={<PerfTip T={T}/>}/>
                      <Line type="monotone" dataKey={m.trainKey} name="Training"   stroke={m.col} strokeWidth={2.5} dot={false} animationDuration={1000}/>
                      <Line type="monotone" dataKey={m.valKey}   name="Validation" stroke={m.col} strokeWidth={2}   dot={false} strokeDasharray="5 4" opacity={.65} animationDuration={1100}/>
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                <div style={{marginTop:10,padding:"8px 12px",background:T.faint,borderRadius:8,fontSize:9,color:T.sub}}>
                  {(()=>{
                    const last=perf.trainingHistory[perf.trainingHistory.length-1];
                    const gap=((last[m.trainKey]-last[m.valKey])*100).toFixed(1);
                    return `Final gap: ${gap}% — ${parseFloat(gap)<3?"Good generalization":parseFloat(gap)<8?"Slight overfitting detected":"Overfitting — consider regularization"}`;
                  })()}
                </div>
              </div>
            ))}
          </div>
        )}

        {perfTab==="radar"&&(
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12}}>
            <div style={{background:T.card,border:`1px solid ${T.border}`,borderRadius:16,padding:"20px 22px",boxShadow:T.shadow}}>
              <SectionHeader icon="🕸️" title="Radar — Model Capabilities" sub="Normalized multi-dimensional comparison" T={T}/>
              <div style={{height:280}}>
                <ResponsiveContainer width="100%" height="100%">
                  <RadarChart data={perf.radarMetrics}>
                    <PolarGrid stroke={T.border}/>
                    <PolarAngleAxis dataKey="metric" tick={{fill:T.sub,fontSize:9}}/>
                    <PolarRadiusAxis domain={[0,100]} tick={{fill:T.sub,fontSize:7}} tickCount={4}/>
                    <Radar name="Random Forest" dataKey="rf"  stroke={T.accent} fill={T.accent} fillOpacity={.18} strokeWidth={2}/>
                    <Radar name="XGBoost"       dataKey="xgb" stroke={T.orange} fill={T.orange} fillOpacity={.15} strokeWidth={2}/>
                    <Legend wrapperStyle={{fontSize:10,color:T.sub}}/>
                    <Tooltip contentStyle={{background:T.panel,border:`1px solid ${T.border}`,borderRadius:8,fontFamily:"inherit",fontSize:10}}/>
                  </RadarChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div style={{display:"flex",flexDirection:"column",gap:10}}>
              <div style={{background:T.card,border:`1px solid ${T.border}`,borderRadius:16,padding:"20px 22px",boxShadow:T.shadow,flex:1}}>
                <SectionHeader icon="📊" title="Dimension Breakdown" sub="Score per capability metric" T={T}/>
                {perf.radarMetrics.map(m=>(
                  <div key={m.metric} style={{marginBottom:12}}>
                    <div style={{display:"flex",justifyContent:"space-between",marginBottom:5}}>
                      <span style={{fontSize:10,color:T.text,fontWeight:600}}>{m.metric}</span>
                      <div style={{display:"flex",gap:12}}>
                        <span style={{fontSize:10,color:T.accent,fontWeight:700}}>{m.rf}%</span>
                        <span style={{fontSize:10,color:T.orange,fontWeight:700}}>{m.xgb}%</span>
                      </div>
                    </div>
                    <div style={{display:"flex",flexDirection:"column",gap:3}}>
                      {[{key:"rf",color:T.accent,label:"Forest",val:m.rf},{key:"xgb",color:T.orange,label:"Boost",val:m.xgb}].map(r=>(
                        <div key={r.key} style={{display:"flex",alignItems:"center",gap:7}}>
                          <span style={{width:40,fontSize:7.5,color:T.sub,letterSpacing:.5}}>{r.label}</span>
                          <div style={{flex:1,height:5,background:T.faint,borderRadius:3,overflow:"hidden"}}>
                            <div style={{height:"100%",width:`${r.val}%`,background:r.color,borderRadius:3,transition:"width 1.2s ease"} }/>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <div style={{background:T.card,border:`1px solid ${T.border}`,borderRadius:14,padding:"16px 18px",boxShadow:T.shadow}}>
                <div style={{fontSize:11,fontWeight:700,color:T.text,marginBottom:10}}>🧠 Ensemble Rationale</div>
                {[{title:"Why Random Forest?",text:"Stable, robust to noise, excellent recall on congestion events.",col:T.accent},
                  {title:"Why XGBoost?",text:"Higher precision, better at capturing non-linear rush-hour spikes.",col:T.orange},
                  {title:"Why blend both?",text:"Combining reduces variance and bias — lower error than either alone.",col:T.green},
                ].map(s=>(
                  <div key={s.title} style={{marginBottom:8,paddingBottom:8,borderBottom:`1px solid ${T.border}`}}>
                    <div style={{fontSize:9,fontWeight:700,color:s.col,marginBottom:2}}>{s.title}</div>
                    <div style={{fontSize:9,color:T.sub,lineHeight:1.6}}>{s.text}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {perfTab==="regressor"&&(
          <div style={{animation:"fadeUp .4s ease both"}}>
            <div style={{background:`linear-gradient(135deg,${T.tealDim},${T.card})`,border:`1px solid ${T.teal}25`,
              borderLeft:`4px solid ${T.teal}`,borderRadius:16,padding:"18px 24px",marginBottom:16,boxShadow:T.shadow}}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",flexWrap:"wrap",gap:12}}>
                <div>
                  <div style={{fontSize:9,color:T.teal,letterSpacing:2.5,marginBottom:5,textTransform:"uppercase",fontWeight:700}}>
                    XGBoost Regressor — Model Performance
                  </div>
                  <div style={{fontSize:18,fontWeight:900,color:T.text,marginBottom:4}}>
                    🚗 Speed Drop Prediction
                  </div>
                  <div style={{fontSize:10,color:T.sub}}>
                    Predicts how many km/h speed will drop from free-flow baseline · Continuous target variable
                  </div>
                </div>
                <div style={{display:"flex",gap:10,flexWrap:"wrap"}}>
                  {[{lbl:"Task Type",val:"Regression",col:T.teal},{lbl:"Target",val:"Speed Drop (km/h)",col:T.purple},{lbl:"Algorithm",val:"XGBoost",col:T.orange}].map(b=>(
                    <div key={b.lbl} style={{background:`${b.col}12`,border:`1px solid ${b.col}30`,borderRadius:8,padding:"8px 14px",textAlign:"center"}}>
                      <div style={{fontSize:12,fontWeight:900,color:b.col}}>{b.val}</div>
                      <div style={{fontSize:8,color:T.sub,letterSpacing:1,marginTop:2}}>{b.lbl}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div style={{display:"grid",gridTemplateColumns:"repeat(5,1fr)",gap:10,marginBottom:16}}>
              <RegMetricCard label="MAE" value={(perf.reg.mae).toFixed(2)} unit=" km/h"
                sub="Mean Abs Error" color={T.teal} icon="📏" T={T}/>
              <RegMetricCard label="RMSE" value={(perf.reg.rmse).toFixed(2)} unit=" km/h"
                sub="Root Mean Sq Error" color={T.accent} icon="📐" T={T}/>
              <RegMetricCard label="R² Score" value={(perf.reg.r2*100).toFixed(1)} unit="%"
                sub="Variance explained" color={T.green} icon="📈" T={T}/>
              <RegMetricCard label="MAPE" value={(perf.reg.mape*100).toFixed(1)} unit="%"
                sub="Mean Abs % Error" color={T.orange} icon="🎯" T={T}/>
              <RegMetricCard label="Explained Var" value={(perf.reg.evs*100).toFixed(1)} unit="%"
                sub="Explained variance score" color={T.purple} icon="🧮" T={T}/>
            </div>

            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,marginBottom:12}}>

              <div style={{background:T.card,border:`1px solid ${T.border}`,borderRadius:16,padding:"20px 22px",boxShadow:T.shadow}}>
                <SectionHeader icon="📉" title="Regressor — Learning Curve"
                  sub="Train vs validation R² over boosting rounds" badge="XGB REG" badgeColor={T.teal} T={T}/>
                <div style={{height:230}}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={perf.trainingHistory} margin={{top:4,right:4,left:-28,bottom:0}}>
                      <CartesianGrid strokeDasharray="3 3" stroke={dark?"rgba(255,255,255,.04)":"rgba(0,0,0,.05)"}/>
                      <XAxis dataKey="epoch" stroke={T.sub} tick={{fill:T.sub,fontSize:8}}/>
                      <YAxis domain={[0.4,1]} stroke={T.sub} tick={{fill:T.sub,fontSize:8}} tickFormatter={v=>`${(v*100).toFixed(0)}%`}/>
                      <Tooltip content={<PerfTip T={T}/>}/>
                      <Line type="monotone" dataKey="reg_train" name="Train R²"      stroke={T.teal}   strokeWidth={2.5} dot={false} animationDuration={1000}/>
                      <Line type="monotone" dataKey="reg_val"   name="Validation R²" stroke={T.teal}   strokeWidth={2}   dot={false} strokeDasharray="5 4" opacity={.65} animationDuration={1100}/>
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                <div style={{marginTop:10,padding:"8px 12px",background:T.faint,borderRadius:8,fontSize:9,color:T.sub}}>
                  {(()=>{
                    const last=perf.trainingHistory[perf.trainingHistory.length-1];
                    const gap=((last.reg_train-last.reg_val)*100).toFixed(1);
                    return `Final gap: ${gap}% — ${parseFloat(gap)<3?"Good generalization":parseFloat(gap)<8?"Slight overfitting detected":"Overfitting — consider regularization"}`;
                  })()}
                </div>
              </div>

              <div style={{background:T.card,border:`1px solid ${T.border}`,borderRadius:16,padding:"20px 22px",boxShadow:T.shadow}}>
                <SectionHeader icon="🔢" title="Regressor — Feature Importance"
                  sub="Real-time internal weights from the model" badge="XGB REG" badgeColor={T.teal} T={T}/>
                <div style={{height:200}}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={[...perf.importances].sort((a,b)=>b.reg-a.reg)} layout="vertical" margin={{top:4,right:12,left:8,bottom:0}}>
                      <CartesianGrid strokeDasharray="3 3" stroke={dark?"rgba(255,255,255,.04)":"rgba(0,0,0,.05)"} horizontal={false}/>
                      <XAxis type="number" domain={[0,40]} stroke={T.sub} tick={{fill:T.sub,fontSize:8}}/>
                      <YAxis type="category" dataKey="feature" stroke={T.sub} tick={{fill:T.sub,fontSize:8}} width={90}/>
                      <Tooltip content={<PerfTip T={T}/>}/>
                      <Bar dataKey="reg" fill={T.teal} radius={[0,4,4,0]} opacity={.85}
                        label={{position:"right",fill:T.teal,fontSize:8,formatter:v=>`${v}%`}} name="Importance"/>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div style={{marginTop:10}}>
                  {[...perf.importances].sort((a,b)=>b.reg-a.reg).map((f,i)=>(
                    <div key={f.feature} style={{display:"flex",alignItems:"center",gap:8,marginBottom:5}}>
                      <div style={{width:16,height:16,borderRadius:4,background:T.tealDim,border:`1px solid ${T.teal}30`,
                        display:"flex",alignItems:"center",justifyContent:"center",fontSize:7,color:T.teal,fontWeight:700}}>{i+1}</div>
                      <div style={{flex:1}}>
                        <div style={{display:"flex",justifyContent:"space-between",marginBottom:2}}>
                          <span style={{fontSize:9,color:T.text}}>{f.feature}</span>
                          <span style={{fontSize:9,fontWeight:700,color:T.teal}}>{f.reg}%</span>
                        </div>
                        <div style={{height:4,background:T.faint,borderRadius:2,overflow:"hidden"}}>
                          <div style={{height:"100%",width:`${f.reg/40*100}%`,background:T.teal,borderRadius:2} }/>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div style={{background:T.card,border:`1px solid ${T.teal}22`,borderRadius:16,padding:"20px 22px",boxShadow:T.shadow,marginBottom:12}}>
              <SectionHeader icon="🎯" title="Actual vs Predicted Speed Drop"
                sub="Each point = one test sample · Ideal model = points on diagonal" badge="RESIDUAL ANALYSIS" badgeColor={T.teal} T={T}/>
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:14,alignItems:"start"}}>
                <div style={{height:240}}>
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={perf.residuals.slice(0,24).map((d,i)=>({...d,idx:i}))} margin={{top:4,right:4,left:-20,bottom:0}}>
                      <defs>
                        <linearGradient id="gActual" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%"  stopColor={T.teal}   stopOpacity={.25}/>
                          <stop offset="95%" stopColor={T.teal}   stopOpacity={.01}/>
                        </linearGradient>
                        <linearGradient id="gPred" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%"  stopColor={T.purple} stopOpacity={.2}/>
                          <stop offset="95%" stopColor={T.purple} stopOpacity={.01}/>
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke={dark?"rgba(255,255,255,.04)":"rgba(0,0,0,.05)"}/>
                      <XAxis dataKey="idx" stroke={T.sub} tick={{fill:T.sub,fontSize:8}} label={{value:"Sample",fill:T.sub,fontSize:8,position:"insideBottom",offset:-2}}/>
                      <YAxis stroke={T.sub} tick={{fill:T.sub,fontSize:8}} label={{value:"km/h",fill:T.sub,fontSize:8,angle:-90,position:"insideLeft"}}/>
                      <Tooltip contentStyle={{background:T.panel,border:`1px solid ${T.border}`,borderRadius:8,fontFamily:"inherit",fontSize:10}}/>
                      <Area type="monotone" dataKey="actual"    stroke={T.teal}   strokeWidth={2}   fill="url(#gActual)" dot={false} name="Actual Drop"/>
                      <Area type="monotone" dataKey="predicted" stroke={T.purple} strokeWidth={2}   fill="url(#gPred)"   dot={false} strokeDasharray="4 3" name="Predicted Drop"/>
                    </AreaChart>
                  </ResponsiveContainer>
                </div>

                <div style={{height:240}}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={perf.residuals.slice(0,24).map((d,i)=>({...d,idx:i}))} margin={{top:4,right:4,left:-20,bottom:0}}>
                      <CartesianGrid strokeDasharray="3 3" stroke={dark?"rgba(255,255,255,.04)":"rgba(0,0,0,.05)"}/>
                      <XAxis dataKey="idx" stroke={T.sub} tick={{fill:T.sub,fontSize:8}} label={{value:"Sample",fill:T.sub,fontSize:8,position:"insideBottom",offset:-2}}/>
                      <YAxis stroke={T.sub} tick={{fill:T.sub,fontSize:8}} label={{value:"Residual",fill:T.sub,fontSize:8,angle:-90,position:"insideLeft"}}/>
                      <Tooltip contentStyle={{background:T.panel,border:`1px solid ${T.border}`,borderRadius:8,fontFamily:"inherit",fontSize:10}}/>
                      <ReferenceLine y={0} stroke={T.sub} strokeWidth={1.5}/>
                      <Bar dataKey="residual" name="Residual (Pred - Actual)"
                        fill={T.orange} opacity={.75} radius={[2,2,0,0]}
                        label={{position:"top",fill:T.sub,fontSize:0}}/>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
              <div style={{display:"flex",gap:20,marginTop:10,flexWrap:"wrap"}}>
                {[{col:T.teal,lbl:"Actual Speed Drop"},{col:T.purple,lbl:"Predicted Drop",dash:true},{col:T.orange,lbl:"Residual (error)",dot:true}].map(({col,lbl,dash,dot})=>(
                  <div key={lbl} style={{display:"flex",alignItems:"center",gap:6}}>
                    {dot?<div style={{width:8,height:8,borderRadius:2,background:col}}/>:
                      <div style={{width:20,height:2.5,background:col,backgroundImage:dash?`repeating-linear-gradient(90deg,${col} 0,${col} 4px,transparent 4px,transparent 7px)`:"none"} }/>}
                    <span style={{fontSize:8,color:T.sub,letterSpacing:1}}>{lbl}</span>
                  </div>
                ))}
              </div>
            </div>

            <div style={{background:T.tealDim,border:`1px solid ${T.teal}22`,borderRadius:14,padding:"16px 20px",borderLeft:`3px solid ${T.teal}`}}>
              <div style={{fontSize:11,fontWeight:700,color:T.teal,marginBottom:12}}>⚙️ XGBoost Regressor — Configuration</div>
              <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(200px,1fr))",gap:10}}>
                {[
                  {k:"Objective",       v:"reg:squarederror"},
                  {k:"N Estimators",    v:"300 rounds"},
                  {k:"Learning Rate",   v:"0.05"},
                  {k:"Max Depth",       v:"6"},
                  {k:"Subsample",       v:"0.8"},
                  {k:"Target Variable", v:"speed_drop_kmh"},
                  {k:"Features",        v:"8 (same as classifiers)"},
                  {k:"Loss Function",   v:"Squared Error (MSE)"},
                ].map(({k,v})=>(
                  <div key={k} style={{background:T.card,borderRadius:8,padding:"8px 12px",border:`1px solid ${T.teal}18`}}>
                    <div style={{fontSize:8,color:T.sub,letterSpacing:1,marginBottom:3,textTransform:"uppercase"}}>{k}</div>
                    <div style={{fontSize:10,fontWeight:700,color:T.teal,fontFamily:"monospace"}}>{v}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

      </div>
    );
  };

  return(
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600;700&display=swap');
        *,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
        html,body,#root{width:100%;min-height:100vh;background:${T.bg};}
        body{transition:background .3s;}
        @keyframes spin   {to{transform:rotate(360deg);}}
        @keyframes fadeUp {from{opacity:0;transform:translateY(18px);}to{opacity:1;transform:translateY(0);}}
        @keyframes fadeIn {from{opacity:0;}to{opacity:1;}}
        @keyframes pulse  {0%,100%{opacity:.45;}50%{opacity:1;}}
        .leaflet-container{width:100%!important;height:100%!important;}
        .leaflet-control-attribution{font-size:9px!important;opacity:.3;}
        ::-webkit-scrollbar{width:4px;}
        ::-webkit-scrollbar-thumb{background:${T.faint};border-radius:4px;}
        input::placeholder{color:${T.sub};}
        .chip:hover{border-color:${T.accent}!important;color:${T.accent}!important;background:${T.accentDim}!important;}
        .drop-row:hover{background:${T.accentDim}!important;color:${T.accent}!important;}
      `}</style>

      <div style={{minHeight:"100vh",width:"100%",background:T.bg,color:T.text,
        fontFamily:"'IBM Plex Mono',monospace",transition:"background .3s,color .25s",paddingBottom:60}}>
        <div style={{maxWidth:1340,margin:"0 auto",padding:"26px 22px",
          opacity:animIn?1:0,transform:animIn?"none":"translateY(20px)",transition:"opacity .65s ease,transform .65s ease"}}>

          <div style={{textAlign:"center",marginBottom:28,position:"relative"}}>
            <button onClick={()=>setDark(d=>!d)} style={{position:"absolute",right:0,top:0,
              background:T.card,border:`1px solid ${T.border}`,borderRadius:40,padding:"7px 16px",
              color:T.text,cursor:"pointer",fontSize:11,fontFamily:"inherit",boxShadow:T.shadow,transition:"all .2s"}}>
              {dark?"☀️ Light":"🌙 Dark"}
            </button>
            <div style={{display:"inline-block",padding:"3px 16px",border:`1px solid ${T.accent}45`,borderRadius:20,fontSize:9,color:T.accent,letterSpacing:3,marginBottom:12}}>
              REAL-TIME TRAFFIC INTELLIGENCE
            </div>
            <h1 style={{fontSize:"clamp(1.7rem,4vw,2.6rem)",fontWeight:700,letterSpacing:-1.5,color:T.text,marginBottom:7,lineHeight:1.1}}>
              US TRAFFIC FORECAST
            </h1>
            <p style={{color:T.sub,fontSize:10,letterSpacing:2.5}}>
              RANDOM FOREST · XGBOOST CLASSIFIER · XGBOOST REGRESSOR · LIVE WEATHER · 24H
            </p>
          </div>

          <div style={{position:"relative",marginBottom:12}}>
            <span style={{position:"absolute",left:15,top:"50%",transform:"translateY(-50%)",fontSize:14,color:T.sub,pointerEvents:"none"}}>🔍</span>
            <input value={searchQ}
              onChange={e=>{setSearch(e.target.value);setDrop(true);}}
              onFocus={e=>{e.target.style.borderColor=T.accent;setDrop(true);}}
              onBlur={e=>{e.target.style.borderColor=T.border;setTimeout(()=>setDrop(false),180);}}
              placeholder="Search corridors, interstates, cities..."
              style={{width:"100%",padding:"12px 14px 12px 44px",background:T.card,border:`1px solid ${T.border}`,
                borderRadius:12,color:T.text,fontSize:12,fontFamily:"inherit",outline:"none",boxShadow:T.shadow,transition:"border .2s"}}
            />
            {drop&&filtered.length>0&&(
              <div style={{position:"absolute",top:"calc(100% + 5px)",left:0,right:0,zIndex:9000,
                background:T.card,border:`1px solid ${T.border}`,borderRadius:12,overflow:"hidden",
                boxShadow:T.shadowHov,animation:"fadeUp .15s ease"}}>
                {filtered.map((c,i)=>(
                  <div key={i} className="drop-row"
                    onMouseDown={()=>{pickLocation(c.lat,c.lng);setSearch(c.name);setDrop(false);}}
                    style={{padding:"10px 16px",cursor:"pointer",fontSize:11,display:"flex",
                      justifyContent:"space-between",alignItems:"center",
                      borderBottom:`1px solid ${T.border}`,transition:"background .1s",color:T.text}}>
                    <span>{c.name}</span>
                    <span style={{fontWeight:700,color:T.accent,fontSize:10}}>{c.state}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div style={{display:"flex",flexWrap:"wrap",gap:7,marginBottom:18}}>
            {CORRIDORS.map((c,i)=>(
              <button key={i} className="chip" onClick={()=>pickLocation(c.lat,c.lng)}
                style={{padding:"5px 12px",borderRadius:20,border:`1px solid ${T.border}`,background:"transparent",
                  color:T.sub,cursor:"pointer",fontSize:10,fontFamily:"inherit",transition:"all .18s"}}>
                {c.state} · {c.name.split("—")[0].trim()}
              </button>
            ))}
          </div>

          <div style={{width:"100%",height:"50vh",minHeight:300,borderRadius:16,overflow:"hidden",
            border:`1px solid ${T.border}`,boxShadow:T.shadow,marginBottom:20,position:"relative"}}>
            <MapContainer center={USA_CENTER} zoom={4} minZoom={4} maxZoom={16}
              maxBounds={USA_BOUNDS} maxBoundsViscosity={1} style={{width:"100%",height:"100%"}}>
              <TileLayer url={dark?TILE_DARK:TILE_LIGHT} attribution={ATTR}/>
              <MaxBounds/><FlyTo target={flyTo}/><MapClicker onPick={mapClick}/>
              <Rectangle bounds={USA_BOUNDS} pathOptions={{color:"#fc8181",weight:1.5,fill:false,dashArray:"6 5",opacity:.5}}/>
              {pin&&<Marker position={pin}><Popup>
                <div style={{fontFamily:"monospace",fontSize:11}}><b>📍 Analysis Point</b><br/>{pin.lat.toFixed(4)}°N · {Math.abs(pin.lng).toFixed(4)}°W</div>
              </Popup></Marker>}
            </MapContainer>
            <div style={{position:"absolute",bottom:10,left:10,zIndex:1000,background:dark?"rgba(5,8,16,.88)":"rgba(255,255,255,.92)",
              backdropFilter:"blur(8px)",border:`1px solid ${T.border}`,borderRadius:7,padding:"4px 10px",fontSize:9,color:T.sub,letterSpacing:1}}>
              ⚠ RESTRICTED TO USA
            </div>
            {pin&&<div style={{position:"absolute",bottom:10,right:10,zIndex:1000,background:dark?"rgba(5,8,16,.88)":"rgba(255,255,255,.92)",
              backdropFilter:"blur(8px)",border:`1px solid ${T.accent}45`,borderRadius:7,padding:"4px 10px",fontSize:9,color:T.accent,fontWeight:700}}>
              {pin.lat.toFixed(3)}°N · {Math.abs(pin.lng).toFixed(3)}°W
            </div>}
            {loading&&(
              <div style={{position:"absolute",inset:0,zIndex:2000,background:dark?"rgba(5,8,16,.8)":"rgba(238,242,247,.8)",
                backdropFilter:"blur(6px)",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",gap:12}}>
                <div style={{width:42,height:42,borderRadius:"50%",border:`3px solid ${T.border}`,
                  borderTop:`3px solid ${T.accent}`,animation:"spin .72s linear infinite"} }/>
                <div style={{color:T.accent,fontSize:11,letterSpacing:2,animation:"pulse 1.4s ease infinite"}}>RUNNING ALL 3 MODELS...</div>
                <div style={{color:T.sub,fontSize:9,letterSpacing:1}}>RF CLASSIFIER · XGB CLASSIFIER · XGB REGRESSOR · WEATHER</div>
              </div>
            )}
          </div>

          {data&&!loading&&(
            <div style={{animation:"fadeIn .4s ease both"}}>
              <div style={{display:"flex",gap:6,marginBottom:16,borderBottom:`1px solid ${T.border}`,paddingBottom:12}}>
                {[{id:"forecast",   icon:"📡",label:"Traffic Forecast"},
                  {id:"performance",icon:"🧪",label:"Model Performance"},
                ].map(tab=>(
                  <button key={tab.id} onClick={()=>setTab(tab.id)} style={{
                    padding:"9px 22px",borderRadius:10,cursor:"pointer",fontFamily:"inherit",
                    fontSize:11,letterSpacing:1,transition:"all .2s",fontWeight:600,
                    border:`1px solid ${activeTab===tab.id?T.accent:T.border}`,
                    background:activeTab===tab.id?T.accentDim:"transparent",
                    color:activeTab===tab.id?T.accent:T.sub,
                    boxShadow:activeTab===tab.id?T.glow:"none",
                  }}>
                    {tab.icon} {tab.label}
                  </button>
                ))}
                <div style={{marginLeft:"auto",display:"flex",alignItems:"center",gap:10}}>
                  <div style={{width:7,height:7,borderRadius:"50%",background:T.green,animation:"pulse 2s ease infinite"} }/>
                  <span style={{fontSize:9,color:T.sub,letterSpacing:1.5}}>LIVE · 3 MODELS ACTIVE</span>
                </div>
              </div>
              {activeTab==="forecast"    && renderForecast()}
              {activeTab==="performance" && renderPerformance()}
            </div>
          )}

          {!data&&!loading&&(
            <div style={{textAlign:"center",padding:"60px 0",color:T.sub,background:T.card,
              border:`1px solid ${T.border}`,borderRadius:16,boxShadow:T.shadow,animation:"fadeIn .8s ease"}}>
              <div style={{fontSize:48,marginBottom:14}}>🗺️</div>
              <div style={{fontSize:13,fontWeight:700,color:T.text,marginBottom:6}}>Click the map or select a corridor</div>
              <div style={{fontSize:9,color:T.sub,letterSpacing:2}}>RF CLASSIFIER · XGB CLASSIFIER · XGB REGRESSOR · WEATHER · 24H FORECAST</div>
            </div>
          )}

          <div style={{textAlign:"center",marginTop:28,paddingTop:14,borderTop:`1px solid ${T.border}`}}>
            <span style={{fontSize:8,color:T.sub,letterSpacing:2}}>
              USA ONLY · OPENWEATHER LIVE · RF CLASSIFIER + XGB CLASSIFIER + XGB REGRESSOR ENSEMBLE
            </span>
          </div>

        </div>
      </div>
    </>
  );
}