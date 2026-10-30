import assert from "node:assert/strict";
import test from "node:test";
import { createHalloweenFlash } from "../../web/js/features/home/halloween-flash.js";

function fixture(stage = 4) {
  const root = {dataset:{}};
  const motion = Object.assign(new EventTarget(), {matches:false});
  const timers = [], removals = [];
  const state = {active:true,stage};
  const scope = {
    active:true,
    timeout(callback,delay) {
      const timer = {delay,active:true,run(){this.active=false;callback();}};
      timers.push(timer);
      return ()=>{timer.active=false;};
    },
    listen(target,name,callback) {
      target.addEventListener(name,callback);
      removals.push(()=>target.removeEventListener(name,callback));
    },
    dispose(){this.active=false;timers.forEach(t=>{t.active=false;});removals.forEach(fn=>fn());},
  };
  const storm = createHalloweenFlash(root,{getState:()=>state,scopeFactory:()=>scope,motion});
  return {root,motion,timers,state,storm};
}

test("one flash every ten seconds without overlapping timers",()=>{
  const f=fixture();
  f.storm.sync();f.storm.sync();
  assert.equal(f.timers.filter(t=>t.active).length,1);
  assert.equal(f.timers[0].delay,1800);
  f.timers[0].run();
  assert.equal(f.root.dataset.eventLightning,"true");
  assert.equal(f.timers[1].delay,360);
  f.storm.sync();assert.equal(f.timers.length,2);
  f.timers[1].run();
  assert.equal(f.root.dataset.eventLightning,undefined);
  assert.equal(f.timers[2].delay,9640);
  assert.equal(f.timers.filter(t=>t.active).length,1);
  f.storm.dispose();
});

test("all Halloween days use the same regular cadence",()=>{
  for(const stage of [1,2,3,4]){
    const f=fixture(stage);f.storm.sync();f.timers[0].run();f.timers[1].run();
    assert.equal(f.timers[2].delay + f.timers[1].delay,10000);f.storm.dispose();
  }
});

test("reduced motion cancels a live strike and prevents new flashes",()=>{
  const f=fixture();f.storm.sync();f.timers[0].run();
  f.motion.matches=true;f.motion.dispatchEvent(new Event("change"));
  assert.equal(f.root.dataset.eventLightning,undefined);
  assert.equal(f.timers.filter(t=>t.active).length,0);
  f.storm.sync();assert.equal(f.timers.filter(t=>t.active).length,0);
  f.motion.matches=false;f.motion.dispatchEvent(new Event("change"));
  assert.equal(f.timers.filter(t=>t.active).length,1);f.storm.dispose();
});

test("leaving Home, hiding the browser, disabling events and disposal cancel all storm work",()=>{
  const f=fixture();f.storm.sync();f.timers[0].run();
  f.state.active=false;f.storm.sync();
  assert.equal(f.root.dataset.eventLightning,undefined);
  assert.equal(f.timers.filter(t=>t.active).length,0);
  f.state.active=true;f.storm.sync();f.storm.dispose();
  f.storm.sync();assert.equal(f.timers.filter(t=>t.active).length,0);
});
