const { test } = require('node:test');
const assert = require('node:assert/strict');
const { observeTasks } = require('./performance-observation.cjs');

test('startup and later work cannot inflate the measured scenario', () => {
  assert.deepEqual(observeTasks([
    {start:0,duration:800}, {start:1100,duration:90}, {start:2100,duration:300},
  ],1000,2000),{longTasks:1,tbtMs:40});
});
test('tasks overlapping a measurement boundary count only blocking time inside it', () => {
  assert.deepEqual(observeTasks([
    {start:900,duration:150}, {start:1950,duration:200},
  ],1000,2025),{longTasks:2,tbtMs:75});
});
test('short work and an empty window have zero blocking time', () => {
  assert.deepEqual(observeTasks([{start:1100,duration:40}],1000,2000),{longTasks:1,tbtMs:0});
  assert.deepEqual(observeTasks([],1000,2000),{longTasks:0,tbtMs:0});
});
