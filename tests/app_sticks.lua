-- Actual lifecycle/atlas/directory, with native services stubbed; no network.
local function copy(v)
    if type(v)~='table' then return v end
    local r={};for k,value in pairs(v) do r[k]=copy(value) end;return r
end
local fixtures,next_json={},0
json={encode=function(v)
    next_json=next_json+1;local key='['..next_json..']';fixtures[key]=copy(v);return key
end,decode=function(key) assert(fixtures[key]);return copy(fixtures[key]) end}
package.loaded.atlas_data={schema=1,built_at='2026-10-07',tile_w=672,tile_h=252,
    stations={{'zero',0,0,'GB','Zero'}, {'east',0,10,'GB','East'},
        {'west',0,-10,'GB','West'}, {'north',10,0,'GB','North'}, {'south',-10,0,'GB','South'}}}
local state,requests,responses,saved,plays,pauses,stops,redraws,scans,idle,keyboard_result,current
-- View is the observer; there is no test-only state API in the app.
package.loaded.view={draw=function(s) state=s end}
local Atlas=require('atlas')
local nearest=Atlas.nearest
Atlas.nearest=function(self,limit) scans=scans+1;return nearest(self,limit) end
local function record(id)
    return {stationuuid=id,name=id,url_resolved='https://example.invalid/'..id,
        codec='MP3',lastcheckok=1,hls=0,countrycode='GB'}
end
local function reset()
    requests={};responses={};plays={};pauses={};stops=0;redraws=0;scans=0;keyboard_result=nil
    current={state='stopped',error=''}
    local rows={};for i=1,6 do rows[i]=record('station-'..i) end
    saved={['frequency.v1']={version=1,volume=0.7,favorites=copy(rows),recent=copy(rows)},
        ['frequency.cache.v1']={version=1,key='\n\nAll sounds\n0',stations=rows}}
    http={get_async=function(url) requests[#requests+1]=url;return #requests end,
        poll=function() local r=responses;responses={};return r end,
        get=function() error('blocking network forbidden') end}
    storage={load=function(k) return copy(saved[k]) end,save=function(k,v) saved[k]=copy(v) end}
    app={request_redraw=function() redraws=redraws+1 end,set_idle_fps=function(n) idle=n end}
    audio={stream=function(url) plays[#plays+1]=url;current={state='connecting',url=url,error=''} end,
        stream_status=function() return current end,set_stream_volume=function() end,
        pause_stream=function(paused) pauses[#pauses+1]=paused;current.state=paused and 'paused' or 'playing' end,
        stop_stream=function() stops=stops+1;current={state='stopped',error=''} end}
    text_input={show=function() end,poll=function() local r=keyboard_result;keyboard_result=nil;return r end}
    dofile('main.lua');on_init();on_render()
    assert(#plays==0 and idle==5,'launch stays stopped and idle stays at 5 Hz')
end
local function press(button,action) on_input(button,action or 'press') end
local function tick(n,dt) for _=1,n do on_update(dt or 1/30) end end
local function near(a,b,label) assert(math.abs(a-b)<1e-9,label or (a..' ~= '..b)) end
local function map() press('dpad_right');assert(state.focus=='map') end
local function menu(index)
    press('start');for _=2,index do press('dpad_down') end;press('a')
end
local function respond(id,data)
    responses[#responses+1]={id=id,ok=true,status=200,body=json.encode(data)};on_update(0)
end

-- Changed-state callbacks are quiet at neutral; holding a horizontal right
-- stick, invalid dt, or rendering repeatedly does not animate/recompute.
reset();map()
local n,r,q=scans,redraws,#requests
on_stick('left',0,0);on_stick('right',0,0);tick(60)
on_stick('right',1,0);tick(10);on_stick('right',0,0)
on_stick('unknown',1,1);on_stick(nil,1,1)
for _=1,10 do on_render() end
assert(scans==n and redraws==r and #requests==q,'neutral/unused axes must not redraw, scan or fetch')

-- Proportional movement is independent of update partition and zoom scale.
local function displacement(dts,x,y,zoom)
    reset();map();state.atlas.zoom=zoom or 1
    local u,v=state.atlas.u,state.atlas.v
    on_stick('left',x,y);for _,dt in ipairs(dts) do on_update(dt) end
    return (state.atlas.u-u)*672*state.atlas.zoom,(state.atlas.v-v)*252*state.atlas.zoom
end
local dx,dy=displacement({0.02,0.03,0.05},0.5,0)
near(dx,9);near(dy,0)
local alternate=displacement({0.1},0.5,0);near(dx,alternate,'variable dt must preserve distance')
local zoomed=displacement({0.1},0.5,0,8);near(dx,zoomed,'pan speed uses viewport pixels at every zoom')
dx,dy=displacement({0.1},0.6,-0.8);near(dx,10.8);near(dy,-14.4,'negative y pans up')
near(math.sqrt(dx*dx+dy*dy),18,'normalized diagonal must preserve vector speed')
local full=displacement({0.1},1,0);near(full,2*alternate,'deflection scales speed')
dx,dy=displacement({0.1},1,1)
near(dx,dy);near(math.sqrt(dx*dx+dy*dy),18,'full diagonal is capped to full stick speed')

-- Invalid time is ignored; a long stall cannot cause a giant movement.
reset();map();on_stick('left',1,0)
local u,v=state.atlas.u,state.atlas.v;n=scans;r=redraws
for _,dt in ipairs({0,-1,0/0,math.huge,-math.huge,'0.1',false}) do on_update(dt) end
on_update(nil)
near(state.atlas.u,u);near(state.atlas.v,v);assert(scans==n and redraws==r)
on_update(9);near((state.atlas.u-u)*672,18,'pan dt is capped at 100 ms')

-- Malformed axes cancel a previous hold, without poisoning atlas coordinates.
for _,axes in ipairs({{'1',0},{nil,0},{0/0,0},{math.huge,0},{0,-math.huge},{1.01,0},{0,-1.01}}) do
    reset();map();on_stick('left',1,0);on_stick('left',axes[1],axes[2])
    u,v=state.atlas.u,state.atlas.v;r=redraws;n=scans
    tick(3);near(state.atlas.u,u);near(state.atlas.v,v)
    on_stick('left',0.9,0);tick(2);near(state.atlas.u,u,'bad axes require neutral before reuse')
    assert(scans==n and redraws==r)
    on_stick('left',0,0);on_stick('left',1,0);on_update(.1);assert(state.atlas.u>u)
end

-- Fractional input is accumulated, but no image pixel change means no redraw.
reset();map();n=scans;r=redraws
on_stick('left',0.001,0);tick(3,.01);on_stick('left',0,0)
assert(scans==n and redraws==r,'subpixel pan must not redraw or scan')
state.atlas:set_cursor(-90,180);n=scans;r=redraws
on_stick('left',1,1);tick(20);on_stick('left',0,0)
assert(scans==n and redraws==r,'clamped edge holds must not redraw or scan')

-- Scans are modest while held, flush once on release, then stop entirely.
reset();map();q=#requests;n=scans
on_stick('left',1,0);tick(30)
assert(scans-n>=6 and scans-n<=10,'nearby scans must be bounded during one second of pan')
on_stick('left',0,0);assert(not state.map_dirty,'release flushes final visible position')
n=scans;r=redraws;tick(30)
assert(scans==n and redraws==r and #requests==q,'map pan/settled idle must not fetch or animate')

-- A tiny visible movement invalidates a pending tune immediately, before the
-- next nearest scan. Choosing/tuning during pan flushes the current list first.
reset();map();press('a');local lookup=#requests
assert(requests[lookup]:find('/json/stations/byuuid/zero',1,true))
local generation=state.map_generation;n=scans
on_stick('left',1,0);on_update(.01)
assert(state.map_generation>generation and not state.map_loading and scans==n,
    'generation cancellation must not wait for the nearest refresh')
respond(lookup,{record('zero')});assert(#plays==0,'late analog-pan response cannot autoplay')
-- A reply delivered in the very first pan update also cannot start playback.
reset();map();press('a');lookup=#requests
responses[#responses+1]={id=lookup,ok=true,status=200,body=json.encode({record('zero')})}
on_stick('left',1,0);on_update(.01)
assert(#plays==0 and not state.map_loading,'movement must cancel before same-update HTTP delivery')
press('r1');assert(not state.map_dirty and state.map_selected==2)
on_update(.01);assert(state.map_dirty);press('a');assert(not state.map_dirty)

-- Zoom steps once per tilt; trigger/release hysteresis survives noise, direct
-- reversal and holding at a bound. Horizontal right-stick motion is ignored.
reset();map();q=#requests
on_stick('right',0,-.59);assert(state.atlas.zoom==1)
on_stick('right',0,-.6);assert(state.atlas.zoom==2)
tick(60)
for _,y in ipairs({-.59,-.61,-.4,-.99,.9,-.8}) do on_stick('right',0,y) end
assert(state.atlas.zoom==2,'noise/hold/reversal must not consume another zoom step')
on_stick('right',.5,-.3);on_stick('right',.5,-.6);assert(state.atlas.zoom==4)
on_stick('right',0,0);on_stick('right',0,-1);assert(state.atlas.zoom==8)
on_stick('right',0,0);n=scans;r=redraws
on_stick('right',0,-1);on_stick('right',0,1);tick(10)
assert(state.atlas.zoom==8 and scans==n and redraws==r,'a tilt at maximum still latches')
on_stick('right',0,.3);on_stick('right',0,.6);assert(state.atlas.zoom==4)
on_stick('right',1,0);on_stick('right',0,1);assert(state.atlas.zoom==2)
on_stick('right',0,0);on_stick('right',0,1);assert(state.atlas.zoom==1)
on_stick('right',0,0);n=scans;r=redraws
on_stick('right',0,1);on_stick('right',0,-1);assert(state.atlas.zoom==1)
assert(scans==n and redraws==r and #requests==q,'zoom is local and bounded')
on_stick('right',0,0);on_stick('right',0,0/0);on_stick('right',0,-1)
assert(state.atlas.zoom==1,'invalid zoom axis requires a neutral state')
on_stick('right',0,0);on_stick('right',0,-1);assert(state.atlas.zoom==2)


-- A stick held across an overlay/view change stays blocked even when changed
-- callbacks arrive from noise. Fresh left-stick input can navigate the menu.
reset();map();on_stick('left',.8,-.2);on_update(.03);press('start')
u,v=state.atlas.u,state.atlas.v
on_stick('left',.9,-.2);tick(20);assert(state.menu_cursor==1)
near(state.atlas.u,u);near(state.atlas.v,v)
press('start');on_stick('left',1,0);tick(10);near(state.atlas.u,u)
on_stick('left',0,0);on_stick('left',.8,0);on_update(.03);assert(state.atlas.u>u)
press('start');on_stick('left',0,0);on_stick('left',0,1)
assert(state.menu_cursor==2);tick(12);assert(state.menu_cursor==3,'menu navigation repeats')
u=state.atlas.u;press('b');on_stick('left',.1,.9);tick(12);near(state.atlas.u,u)
on_stick('left',0,0);on_stick('left',.8,0);on_update(.03);assert(state.atlas.u>u)
press('b');assert(state.focus=='list')
local selected=state.selected;on_stick('left',0,1);tick(12);assert(state.selected==selected)
on_stick('left',0,0);on_stick('left',0,1);assert(state.selected==selected+1)
on_stick('left',0,0);on_stick('left',1,0);assert(state.focus=='map')
u=state.atlas.u;tick(10);on_stick('left',.9,.1);tick(10);near(state.atlas.u,u)
on_stick('left',0,0);on_stick('left',.9,0);on_update(.03);assert(state.atlas.u>u)
on_stick('right',0,-1);local zoom=state.atlas.zoom;press('start');press('b')
on_stick('right',0,.9);assert(state.atlas.zoom==zoom,'right stick must recenter across overlays')
on_stick('right',0,0);on_stick('right',0,1);assert(state.atlas.zoom==zoom/2)

-- Keyboard suspends both sticks, including holds that begin while editing.
reset();on_stick('left',0,1);press('y');selected=state.selected
on_stick('left',0,.9);on_stick('right',0,-1);tick(15)
assert(state.selected==selected and state.atlas.zoom==1)
keyboard_result=false;on_update(.03);assert(not state.keyboard)
on_stick('left',0,1);tick(15);assert(state.selected==selected,'closing keyboard must not resume navigation')
press('dpad_right');u=state.atlas.u;tick(5);on_stick('left',1,0);tick(5);near(state.atlas.u,u)
on_stick('right',0,.9);assert(state.atlas.zoom==1)
on_stick('left',0,0);on_stick('left',1,0);on_update(.03);assert(state.atlas.u>u)
on_stick('right',0,0);on_stick('right',0,-1);assert(state.atlas.zoom==2)

-- Non-map left navigation: dominant direction, hysteresis/repeat, boundaries,
-- favorites/recent, countries/pages, settings/volume, and details/About exit.
reset();q=#requests
on_stick('left',0,.59);assert(state.selected==1)
on_stick('left',.6,.8);assert(state.selected==2,'diagonal uses dominant axis')
tick(3,.1);assert(state.selected==2,'repeat has a first delay')
tick(1,.06);assert(state.selected==3)
on_stick('left',0,.4);tick(2,.08);assert(state.selected==4,'hold persists above release threshold')
on_stick('left',0,.3);selected=state.selected;tick(10);assert(state.selected==selected)
on_stick('left',0,-.6);assert(state.selected==selected-1)
on_stick('left',0,0);press('dpad_up');press('dpad_up')
n=scans;r=redraws;on_stick('left',0,-1);tick(20)
assert(state.selected==1 and redraws==r and scans==n and #requests==q,'list boundaries are quiet')
for _,index in ipairs({3,4}) do
    on_stick('left',0,0);menu(index);selected=state.selected
    on_stick('left',0,1);assert(state.selected==selected+1,'saved lists support analog selection')
end
on_stick('left',0,0);on_stick('left',-1,0);assert(state.view=='countries')
local countries={};for i=1,100 do countries[i]={name='Country '..i,iso_3166_1='GB',stationcount=i} end
respond(#requests,countries)
local cursor=state.country_cursor;on_stick('left',0,1);tick(12)
assert(state.country_cursor==cursor,'a hold across country view change needs neutral')
on_stick('left',0,0);on_stick('left',0,1);assert(state.country_cursor==cursor+1)
on_stick('left',0,0);on_stick('left',1,0);assert(state.country_offset==100 and state.country_loading)
respond(#requests,countries)
on_stick('left',0,0);on_stick('left',-1,0);assert(state.country_offset==0)
respond(#requests,countries)
on_stick('left',0,0);menu(5);assert(state.view=='settings')
n=scans;local settings_zoom=state.atlas.zoom
on_stick('right',0,0);on_stick('right',0,-1);tick(5)
assert(scans==n and state.atlas.zoom==settings_zoom,'right stick acts only in map mode')
on_stick('left',1,0);near(state.volume,.75)
on_stick('left',0,0);on_stick('left',-1,0);near(state.volume,.7)
on_stick('left',0,0);on_stick('left',0,1);assert(state.settings_cursor==2)
on_stick('left',0,0);on_stick('left',0,1);assert(state.settings_cursor==3)
press('a');assert(state.view=='about');tick(15);press('b');assert(state.view=='explore')
on_stick('left',0,.9);tick(15);assert(state.selected==1,'About/view change clears old nav')
on_stick('left',0,0);menu(9);assert(state.view=='details');press('b');assert(state.view=='explore')

-- All existing digital actions remain usable alongside the optional callback.
reset();press('dpad_down');assert(state.selected==2)
press('dpad_down','repeat');assert(state.selected==3)
press('dpad_up','release');assert(state.selected==3)
press('x');assert(#state.favorites==5);press('x');assert(#state.favorites==6)
press('l1');assert(state.genre==10);press('r1');assert(state.genre==1)
-- Genre changes deliberately clear live search rows; restore a cached page.
reset();press('l2','repeat');near(state.volume,.65);press('r2');near(state.volume,.7)
press('a');assert(#plays==1)
current.state='playing';on_update(0);press('a');assert(pauses[1]==true)
on_update(0);press('a');assert(pauses[2]==false)
press('b');assert(stops==1)
press('y');assert(state.keyboard=='search');keyboard_result=false;on_update(0)
map();u,v=state.atlas.u,state.atlas.v
press('dpad_right');near((state.atlas.u-u)*672,24)
press('dpad_up','repeat');near((state.atlas.v-v)*252,-24)
press('x');assert(state.atlas.zoom==2);press('y');assert(state.atlas.zoom==1)
press('r1');assert(state.map_selected==2);press('l1');assert(state.map_selected==1)
press('a');assert(state.map_loading)
local id=state.map_rows[state.map_selected].stationuuid;respond(#requests,{record(id)})
assert(plays[#plays]=='https://example.invalid/'..id)
press('b');assert(state.focus=='list');press('dpad_left');assert(state.view=='countries')
respond(#requests,countries);press('dpad_down');assert(state.country_cursor==2)
press('a');assert(state.view=='explore' and state.country_code=='GB')
on_destroy();u=state.atlas.u;on_stick('left',1,0);tick(3);near(state.atlas.u,u)
assert(stops==2)
print('Sticks: proportional/finite pan, quiet idle, bounded scans, zoom latch, cancellation, overlays, all views and digital compatibility passed')
