import test from 'node:test';
import assert from 'node:assert/strict';
import {createSeriesStatus} from '../../web/js/features/media-details/series-status.js';

function label(counts) {
  const text={textContent:''};
  const badge={className:'',classList:{add(){}},querySelector:()=>text};
  const status=createSeriesStatus({},badge);
  status.badge({jellyfin_configured:true,jellyfin_available:true,
    season_episode_counts:counts,
    seasons:[{season:1,episodes:Array.from({length:10},()=>({in_jellyfin:true}))}],
  });
  return text.textContent;
}

test('a missing known season cannot be called complete in Jellyfin',()=>{
  assert.equal(label({'1':10,'2':3}),'10 Episoden in Jellyfin');
});
test('missing episodes in an existing season cannot be called complete',()=>{
  assert.equal(label({'1':12}),'10 Episoden in Jellyfin');
});
test('a genuinely complete known inventory retains its badge',()=>{
  assert.equal(label({'1':10}),'Vollständig in Jellyfin');
});
