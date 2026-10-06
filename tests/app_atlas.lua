local fixtures,next_json={},0
local function copy(v)
 if type(v)~='table' then return v end
 local r={};for k,value in pairs(v) do r[k]=copy(value) end;return r
end
json={encode=function(v) next_json=next_json+1;local k='['..next_json..']';fixtures[k]=copy(v);return k end,
 decode=function(k) assert(fixtures[k],'invalid JSON fixture');return copy(fixtures[k]) end}
package.loaded.atlas_data={schema=1,built_at='2026-10-07',tile_w=672,tile_h=252,
 stations={{'it-rome',41.9,12.5,'IT','Rome Atlas'},{'us-newyork',40.7,-74,'US','New York Atlas'},{'zero',0,0,'GB','Zero Atlas'}}}
local requests,responses,plays,drawn,saved={},{},{},{},{}
local current={state='stopped',error=''}
http={get_async=function(url)requests[#requests+1]=url;return #requests end,
 poll=function()local r=responses;responses={};return r end}
http.get=function()error('blocking HTTP forbidden')end
storage={load=function(k)return saved[k]end,save=function(k,v)saved[k]=copy(v)end}
app={set_idle_fps=function()end,request_redraw=function()end}
screen=setmetatable({draw_text=function(t)drawn[#drawn+1]=t end,draw_display_text=function(t)drawn[#drawn+1]=t end,
 draw_image=function(path)drawn[#drawn+1]=path end},{__index=function()return function()end end})
audio={stream=function(url)plays[#plays+1]=url;current={state='connecting',url=url,error=''}end,
 stream_status=function()return current end,set_stream_volume=function()end,stop_stream=function()end,pause_stream=function()end}
text_input={is_active=function()return false end}
local function press(k)on_input(k,'press')end
local function latest(part)for i=#requests,1,-1 do if requests[i]:find(part,1,true)then return i end end;error('request not found '..part)end
local function respond(id,data)responses[#responses+1]={id=id,ok=true,status=200,body=json.encode(data)};on_update(.1)end
local function render()drawn={};on_render();return table.concat(drawn,'\n')end
local function station(id) return {stationuuid=id,name=id,geo_lat=0,geo_long=0,countrycode='GB',codec='MP3',hls=0,lastcheckok=1,url_resolved='https://example.invalid/'..id}end
dofile('main.lua');on_init()
assert(#plays==0,'launch must never autoplay')
local view=render();assert(view:find('3 locations / 3 countries',1,true));assert(view:find('assets/atlas/z1-0-0.png',1,true))
-- A usable worldwide map exists even while directory requests are offline/loading.
press('dpad_right');assert(render():find('nearby',1,true))
local n=#requests;press('x');press('y');press('dpad_right');press('dpad_left');assert(#requests==n,'pan/zoom must not fetch station pages')
press('a');local stale=latest('/stations/byuuid/');local count=#requests;press('a');assert(#requests==count,'duplicate tune must not create another request')
press('dpad_right');respond(stale,{station('zero')});assert(#plays==0,'late station response must not tune after moving cursor')
press('dpad_left');press('a');respond(latest('/stations/byuuid/'),{false,42,'bad'});assert(#plays==0);assert(render():find('unavailable or unsupported',1,true))
press('a');respond(latest('/stations/byuuid/'),{station('zero')});assert(plays[1]=='https://example.invalid/zero')
-- Cached metadata allows retry without another lookup; pause/resume uses the real player.
current={state='playing',url=plays[1],error=''};on_update(.1);n=#requests;press('a');assert(#requests==n)
press('start');for _=1,9 do press('dpad_down') end;press('a')
assert(saved['frequency.v1'].favorites[1].stationuuid=='zero','map favorite must preserve resolved stream metadata')
press('b');assert(render():find('RIGHT map',1,true))
press('start');press('dpad_down');press('dpad_down');press('a')
assert(render():find('Favorites',1,true))
press('dpad_right');assert(render():find('X/Y',1,true));assert(not render():find('saved records',1,true))
press('b');assert(render():find('Favorites',1,true));on_destroy()
print('Atlas app: offline coverage, no autoplay, async tuning, cancellation, malformed metadata and bounded lookup passed')
