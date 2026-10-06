local Atlas=require('atlas')
local rows={{'italy',41.9,12.5,'IT','Rome'},{'america',40.7,-74,'US','New York'},
 {'zero',0,0,'GB','Zero'},{'bad',91,0,'GB','Invalid'},{'nan',0/0,1,'GB','Invalid'},
 {'italy',41.9,12.5,'IT','Duplicate'}}
local data={schema=1,built_at='2026-10-07',tile_w=672,tile_h=252,stations=rows}
local a=Atlas.new(data)
assert(#a.records==3 and a.countries==3)
assert(not Atlas.new({schema=0}).records[1]);assert(#Atlas.new({schema=0}):tiles()==0)
a:set_cursor(41.9,12.5);assert(a:nearest(100)[1].stationuuid=='italy')
assert(a:country('IT') and a.zoom==4);assert(not a:country('ZZ'))
local coords={{0,0},{90,180},{-90,-180},{41.9,12.5},{-60,160}}
for _,zoom in ipairs({1,2,4,8}) do
 for _,p in ipairs(coords) do
  a.zoom=zoom;a:set_cursor(p[1],p[2]);local tiles=a:tiles();assert(#tiles<=4)
  local area=0
  for _,t in ipairs(tiles) do
   local o=t.opts;area=area+o.w*o.h
   assert(o.w>0 and o.h>0 and o.src_x>=0 and o.src_y>=0 and o.src_x+o.src_w<=672 and o.src_y+o.src_h<=252)
   assert(t.x>=24 and t.y>=150 and t.x+o.w<=696 and t.y+o.h<=402)
  end
  assert(area==672*252,'tiles must cover the viewport exactly without overlap')
  local x,y=a:cursor();assert(x and x>=24 and x<696 and y>=150 and y<402)
 end
end
local many={};for i=1,250 do many[i]={string.format('%04d',i),41.9,12.5,'IT','Station '..i} end
a=Atlas.new({schema=1,tile_w=672,tile_h=252,stations=many});a:set_cursor(41.9,12.5)
local nearby=a:nearest(100);assert(#nearby==100);assert(nearby[1].stationuuid=='0001' and nearby[100].stationuuid=='0100')
a:magnify(1);a:magnify(1);a:magnify(1);a:magnify(1);assert(a.zoom==8)
for i=1,5 do a:magnify(-1) end;assert(a.zoom==1)
a:country('');assert(a.zoom==1 and a.u==0.5 and a.v==0.5)
print('Atlas: global index, Italy selection, nearest ordering, 1/2/4/8x tiles and finite bounds passed')

-- Pixel pan preserves fractional input, screen speed at every zoom, y sign,
-- and clamps coordinates without reporting a change at a stationary edge.
for _,zoom in ipairs({1,2,4,8}) do
 a.zoom=zoom;a:set_cursor(0,0)
 local u,v=a.u,a.v
 assert(not a:pan_pixels(.1,.1),'fractional input below a pixel must stay quiet')
 assert(a:pan_pixels(17.9,-9.1))
 assert(math.abs((a.u-u)*672*zoom-18)<1e-9)
 assert(math.abs((a.v-v)*252*zoom+9)<1e-9,'negative y must move north')
 u,v=a.u,a.v
 for _,p in ipairs({{0/0,0},{math.huge,0},{0,-math.huge},{'1',0}}) do
  assert(not a:pan_pixels(p[1],p[2]));assert(a.u==u and a.v==v)
 end
 a:set_cursor(-90,180);u,v=a.u,a.v
 assert(not a:pan_pixels(24,24));assert(a.u==u and a.v==v)
 assert(a:move('dpad_left') and a:move('dpad_up'))
 assert(not a:move('unknown'))
end
a.zoom=8;assert(not a:magnify(1));assert(a:magnify(-1) and a.zoom==4)
a.zoom=1;assert(not a:magnify(-1));assert(a:magnify(1) and a.zoom==2)

local actual=Atlas.new()
assert(#actual.records>10000 and actual.countries>150,'worldwide asset coverage must not regress to a single directory page')
assert(actual:country('IT'),'Italy must have actual coordinates')
local italy=0;for _,r in ipairs(actual.records) do if r[4]=='IT' then italy=italy+1 end end
assert(italy>=100,'Italy coverage missing')
for _,p in ipairs({{41.9,12.5},{40.7,-74},{-33.8,151.2},{35.7,139.7}}) do
 actual:set_cursor(p[1],p[2]);actual.zoom=8
 assert(#actual:nearest(100)==100 and #actual:tiles()<=4)
end
