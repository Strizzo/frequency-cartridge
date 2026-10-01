local station = require('station')
local directory = require('directory')
local function record(extra)
    local r = {stationuuid='one', name='Radio', url_resolved='https://radio.example/live', codec='MP3', lastcheckok=1}
    for k,v in pairs(extra or {}) do r[k]=v end
    return r
end
assert(station.normalize(record()).url_resolved == 'https://radio.example/live')
for _, codec in ipairs({'OPUS', 'HE-AAC', 'AAC+', ''}) do
    assert(station.normalize(record({codec=codec})) == nil, 'unsupported codec must be omitted')
end
for _, url in ipairs({'file:///etc/passwd', 'https://radio.example/list.m3u8', 'https://radio.example/list.pls'}) do
    assert(station.normalize(record({url_resolved=url})) == nil, 'unsafe/playlist URL accepted')
end
assert(station.normalize({stationuuid='one',url='https://radio.example/live',codec='MP3'}) == nil, 'unresolved URL fallback')
assert(station.normalize(record({hls=1})) == nil)
assert(station.normalize(record({lastcheckok=0})) == nil)
local custom=station.normalize({url_resolved='https://radio.example/custom'},true)
assert(custom.custom and custom.stationuuid=='custom:https://radio.example/custom')
assert(#station.list({record(),record(),record({stationuuid='two'})})==2)
assert(#station.list({record(),record({stationuuid='two'})},1)==1)
local zero=station.normalize(record({geo_lat=0,geo_long=0}))
local x,y=station.project(zero)
assert(x==360 and y==276)
assert(station.project(station.normalize(record({geo_lat=91,geo_long=0}))) == nil)
assert(station.project(station.normalize(record({geo_lat=0}))) == nil)
assert(station.text('ééé',5)=='éé', 'UTF-8 boundary must survive truncation')
assert(directory.valid_host('DE1.API.RADIO-BROWSER.INFO.')=='de1.api.radio-browser.info')
for _,h in ipairs({'evil.example', 'api.radio-browser.info.evil.example', '-bad.radio-browser.info', 'a..radio-browser.info'}) do
    assert(directory.valid_host(h)==nil, 'invalid directory host accepted')
end
assert(directory.encode('café &')=='caf%C3%A9%20%26')
local callbacks=0
http={get_async=function() return 1 end,poll=function() return {} end}
local d=directory.new()
d:request('https://example.invalid',function(r,e) assert(r==nil and e=='Request timed out');callbacks=callbacks+1 end)
d:poll(15)
d:poll(15)
assert(callbacks==1, 'timeout must complete a request once')
print('Frequency: stream filtering, geographic data, UTF-8, mirror validation, request timeout passed')
