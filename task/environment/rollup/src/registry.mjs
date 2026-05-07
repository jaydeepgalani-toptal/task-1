import fs from "node:fs";

function requireText(value, label, partnerId) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`registry_invalid partner=${partnerId} field=${label}`);
  }
  return value;
}

function normalizePartner(partner) {
  const settlement = partner.settlement || {};
  const eventIdentity = partner.eventIdentity || "stable-event";
  const postingSequencePath = partner.postingSequencePath;

  if (!["stable-event", "ledger-posting"].includes(eventIdentity)) {
    throw new Error(`registry_invalid partner=${partner.id} field=eventIdentity`);
  }
  if (
    eventIdentity === "ledger-posting" &&
    (typeof postingSequencePath !== "string" || postingSequencePath.trim() === "")
  ) {
    throw new Error(`registry_invalid partner=${partner.id} field=postingSequencePath`);
  }

  return {
    ...partner,
    eventIdentity,
    profile: requireText(partner.profile, "profile", partner.id),
    sourceTsPath: requireText(partner.sourceTsPath, "sourceTsPath", partner.id),
    eventIdPath: requireText(partner.eventIdPath, "eventIdPath", partner.id),
    postingSequencePath,
    accountPath: requireText(partner.accountPath, "accountPath", partner.id),
    settlement: {
      zone: requireText(settlement.zone, "settlement.zone", partner.id),
      cutoffLocal: requireText(settlement.cutoffLocal, "settlement.cutoffLocal", partner.id)
    }
  };
}

export function loadRegistry(registryPath) {
  const registry = JSON.parse(fs.readFileSync(registryPath, "utf8"));
  return {
    ...registry,
    partners: registry.partners.map(normalizePartner)
  };
}

export function enabledPartners(registry, explicitOrder = []) {
  const enabled = registry.partners
    .filter((partner) => partner.enabled)
    .sort((left, right) => left.sortOrder - right.sortOrder);

  if (explicitOrder.length === 0) {
    return enabled;
  }

  const byId = new Map(enabled.map((partner) => [partner.id, partner]));
  const ordered = [];

  for (const partnerId of explicitOrder) {
    if (byId.has(partnerId)) {
      ordered.push(byId.get(partnerId));
      byId.delete(partnerId);
    }
  }

  return [...ordered, ...byId.values()];
}
