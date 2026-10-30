// Count only blocking time inside the measured render/interaction window.
function observeTasks(tasks, start, end) {
  const overlapping = tasks.filter(task => task.start < end && task.start + task.duration > start);
  return {
    longTasks: overlapping.length,
    tbtMs: overlapping.reduce((sum, task) => sum + Math.max(0,
      Math.min(end, task.start + task.duration) - Math.max(start, task.start + 50)), 0),
  };
}
module.exports = { observeTasks };
