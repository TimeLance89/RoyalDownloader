import test from 'node:test';
import assert from 'node:assert/strict';
import { createMovieStream } from '../../web/js/features/media-details/movie-stream.js';

test('seeking keeps one negotiated session and closing releases it', async () => {
  const calls = [], video = {readyState: 1,currentTime: 0,canPlayType:()=> 'probably',pause(){},load(){},removeAttribute(){},addEventListener(){},removeEventListener(){}};
  const client = {post:async url=>{calls.push(url);return {id:'session',mode:'direct',url:'/stream'};},delete:async url=>calls.push(url)};
  const stream=createMovieStream(video,{document:{},client,prepared(){},failed(){assert.fail('unexpected playback error');}});
  await stream.open('item_id=one',120,false);
  stream.seek(600); assert.equal(video.currentTime,600);
  stream.seek(40); assert.equal(video.currentTime,40);
  assert.equal(calls.filter(x=>x.includes('/movies/session')).length,1);
  stream.close(); assert.ok(calls.includes('/api/media-center/playback/session'));
});

test('late negotiation cannot restart a closed player', async () => {
  let resolve, released;
  const video={pause(){},load(){},removeAttribute(){}};
  const client={post:()=>new Promise(r=>resolve=r),delete:async url=>released=url};
  const stream=createMovieStream(video,{document:{},client,prepared(){assert.fail('closed session prepared');},failed(){assert.fail('closed session failed');}});
  const opening=stream.open('item_id=one',0,false);stream.close();
  resolve({id:'late',mode:'direct'});await opening;
  assert.equal(released,'/api/media-center/playback/late');
});

test('stalled stream falls back once without saving a reset position', async () => {
  const listeners=new Map(), calls=[], starts=[];
  const video={readyState:1,currentTime:600,paused:false,canPlayType:()=> 'probably',pause(){},load(){},play:async()=>{},removeAttribute(){},addEventListener:(n,fn)=>listeners.set(n,fn),removeEventListener:n=>listeners.delete(n)};
  const original=globalThis.setTimeout;
  let timer;
  globalThis.setTimeout=fn=>{timer=fn;return 1;};
  const client={post:async url=>{calls.push(url);return {id:String(calls.length),mode:'direct',url:'/stream'};},delete:async()=>{}};
  const stream=createMovieStream(video,{document:{},client,starting:p=>starts.push(p),prepared(){},failed(){assert.fail('unexpected error');}});
  try {
    await stream.open('item_id=one',120,false);
    listeners.get('waiting')();timer();
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(calls.length,2);
    assert.match(calls[1],/force_transcode=true/);
    assert.deepEqual(starts,[120,600]);
    listeners.get('waiting')();
    assert.equal(calls.length,2);
  } finally {stream.close();globalThis.setTimeout=original;}
});

test('HLS uses MSE even when browser advertises native HLS', async () => {
  let attached=false,source;
  class Hls {
    static isSupported=()=>true;
    static Events={ERROR:'error'};
    constructor(){} on(){} loadSource(url){source=url;} attachMedia(){attached=true;} destroy(){}
  }
  const video={canPlayType:()=> 'probably',pause(){},load(){},removeAttribute(){},addEventListener(){},removeEventListener(){}};
  const stream=createMovieStream(video,{document:{defaultView:{Hls}},client:{post:async()=>({id:'one',mode:'hls',url:'/manifest'}),delete:async()=>{}},prepared(){},failed(){assert.fail('unexpected failure');}});
  await stream.open('item_id=one',120,false);
  assert.equal(attached,true);assert.equal(source,'/manifest');assert.equal(video.src,undefined);
  stream.close();
});

test('unbuffered HLS seeks prime earlier keyframes then land at requested time', async () => {
  const handlers=new Map(), requests=[], loads=[];
  let instance, range=[0,0], plays=0;
  class Hls {
    static isSupported=()=>true;
    static Events={ERROR:'error',FRAG_BUFFERED:'buffered'};
    constructor(config){this.config=config;instance=this;} on(n,fn){handlers.set(n,fn);} loadSource(){} attachMedia(){} destroy(){} stopLoad(){} startLoad(t){loads.push(t);}
  }
  const video={readyState:1,currentTime:0,paused:true,buffered:{length:1,start:()=>range[0],end:()=>range[1]},pause(){this.paused=true;},play:async()=>{plays++;video.paused=false;},load(){},removeAttribute(){},addEventListener(){},removeEventListener(){}};
  const stream=createMovieStream(video,{document:{defaultView:{Hls}},client:{post:async u=>{requests.push(u);return {id:'one',mode:'hls',url:'/hls'};},delete:async()=>{}},prepared(){},failed(){assert.fail('unexpected error');}});
  try {
    await stream.open('item_id=one',120,true);
    assert.equal(instance.config.startPosition,102);assert.equal(plays,0);assert.equal(stream.pendingPosition,120);
    range=[110,135];handlers.get('buffered')();
    assert.equal(video.currentTime,120);assert.equal(plays,1);assert.equal(stream.pendingPosition,null);
    stream.seek(600);await new Promise(resolve=>setImmediate(resolve));assert.equal(instance.config.startPosition,582);assert.equal(stream.pendingPosition,600);
    range=[590,610];handlers.get('buffered')();assert.equal(video.currentTime,600);assert.equal(plays,2);
    assert.equal(requests.filter(u=>u.includes('/movies/session')).length,1);
  } finally {stream.close();}
});

test('permission-denied heartbeat stops and releases the stream', async () => {
  const calls = [], errors = [];
  const video = {pause(){},load(){},removeAttribute(){},addEventListener(){},removeEventListener(){}};
  const client = { post: async url => {
    if (url.endsWith('/heartbeat')) throw {status:403};
    return {id:'owned',mode:'direct',url:'/stream'};
  }, delete: async url => calls.push(url) };
  const stream = createMovieStream(video,{document:{},client,prepared(){},failed:e=>errors.push(e.status)});
  await stream.open('item_id=one',0,false);
  stream.heartbeat();
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(errors,[403]);
  assert.equal(stream.managesErrors,false);
  assert.ok(calls.includes('/api/media-center/playback/owned'));
});
