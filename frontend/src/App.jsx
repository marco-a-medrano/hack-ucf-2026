import React, {useMemo,useState} from 'react';
import {Activity, AlertTriangle, CarFront, CheckCircle2, CircleParking, Clock3, Database, LayoutDashboard, RotateCcw, ShieldCheck, ShieldAlert, Wifi, Zap} from 'lucide-react';

const seed=[
  {id:'A01',occupied:true,plate:'DEMO101',permit:'valid'},
  {id:'A02',occupied:true,plate:'TEST404',permit:'invalid'},
  {id:'A03',occupied:false,plate:null,permit:null},
  {id:'A04',occupied:true,plate:'UCF2026',permit:'valid'},
  {id:'A05',occupied:false,plate:null,permit:null},
  {id:'A06',occupied:true,plate:'PARK777',permit:'valid'},
  {id:'A07',occupied:false,plate:null,permit:null},
  {id:'A08',occupied:true,plate:'EXPIRE9',permit:'expired'},
  {id:'A09',occupied:false,plate:null,permit:null},
  {id:'A10',occupied:false,plate:null,permit:null},
  {id:'A11',occupied:true,plate:'OK1234',permit:'valid'},
  {id:'A12',occupied:false,plate:null,permit:null}
];
const permits={'DEMO101':'valid','UCF2026':'valid','PARK777':'valid','OK1234':'valid','EXPIRE9':'expired','TEST404':'invalid'};
const timestamp=()=>new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'});
function Stat({icon:Icon,title,value,note,tone}){return <section className="stat panel"><div className="stat-heading"><span>{title}</span><Icon size={19} className={tone||''}/></div><strong className={tone||''}>{value}</strong><small>{note}</small></section>}
export default function App(){
 const [spaces,setSpaces]=useState(seed);
 const [active,setActive]=useState('A01');
 const [logs,setLogs]=useState([{id:1,time:'Demo',msg:'Sample garage data loaded',kind:'info'}]);
 const [demoPlate,setDemoPlate]=useState('');
 const [filter,setFilter]=useState('all');
 const selected=spaces.find(s=>s.id===active);
 const available=spaces.filter(s=>!s.occupied).length;
 const occupied=spaces.length-available;
 const percent=Math.round(available/spaces.length*100);
 const review=spaces.filter(s=>s.occupied&&(s.permit==='invalid'||s.permit==='expired'));
 const display=useMemo(()=>spaces.filter(s=>filter==='all'||(filter==='available'?!s.occupied:filter==='occupied'?s.occupied:s.occupied&&s.permit!=='valid')),[spaces,filter]);
 const addLog=(msg,kind='info')=>setLogs(old=>[{id:Date.now()+Math.random(),time:timestamp(),msg,kind},...old].slice(0,12));
 function updateSpot(id,patch){setSpaces(old=>old.map(s=>s.id===id?{...s,...patch}:s));}
 function toggleSpot(id){const s=spaces.find(p=>p.id===id);if(!s)return;updateSpot(id,s.occupied?{occupied:false,plate:null,permit:null}:{occupied:true,plate:null,permit:'unreadable'});setActive(id);addLog(`${id} marked ${s.occupied?'available':'occupied'}`);}
 function verifyPlate(){if(!selected?.occupied)return;const plate=demoPlate.trim().toUpperCase().replace(/[^A-Z0-9]/g,'');if(!plate)return;const permit=permits[plate]||'invalid';updateSpot(active,{plate,permit});addLog(`${active}: ${plate} — ${permit==='valid'?'valid permit':permit==='expired'?'expired permit; flagged for review':'no valid permit; flagged for review'}`,permit==='valid'?'ok':'alert');setDemoPlate('');}
 function reset(){setSpaces(seed.map(s=>({...s})));setActive('A01');setDemoPlate('');setFilter('all');setLogs([{id:Date.now(),time:timestamp(),msg:'Demo data reset',kind:'info'}]);}
 return <div className="app">
  <aside className="sidebar"><div className="brand"><span className="brandmark"><CircleParking size={23}/></span><div><b>ParkVision</b><small>GARAGE INTELLIGENCE</small></div></div><div className="nav-label">WORKSPACE</div><div className="nav-selected"><LayoutDashboard size={19}/> Overview</div><div className="sidebar-bottom"><span className="status-pip"/> Demo mode <small>Local simulated data</small></div></aside>
  <main className="main">
    <header className="topbar"><div><div className="eyebrow">MONITORING / OVERVIEW</div><h1>Parking Garage Dashboard</h1><p>Live-style monitoring and parking authorization overview</p></div><div className="top-actions"><span className="demo"><span className="status-pip"/> DEMO MODE</span><button className="outline" onClick={reset}><RotateCcw size={16}/> Reset demo</button></div></header>
    <section className="stats"><Stat icon={CircleParking} title="Total Spaces" value={spaces.length} note="Garage Level 1"/><Stat icon={CheckCircle2} title="Available" value={available} note="Open parking spaces" tone="green"/><Stat icon={CarFront} title="Occupied" value={occupied} note="Detected vehicles" tone="rose"/><Stat icon={Activity} title="Availability" value={`${percent}%`} note="Current garage capacity" tone="blue"/></section>
    <section className="split"><div className="panel availability"><div className="section-head"><div><h2>Garage Availability</h2><p>Percentage of parking spaces currently open</p></div><span className="percentage">{percent}% available</span></div><div className="progress"><div style={{width:`${percent}%`}}/></div><div className="avail-bottom"><span><b className="green">{available}</b> available</span><span><b className="rose">{occupied}</b> occupied</span><span>{spaces.length} total</span></div></div><div className="panel rover"><div className="section-head"><div><h2>Rover Connection</h2><p>Hardware integration status</p></div><Wifi size={21} className="muted"/></div><div className="connection"><span className="connection-icon"><Zap size={22}/></span><div><b>Not Connected</b><small>ESP32 / Camera awaiting integration</small></div><span className="offline">OFFLINE</span></div><p className="fine">This demo uses manual inputs. No live camera or vehicle connection is active.</p></div></section>
    <section className="content-grid"><div className="panel map-panel"><div className="section-head map-heading"><div><h2>Level 1 — Parking Map</h2><p>Click a space to inspect it, then toggle its occupancy.</p></div><div className="filter"><label htmlFor="spot-filter">Show</label><select id="spot-filter" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">All spaces</option><option value="available">Available</option><option value="occupied">Occupied</option><option value="review">Needs review</option></select></div></div><div className="spot-grid">{display.map(s=><button key={s.id} title={`${s.id}: ${s.occupied?'Occupied':'Available'}`} onClick={()=>setActive(s.id)} className={`spot ${s.occupied?'occupied':'empty'} ${active===s.id?'active':''}`}><CarFront size={25}/><b>{s.id}</b><small>{s.occupied?'Occupied':'Available'}</small></button>)}</div>{!display.length&&<p className="empty-filter">No parking spaces match this filter.</p>}<div className="legend"><span><i className="green-dot"/> Available (0)</span><span><i className="red-dot"/> Occupied (1)</span><span><i className="outline-dot"/> Selected</span></div></div>
    <div className="rightcol"><div className="panel details"><div className="section-head"><div><h2>Space Details</h2><p>Selected parking spot</p></div><span className="idchip">{active}</span></div><div className="detail-line"><span>Occupancy</span><b className={selected?.occupied?'rose':'green'}>{selected?.occupied?'1 · Occupied':'0 · Available'}</b></div><div className="detail-line"><span>Plate</span><b>{selected?.plate||'—'}</b></div><div className="detail-line"><span>Permit</span><b className={selected?.permit==='valid'?'green':selected?.permit==='invalid'||selected?.permit==='expired'?'rose':''}>{selected?.permit?selected.permit.toUpperCase():'—'}</b></div><button className="primary full" onClick={()=>toggleSpot(active)}>Toggle occupancy (demo)</button>{selected?.occupied&&<div className="plate-form"><label htmlFor="plate">Simulate plate scan</label><div className="form-row"><input id="plate" value={demoPlate} onChange={e=>setDemoPlate(e.target.value)} onKeyDown={e=>e.key==='Enter'&&verifyPlate()} placeholder="e.g. UCF2026" maxLength={12}/><button className="outline" onClick={verifyPlate}>Verify</button></div><small>Try UCF2026 (valid), EXPIRE9 (expired), or UNKNOWN (not registered).</small></div>}</div>
    <div className="panel review"><div className="section-head"><div><h2>Ticket Review Queue</h2><p>Potential violations — human review required</p></div><span className="alert-count">{review.length}</span></div>{review.length?review.map(s=><div className="review-item" key={s.id}><ShieldAlert size={18} className="rose"/><div><b>{s.plate||'Unreadable plate'}</b><small>Space {s.id} · {s.permit==='expired'?'Expired permit':'No valid permit'}</small></div><span>Review</span></div>):<div className="allclear"><ShieldCheck size={22} className="green"/> No pending reviews</div>}</div></div></section>
    <section className="panel activity"><div className="section-head"><div><h2>Recent Activity</h2><p>Latest simulated occupancy and permit updates</p></div><Clock3 size={19} className="muted"/></div>{logs.map(l=><div className="log" key={l.id}><span className={`log-dot ${l.kind}`}/><span>{l.msg}</span><time>{l.time}</time></div>)}</section>
    <footer><Database size={15}/> Prototype dashboard · Demo values only · No real license plates are stored</footer>
  </main>
 </div>;
}
