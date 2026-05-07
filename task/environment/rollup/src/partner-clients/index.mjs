import { getNormalizationContext } from "../payload-access.mjs";
import * as alpha from "./alpha.mjs";
import * as beta from "./beta.mjs";
import * as delta from "./delta.mjs";
import * as epsilon from "./epsilon.mjs";
import * as gamma from "./gamma.mjs";

const clients = {
  alpha,
  beta,
  gamma,
  delta,
  epsilon
};

export async function fetchNormalizedPartnerEvents(partner) {
  const client = clients[partner.id];
  if (!client) {
    throw new Error(`unknown_partner ${partner.id}`);
  }

  const context = getNormalizationContext(partner);
  const payload = await client.fetchEvents(partner);
  return {
    fetchedCount: payload.events.length,
    events: payload.events.map((raw) => client.normalizeEvent(raw, partner, context))
  };
}
