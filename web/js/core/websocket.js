import { appStore } from "./store.js";
import { reportError } from "./errors.js";

export function createWebSocketManager({
  createSocket = url => new WebSocket(url),
  url = () => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`,
  status = value => appStore.set({ connection: value }),
  random = Math.random,
} = {}) {
  let socket = null, timer = null, attempt = 0, generation = 0, enabled = false;
  const subscribers = new Map();
  const emit = (topic, data) => {
    for (const listener of [...(subscribers.get(topic) || [])]) {
      try { Promise.resolve(listener(data)).catch(reportError); } catch (error) { reportError(error); }
    }
  };
  const schedule = () => {
    if (!enabled || timer) return;
    status("reconnecting");
    const delay = Math.min(30_000, 2_000 * 2 ** Math.min(attempt++, 4)) * (0.8 + random() * 0.4);
    timer = setTimeout(() => { timer = null; open(); }, delay);
  };
  const open = () => {
    if (!enabled || socket) return;
    const token = ++generation;
    status("connecting");
    let connection;
    try { connection = createSocket(url()); }
    catch (error) { reportError(error); schedule(); return; }
    socket = connection;
    const current = () => enabled && token === generation && socket === connection;
    connection.onopen = () => {
      if (!current()) return;
      attempt = 0;
      status("connected");
      emit("connection.open", { generation: token, isCurrent: current });
    };
    connection.onmessage = event => {
      if (!current()) return;
      let message;
      try { message = JSON.parse(event.data); }
      catch { return; }
      if (!message || typeof message.type !== "string") return;
      emit(message.type, message);
    };
    connection.onerror = () => { if (current()) connection.close(); };
    connection.onclose = event => {
      if (!current()) return;
      socket = null;
      if (event.code === 1008) {
        enabled = false;
        status("auth_failed");
        emit("session.expired", event);
      } else schedule();
    };
  };
  return {
    connect() { enabled = true; if (!timer) open(); },
    disconnect() {
      enabled = false;
      ++generation;
      clearTimeout(timer); timer = null;
      const previous = socket; socket = null;
      previous?.close();
      status("disconnected");
    },
    subscribe(topic, listener) {
      if (!subscribers.has(topic)) subscribers.set(topic, new Set());
      const set = subscribers.get(topic);
      set.add(listener);
      return () => {
        if (!set.delete(listener)) return;
        if (!set.size) subscribers.delete(topic);
      };
    },
  };
}

// /ws has no application ping/pong contract; protocol heartbeats remain server-owned.
export const websocket = createWebSocketManager();
