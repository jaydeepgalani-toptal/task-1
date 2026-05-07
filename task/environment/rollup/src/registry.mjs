import fs from "node:fs";

const REQUIRED_PARTNER_FIELDS = [
  "partnerId",
  "baseUrl",
  "eventsPath",
  "reportPath",
  "currency",
  "accountField",
  "amountField",
  "timestampField",
  "referenceField",
  "settlementCutoff"
];

function requireText(value, label, partnerId) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`registry_invalid partner=${partnerId || "unknown"} field=${label}`);
  }
  return value;
}

function normalizePartner(partner) {
  for (const field of REQUIRED_PARTNER_FIELDS) {
    requireText(partner[field], field, partner.partnerId);
  }

  return {
    ...partner,
    enabled: partner.enabled !== false
  };
}

export function loadRegistry(registryPath) {
  const registry = JSON.parse(fs.readFileSync(registryPath, "utf8"));
  return {
    partners: registry.partners.map(normalizePartner)
  };
}

export function enabledPartners(registry) {
  return registry.partners.filter((partner) => partner.enabled);
}
