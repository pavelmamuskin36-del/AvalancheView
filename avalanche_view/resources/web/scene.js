/* MapLibre owns the camera; deck receives its view through MapboxOverlay. */
'use strict';
let bridge, map, overlay, scene, selected = null, mode3d = false, exaggeration = 1;
let generation = 0, sceneIds = [], windLayers = [], contourLabels = [], extraLayers = [], streamPaths = [], styleIds = [], styleSources = [];
let terrainDescriptor = null, hill = {enabled:true,intensity:0.35,opacity:0.65,azimuth:315,altitude:45};
const extraDescriptors = new Map();
let terrainFailed = false, terrainErrorTimer = null;
function terrainStatus(){
 const d=terrainDescriptor,info=document.getElementById('terrain-info');
 if(!mode3d){info.textContent='';return;}
 const loaded=!!d&&Number.isFinite(map.queryTerrainElevation(map.getCenter()));
 info.textContent=d?`${d.name} · высоты ×${exaggeration}${loaded?'':' · загрузка DEM…'}`:'Нет источника высот';
}
 let activeBasemap = null, lastCursor = 0;
const empty = () => ({type:'FeatureCollection',features:[]});
function emit(type,payload={}){if(bridge) bridge.event(JSON.stringify({type,...payload}));}
function notice(message){const e=document.getElementById('notice');e.textContent=message;e.hidden=!message;}
function fatal(error){const message='WebGL / GIS: '+String(error)+'\nПроверьте драйвер видеокарты и Qt WebEngine. Для диагностики: py main.py --legacy-map';document.getElementById('fatal').textContent=message;document.getElementById('fatal').hidden=false;emit('error',{message});}
async function fetchData(url,type='json'){const r=await fetch(url);if(!r.ok)throw Error('Локальные данные недоступны: '+r.status);return type==='json'?r.json():r.arrayBuffer();}
function source(id,data){if(map.getSource(id))map.getSource(id).setData(data);else map.addSource(id,{type:'geojson',data});}
function remove(id){if(map.getLayer(id))map.removeLayer(id);if(map.getSource(id))map.removeSource(id);}
async function setBasemap(p){
 activeBasemap=p;
 for(const id of ['base-labels','base-raster'])remove(id);
 for(const id of styleIds)if(map.getLayer(id))map.removeLayer(id);for(const id of styleSources)if(map.getSource(id))map.removeSource(id);styleIds=[];styleSources=[];
 map.setLayoutProperty('land','visibility',p.id==='none'?'none':'visible');
 map.setLayoutProperty('borders','visibility',p.id==='none'?'none':'visible');
 if(p.type==='none')return;
 if(p.type==='style'){
  const style=await fetchData(p.url);if(activeBasemap!==p)return;
  const absolute=url=>url?new URL(url,p.url).href:url;
  if(style.glyphs)map.setGlyphs(absolute(style.glyphs));if(typeof style.sprite==='string')map.setSprite(absolute(style.sprite));
  for(const [key,value] of Object.entries(style.sources)){const id='basestyle-'+key;map.addSource(id,{...value,...(value.url?{url:absolute(value.url)}:{}),...(value.tiles?{tiles:value.tiles.map(absolute)}:{}),attribution:p.attribution});styleSources.push(id);}
  for(const layer of style.layers){const id='basestyle-'+layer.id;map.addLayer({...layer,id,...(layer.source?{source:'basestyle-'+layer.source}:{})},'borders');styleIds.push(id);}return;
 }
 map.addSource('base-raster',{type:'raster',tiles:[p.url],tileSize:256,minzoom:p.minZoom,maxzoom:p.maxZoom,attribution:p.attribution});
 map.addLayer({id:'base-raster',type:'raster',source:'base-raster'},'borders');
 if(p.labels_url){map.addSource('base-labels',{type:'raster',tiles:[p.labels_url],tileSize:256,attribution:'© CARTO, © OpenStreetMap contributors'});map.addLayer({id:'base-labels',type:'raster',source:'base-labels'});}
 notice('');
}
function setTerrain(d){
 if(JSON.stringify(d)!==JSON.stringify(terrainDescriptor)){
  terrainFailed=false;clearTimeout(terrainErrorTimer);
  map.setTerrain(null);remove('terrain-shade');remove('shade-dem');remove('terrain-dem');terrainDescriptor=d;
  if(d){const config={type:'raster-dem',tiles:[d.url],tileSize:256,encoding:d.encoding||'mapbox',maxzoom:d.maxZoom||14,...(d.bounds?{bounds:d.bounds}:{}),attribution:d.attribution||d.name};map.addSource('terrain-dem',config);map.addSource('shade-dem',config);}
 }
 if(d){
  if(!map.getLayer('terrain-shade'))map.addLayer({id:'terrain-shade',type:'hillshade',source:'shade-dem'},sceneIds.find(id=>map.getLayer(id)));
  map.setLayoutProperty('terrain-shade','visibility',hill.enabled?'visible':'none');
  map.setPaintProperty('terrain-shade','hillshade-exaggeration',hill.intensity);
  map.setPaintProperty('terrain-shade','hillshade-shadow-color',`rgba(0,0,0,${hill.opacity})`);
  map.setPaintProperty('terrain-shade','hillshade-highlight-color',`rgba(255,255,255,${hill.opacity})`);
  map.setPaintProperty('terrain-shade','hillshade-illumination-direction',hill.azimuth);
  map.setPaintProperty('terrain-shade','hillshade-illumination-altitude',hill.altitude);
  map.setTerrain(mode3d?{source:'terrain-dem',exaggeration}:null);
 }else if(mode3d)notice('Нет источника высоты. Загрузите HGT/HGT_M или GeoTIFF DEM.');
 terrainStatus();
}
function setMode(enabled){mode3d=enabled;setTerrain(terrainDescriptor);map.easeTo({pitch:enabled?65:0,duration:650});emit('mode',{mode:enabled?'3D':'2D'});}
function fit(){if(scene)map.fitBounds([[scene.bounds[0],scene.bounds[1]],[scene.bounds[2],scene.bounds[3]]],{padding:55,duration:650});}
function cells(layer,corners,rgba,values){
 const [ny,nx]=layer.shape, features=[];
 const p=(i,j)=>{const k=2*(i*(nx+1)+j);return[corners[k],corners[k+1]];};
 for(let i=0;i<ny;i++)for(let j=0;j<nx;j++){
  const k=i*nx+j;if(!rgba[k*4+3])continue;
  const a=p(i,j),b=p(i,j+1),c=p(i+1,j+1),d=p(i+1,j);
  features.push({type:'Feature',properties:{color:`rgb(${rgba[k*4]},${rgba[k*4+1]},${rgba[k*4+2]})`,value:values[k],row:i,column:j},geometry:{type:'Polygon',coordinates:[[a,b,c,d,a]]}});
 }return{type:'FeatureCollection',features};
}
async function updateScene(s){
 const revision=++generation, prepared=[];
 for(const layer of s.layers){
  const [cb,rb,vb]=await Promise.all([fetchData(layer.corners,'binary'),fetchData(layer.colors,'binary'),fetchData(layer.values,'binary')]);
  const cellData=cells(layer,new Float64Array(cb),new Uint8Array(rb),new Float64Array(vb));
  const lines=layer.contours?await fetchData(layer.contours):null;
  const wind=layer.wind?new Float64Array(await fetchData(layer.wind,'binary')):null;
  const streams=layer.streamlines?await fetchData(layer.streamlines):null;
  prepared.push({layer,cellData,lines,wind,streams});
 }
 if(revision!==generation)return;
 scene=s;window.avalancheScene=s;windLayers=[];contourLabels=[];streamPaths=[];
 const wanted=[];
 for(const {layer:l,cellData,lines,wind,streams} of prepared){
  const id='field-'+l.id, lineId=id+'-contour';
  const fill=!['Contour lines','Wind vectors','Wind barbs','Streamlines'].includes(l.mode);
  if(fill){source(id,cellData);wanted.push(id);if(!map.getLayer(id))map.addLayer({id,type:'fill',source:id,paint:{'fill-color':['get','color'],'fill-antialias':false}});
   map.setPaintProperty(id,'fill-opacity',l.opacity);
   if(l.cell_edges||l.mode==='Native grid'){const edge=id+'-edges';wanted.push(edge);if(!map.getLayer(edge))map.addLayer({id:edge,type:'line',source:id,paint:{'line-color':'#203b4a','line-width':0.45,'line-opacity':0.4}});}
  }
  if(lines){source(lineId,lines);wanted.push(lineId);if(!map.getLayer(lineId))map.addLayer({id:lineId,type:'line',source:lineId,paint:{'line-color':['get','color']}});map.setPaintProperty(lineId,'line-width',l.contour_width);map.setPaintProperty(lineId,'line-opacity',l.opacity);
   if(l.contour_labels)for(const f of lines.features){if(f.geometry.coordinates.length>8)contourLabels.push({position:f.geometry.coordinates[Math.floor(f.geometry.coordinates.length/2)],text:f.properties.label});}
  }
  if(wind&&!streams)windLayers.push({layer:l,wind});
  if(streams)for(const f of streams.features)streamPaths.push({path:f.geometry.coordinates,opacity:l.opacity});
 }
 // Remove layers before their shared sources (cell edge layers use the fill source).
 for(const id of sceneIds.filter(id=>!wanted.includes(id)).reverse()){if(map.getLayer(id))map.removeLayer(id);}
 for(const id of sceneIds.filter(id=>!wanted.includes(id))){if(map.getSource(id))map.removeSource(id);}
 sceneIds=wanted;for(const id of wanted)map.moveLayer(id);
 source('domain',s.domain);if(!map.getLayer('domain'))map.addLayer({id:'domain',type:'line',source:'domain',paint:{'line-color':'#ffca69','line-width':2,'line-dasharray':[4,2]}});map.moveLayer('domain');
 setTerrain(s.terrain);document.getElementById('time').textContent=s.timestamp;
 if(map.getLayer('terrain-shade'))map.moveLayer('terrain-shade','domain');
 updateLegend(s.layers);notice(s.warnings.join('\n'));if(s.reset)fit();updateDeck();
 map.once('idle',()=>emit('rendered',{timestep:s.timestep,revision:s.revision,camera:camera(),layerCount:s.layers.length}));map.triggerRepaint();
}
function legendLayers(){return [...(scene?.layers||[]),...extraDescriptors.values()].filter(l=>l.show_colorbar&&!l.hidden);}
function updateLegend(){const root=document.getElementById('legend');root.replaceChildren();for(const l of legendLayers()){
 const row=document.createElement('div');row.className='legend-row';const label=document.createElement('div');label.textContent=l.name+' · '+l.units+(l.smooth?' · 3×3':'');row.append(label);
 if(l.categories){for(const category of l.categories){const item=document.createElement('div'),swatch=document.createElement('span');swatch.style.cssText=`display:inline-block;width:12px;height:12px;margin-right:6px;background:rgb(${category.color.slice(0,3).join(',')})`;item.append(swatch,document.createTextNode(category.label));row.append(item);}root.append(row);continue;}
 const ramp=document.createElement('div');ramp.className='ramp';ramp.style.background='linear-gradient(to right,'+l.palette.map(c=>`rgb(${c[0]},${c[1]},${c[2]})`).join(',')+')';row.append(ramp);
 const ticks=document.createElement('div');ticks.className='ticks';for(const v of [l.minimum,l.maximum]){const t=document.createElement('span');t.textContent=Number(v.toPrecision(5));ticks.append(t);}row.append(ticks);if(l.colormap==='twilight'){const compass=document.createElement('div');compass.textContent='N · NE · E · SE · S · SW · W · NW · N';row.append(compass);}root.append(row);
}}
function height(p){return mode3d?(map.queryTerrainElevation(p)||0)+20:0;}
function lifted(p){return[p[0],p[1],height(p)];}
function updateDeck(){
 if(!overlay)return;const layers=[], bounds=map.getBounds(), segments=[];
 for(const {layer:l,wind:a} of windLayers){
  const occupied=new Set(),[ny,nx]=l.shape,stride=l.auto_density?1:l.vector_stride;
  for(let i=0;i<ny;i+=stride)for(let j=0;j<nx;j+=stride){const k=(i*nx+j)*4,p=[a[k],a[k+1]],u=a[k+2],v=a[k+3],speed=Math.hypot(u,v);
   if(!Number.isFinite(speed)||speed<0.01||!bounds.contains(p))continue;
   const pt=map.project(p),bin=Math.floor(pt.x/45)+':'+Math.floor(pt.y/45);if(l.auto_density&&occupied.has(bin))continue;occupied.add(bin);
   const q=map.project([p[0]+u/Math.cos(p[1]*Math.PI/180)*0.001,p[1]+v*0.001]);let dx=q.x-pt.x,dy=q.y-pt.y;const length=Math.hypot(dx,dy);dx/=length;dy/=length;
   const geo=(x,y)=>{const ll=map.unproject([x,y]);return lifted([ll.lng,ll.lat]);};
   const start=geo(pt.x-dx*12,pt.y-dy*12),end=geo(pt.x+dx*12,pt.y+dy*12);
   const color=l.palette[Math.round(Math.min(1,Math.max(0,(speed-l.minimum)/(l.maximum-l.minimum)))*(l.palette.length-1))];
   const add=(a,b)=>segments.push({a,b,color:[color[0],color[1],color[2],Math.round(l.opacity*255)]});add(start,end);
   if(l.mode.includes('barbs')||l.mode==='Wind barbs'){
    // Meteorological feather increments: 50/10/5 knots, rooted at the upwind end.
    let knots=Math.round(speed*1.943844/5)*5,offset=0;
    const stroke=(along,side)=>geo(pt.x-dx*(12-along)-dy*side,pt.y-dy*(12-along)+dx*side);
    while(knots>=50){add(stroke(offset,0),stroke(offset,10));add(stroke(offset,10),stroke(offset+5,0));offset+=6;knots-=50;}
    while(knots>=10){add(stroke(offset,0),stroke(offset+3,9));offset+=4;knots-=10;}
    if(knots>=5)add(stroke(offset,0),stroke(offset+2,5));
   }else{add(end,geo(pt.x+dx*6-dy*4,pt.y+dy*6+dx*4));add(end,geo(pt.x+dx*6+dy*4,pt.y+dy*6-dx*4));}
  }
 }
 if(segments.length)layers.push(new deck.LineLayer({id:'wind-glyphs',data:segments,getSourcePosition:d=>d.a,getTargetPosition:d=>d.b,getColor:d=>d.color,getWidth:1.6,widthUnits:'pixels',parameters:{depthTest:false}}));
 if(streamPaths.length)layers.push(new deck.PathLayer({id:'wind-streamlines',data:streamPaths,getPath:d=>d.path.map(lifted),getColor:d=>[25,48,65,Math.round(d.opacity*255)],getWidth:1.4,widthUnits:'pixels',parameters:{depthTest:false}}));
 if(contourLabels.length)layers.push(new deck.TextLayer({id:'contour-labels',data:contourLabels.slice(0,1500),getPosition:d=>lifted(d.position),getText:d=>d.text,getSize:11,getColor:[25,35,50],background:true,getBackgroundColor:[255,255,255,210],fontFamily:'Segoe UI',parameters:{depthTest:false}}));
 if(selected)layers.push(new deck.ScatterplotLayer({id:'selected-point',data:[selected],getPosition:lifted,getRadius:6,radiusUnits:'pixels',getFillColor:[255,200,75],stroked:true,getLineColor:[20,40,50],lineWidthUnits:'pixels',getLineWidth:2,parameters:{depthTest:false}}));
 overlay.setProps({layers:[...extraLayers,...layers]});
}
function camera(){const c=map.getCenter();return{center:[c.lng,c.lat],zoom:map.getZoom(),pitch:map.getPitch(),bearing:map.getBearing()};}
async function exportPNG(scale){
 const ratio=map.getPixelRatio();try{
  const exportRatio=Math.min(4,Math.max(1,scale));overlay.setProps({useDevicePixels:exportRatio});map.setPixelRatio(exportRatio);map.resize();await new Promise(resolve=>{map.once('idle',resolve);map.triggerRepaint();});
  const canvas=document.createElement('canvas'),base=map.getCanvas();canvas.width=base.width;canvas.height=base.height;const ctx=canvas.getContext('2d');ctx.drawImage(base,0,0);
  const deckCanvas=document.querySelector('canvas.deck-canvas');if(deckCanvas)ctx.drawImage(deckCanvas,0,0,canvas.width,canvas.height);
  const r=map.getPixelRatio();ctx.scale(r,r);ctx.fillStyle='#fffffff0';ctx.fillRect(12,12,440,55);ctx.fillStyle='#203049';ctx.font='bold 16px Segoe UI';ctx.fillText('AvalancheView · '+(scene?.timestamp||''),24,36);ctx.font='12px Segoe UI';ctx.fillText(mode3d?'3D · Terrain ×'+exaggeration:'2D · Native model grid',24,55);
  let y=90;for(const l of legendLayers()){const w=210,x=base.width/r-w-20;if(l.categories){ctx.fillStyle='#fffffff0';ctx.fillRect(x-8,y-20,w+16,25+l.categories.length*18);ctx.fillStyle='#203049';ctx.fillText(l.name+' ['+l.units+']',x,y-5);for(const category of l.categories){ctx.fillStyle=`rgb(${category.color.slice(0,3).join(',')})`;ctx.fillRect(x,y,12,12);ctx.fillStyle='#203049';ctx.fillText(category.label,x+18,y+11);y+=18;}y+=30;continue;}ctx.fillStyle='#fffffff0';ctx.fillRect(x-8,y-20,w+16,58);ctx.fillStyle='#203049';ctx.fillText(l.name+' ['+l.units+']',x,y-5);const grad=ctx.createLinearGradient(x,0,x+w,0);l.palette.forEach((c,i)=>grad.addColorStop(i/Math.max(1,l.palette.length-1),`rgb(${c[0]},${c[1]},${c[2]})`));ctx.fillStyle=grad;ctx.fillRect(x,y,w,9);ctx.fillStyle='#203049';ctx.fillText(Number(l.minimum.toPrecision(5))+' — '+Number(l.maximum.toPrecision(5)),x,y+26);y+=70;}
  const attribution=document.querySelector('.maplibregl-ctrl-attrib-inner')?.textContent||'Natural Earth';const scaleEl=document.querySelector('.maplibregl-ctrl-scale');const bottom=base.height/r;ctx.fillStyle='#ffffffed';ctx.fillRect(0,bottom-36,base.width/r,36);ctx.fillStyle='#203049';ctx.fillText(attribution,12,bottom-9);if(scaleEl){const w=scaleEl.getBoundingClientRect().width;ctx.fillRect(12,bottom-30,w,2);ctx.fillText(scaleEl.textContent,20+w,bottom-25);}
  emit('export',{png:canvas.toDataURL('image/png').split(',')[1],width:canvas.width,height:canvas.height});
 }finally{overlay.setProps({useDevicePixels:ratio});map.setPixelRatio(ratio);map.resize();map.triggerRepaint();}
}
async function command(c){switch(c.type){
 case 'scene':await updateScene(c.scene);break;
 case 'basemap':await setBasemap(c.provider);break;
 case 'mode':setMode(c.enabled);break;
 case 'mountains':mode3d=true;setTerrain(terrainDescriptor);map.flyTo({center:c.center||map.getCenter(),zoom:11.2,pitch:68,bearing:25,duration:1500});emit('mode',{mode:'3D'});break;
 case 'terrainNotice':notice(c.message);break;
 case 'elevationProbe':emit('elevationProbe',{points:c.points.map(p=>({point:p,height:map.queryTerrainElevation(p)}))});break;
 case 'terrain':Object.assign(hill,c.hill||{});exaggeration=c.exaggeration??exaggeration;setTerrain(c.source===undefined?terrainDescriptor:c.source);break;
 case 'fit':fit();break;case 'home':map.easeTo({center:[43.35,42.4],zoom:5,pitch:0,bearing:0});break;
 case 'zoomIn':map.zoomIn();break;
 case 'point':selected=c.point;updateDeck();break;
 case 'theme':document.body.classList.toggle('dark',c.dark);break;
 case 'export':await exportPNG(c.scale||2);break;
 case 'camera':map.jumpTo(c.camera);break;
 case 'diagnostics':{const height=map.queryTerrainElevation(map.getCenter());emit('diagnostics',{camera:camera(),webgl:!!map.getCanvas().getContext('webgl2'),terrain:map.getTerrain(),terrainSource:terrainDescriptor,terrainLoaded:!!terrainDescriptor&&Number.isFinite(height),sources:Object.keys(map.getStyle().sources),layers:map.getStyle().layers.map(l=>l.id),deckLayers:overlay?overlay._deck.props.layers.map(l=>l.id):[],height});break;}
 case 'interactive':for(const key of ['scrollZoom','boxZoom','dragRotate','dragPan','keyboard','doubleClickZoom','touchZoomRotate'])map[key][c.enabled?'enable':'disable']();break;
 case 'overlay':source(c.id,c.url);for(const [suffix,type,paint] of [['fill','fill',{'fill-color':c.color||'#ed9144','fill-opacity':0.25}],['line','line',{'line-color':c.color||'#e97b36','line-width':2}],['point','circle',{'circle-color':c.color||'#e97b36','circle-radius':5}]]){const id=c.id+'-'+suffix;if(!map.getLayer(id))map.addLayer({id,type,source:c.id,paint});}break;
 case 'extraScalar':{
  const l=c.layer,id='extra-'+l.id;const [a,b,v]=await Promise.all([fetchData(l.corners,'binary'),fetchData(l.colors,'binary'),fetchData(l.values,'binary')]);source(id,cells(l,new Float64Array(a),new Uint8Array(b),new Float64Array(v)));map.addLayer({id,type:'fill',source:id,paint:{'fill-color':['get','color'],'fill-opacity':l.opacity,'fill-antialias':false}});extraDescriptors.set(id,l);updateLegend();break;
 }
 case 'visibility':for(const l of map.getStyle().layers.filter(l=>l.id===c.id||l.id.startsWith(c.id+'-')))map.setLayoutProperty(l.id,'visibility',c.visible?'visible':'none');if(extraDescriptors.has(c.id))extraDescriptors.get(c.id).hidden=!c.visible;updateLegend();break;
 case 'removeOverlay':for(const l of map.getStyle().layers.filter(l=>l.id===c.id||l.id.startsWith(c.id+'-')))map.removeLayer(l.id);if(map.getSource(c.id))map.removeSource(c.id);extraDescriptors.delete(c.id);updateLegend();break;
 }}
function start(){
 try{if(!document.createElement('canvas').getContext('webgl2'))throw Error('WebGL 2 недоступен');
  map=new maplibregl.Map({container:'map',center:[43.35,42.4],zoom:4.6,maxZoom:19,maxPitch:80,canvasContextAttributes:{preserveDrawingBuffer:true},style:{version:8,sources:{countries:{type:'geojson',data:'countries.geojson',attribution:'Natural Earth (public domain)'}},layers:[{id:'background',type:'background',paint:{'background-color':'#b9d5de'}},{id:'land',type:'fill',source:'countries',paint:{'fill-color':'#e7e8df'}},{id:'borders',type:'line',source:'countries',paint:{'line-color':'#879e9f','line-width':0.6}}]}});
  window.avalancheMap=map;map.addControl(new maplibregl.NavigationControl({visualizePitch:true}),'top-right');map.addControl(new maplibregl.ScaleControl({unit:'metric'}),'bottom-left');
  map.on('error',e=>{emit('tileError',{message:String(e.error?.message||e.error),source:e.sourceId});
   if(['terrain-dem','shade-dem'].includes(e.sourceId)){
    notice('Не удалось загрузить DEM. Проверьте подключение или выберите локальный рельеф.');
    if(!terrainFailed&&!terrainErrorTimer)terrainErrorTimer=setTimeout(()=>{terrainErrorTimer=null;if(terrainDescriptor?.type==='raster-dem'){terrainFailed=true;emit('terrainUnavailable');}},2000);
   }else notice('Источник карты недоступен. Локальные модельные слои продолжают работать.');});
  map.getCanvas().addEventListener('webglcontextlost',()=>fatal('Потерян графический контекст'));
  map.on('load',()=>{overlay=new deck.MapboxOverlay({interleaved:true,layers:[]});map.addControl(overlay);emit('ready');});
  map.on('moveend',()=>{updateDeck();emit('camera',{camera:camera()});});
  let terrainUpdate;
  map.on('sourcedata',e=>{if(e.sourceId==='terrain-dem'&&e.isSourceLoaded){terrainStatus();clearTimeout(terrainUpdate);terrainUpdate=setTimeout(updateDeck,80);}});
  map.on('click',e=>emit('point',{lon:e.lngLat.lng,lat:e.lngLat.lat}));
  map.on('mousemove',e=>{const now=performance.now();if(now-lastCursor<100)return;lastCursor=now;emit('cursor',{lon:e.lngLat.lng,lat:e.lngLat.lat,elevation:map.queryTerrainElevation(e.lngLat)});});
 }catch(e){fatal(e);}
}
new QWebChannel(qt.webChannelTransport,channel=>{bridge=channel.objects.bridge;bridge.command.connect(raw=>command(JSON.parse(raw)).catch(fatal));start();});
