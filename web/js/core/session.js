import { api } from "./api.js";

export async function logout() {
  try { await api.post("/api/auth/logout"); }
  catch (error) { console.warn("Abmeldung fehlgeschlagen:", error); }
  location.reload();
}
