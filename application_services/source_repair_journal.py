"""Shared atomic activation and rollback for declarative source repairs."""


class SourceRepairJournal:
    def activate(self, provider, repair_id):
        with self.store.lock:
            entry = self.store.entry(provider)
            repair = next((r for r in entry.get("repairs", []) if r["id"] == repair_id), None)
            if not repair or repair["confidence"] != "high" or not repair["validation"]["shadow_passed"]:
                raise ValueError("Reparatur ist nicht eindeutig validiert")
            if repair["state"] != "available" or repair["previous_profile"] != self.profile(provider):
                raise ValueError("Reparatur ist nicht mehr aktuell; erneut prüfen")
            if entry.get("active_repair"):
                raise ValueError("Aktive Reparatur zuerst zurücksetzen")
            repair["state"] = "active"
            repair["activated_at"] = self.store.clock()
            self.store.update(provider, profile=self.validate_profile(provider, repair["profile"]), active_repair=repair_id,
                              repairs=entry["repairs"], repair_failures=[])
            self.store.record(provider, {"event": "repair_activated", "repair_id": repair_id, "reason": "shadow_validation_passed"})

    def rollback(self, provider, repair_id, reason="administrator"):
        with self.store.lock:
            entry = self.store.entry(provider)
            if entry.get("active_repair") != repair_id:
                raise ValueError("Reparatur ist nicht aktiv")
            repair = next(r for r in entry["repairs"] if r["id"] == repair_id)
            repair["state"] = "rolled_back"
            self.store.update(provider, profile=repair["previous_profile"], active_repair=None, repairs=entry["repairs"], repair_failures=[])
            self.store.record(provider, {"event": "repair_rolled_back", "repair_id": repair_id, "reason": reason})
