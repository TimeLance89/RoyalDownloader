import assert from "node:assert/strict";
import test from "node:test";
import { seasonalEventAt, createSeasonalEvents } from "../../web/js/features/home/seasonal-events.js";

test("Halloween runs annually October 28–31 using local calendar boundaries", () => {
  for (const year of [2026, 2027, 2028]) {
    for (const [day, stage] of [[28,1], [29,2], [30,3], [31,4]]) {
      assert.deepEqual(seasonalEventAt(new Date(year,9,day,0,0)), { id:"halloween", stage });
      assert.deepEqual(seasonalEventAt(new Date(year,9,day,23,59,59)), { id:"halloween", stage });
    }
    for (const date of [new Date(year,9,27,23,59,59), new Date(year,10,1,0,0), new Date(year,0,30)]) {
      assert.equal(seasonalEventAt(date), null);
    }
  }
});

function service(client) {
  return createSeasonalEvents({ ownerDocument:{defaultView:{}}, dataset:{}, querySelector:()=>null }, {client});
}

test("a stale configuration read cannot undo the saved off preference", async () => {
  let resolve;
  const events = service({get:()=>new Promise(done=>{resolve=done;}), post:async()=>({enabled:false})});
  const read = events.load();
  await events.save(false);
  resolve({enabled:true});
  await read;
  assert.equal(events.enabled,false);
});

test("failed persistence retains the last confirmed preference", async () => {
  const events = service({get:async()=>({enabled:false}),post:async()=>{throw new Error("disk full");}});
  await events.load();
  await assert.rejects(events.save(true), /disk full/);
  assert.equal(events.enabled,false);
});

test("cancelled configuration reads cannot change the current preference", async () => {
  let resolve;
  const events=service({get:()=>new Promise(done=>{resolve=done;})});
  const controller = new AbortController();
  const read=events.load({signal:controller.signal});
  controller.abort(); resolve({enabled:true}); await read;
  assert.equal(events.enabled,null);
});
