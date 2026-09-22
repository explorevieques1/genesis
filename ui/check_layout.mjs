const BAND_ORDER = ['execution','journal','strategy','research','charting']
const BAND_BASE=600, BAND_GAP=180, ARC_CENTRE=270, NODE_PITCH_DEG=27, ARC_HALF_WIDTH=950
const rad=d=>d*Math.PI/180, deg=r=>r*180/Math.PI
// roster counts; execution has 4 agents(176) + 2 spinal(210)
const fam = {
  execution:[210,210,176,176,176,176],
  journal:[176,176,176,176,176,176],
  strategy:[176,176,176,176,176,176,176],
  research:[176,176,176,176,176,176,176],
  charting:[176,176,176,176,176],
}
const H=44
const pos=[]
BAND_ORDER.forEach((f,band)=>{
  const list=fam[f]; const r=BAND_BASE+band*BAND_GAP
  const fitHalf=deg(Math.asin(Math.min(1,ARC_HALF_WIDTH/r)))
  const half=Math.min(fitHalf,(NODE_PITCH_DEG*(list.length-1))/2)
  const a0=ARC_CENTRE-half
  const step=list.length===1?0:(half*2)/(list.length-1)
  list.forEach((w,i)=>{
    const a=rad(list.length===1?ARC_CENTRE:a0+step*i)
    pos.push({id:`${f}${i}`,w,h:H,x:Math.cos(a)*r,y:Math.sin(a)*r})
  })
})
let bad=0
for(let i=0;i<pos.length;i++)for(let j=i+1;j<pos.length;j++){
  const a=pos[i],b=pos[j]
  const gx=Math.abs(a.x-b.x)-(a.w+b.w)/2
  const gy=Math.abs(a.y-b.y)-(a.h+b.h)/2
  if(gx<0&&gy<0){bad++;console.log('OVERLAP',a.id,b.id,{gx:gx.toFixed(0),gy:gy.toFixed(0)})}
}
const xs=pos.map(p=>p.x), ys=pos.map(p=>p.y)
console.log('nodes',pos.length,'overlaps',bad)
console.log('extent x',Math.min(...xs).toFixed(0),Math.max(...xs).toFixed(0),'y',Math.min(...ys).toFixed(0),Math.max(...ys).toFixed(0))
// min adjacent chord per family
BAND_ORDER.forEach(f=>{
  const g=pos.filter(p=>p.id.startsWith(f))
  let m=1e9; for(let i=1;i<g.length;i++)m=Math.min(m,Math.hypot(g[i].x-g[i-1].x,g[i].y-g[i-1].y))
  console.log(f,'min adjacent centre dist',m.toFixed(0))
})
