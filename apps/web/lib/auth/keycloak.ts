"use client";

import Keycloak from "keycloak-js";
import { KEYCLOAK_CLIENT_ID, KEYCLOAK_REALM, KEYCLOAK_URL } from "./config";

/**
 * Single keycloak-js instance for the whole app. keycloak-js may only be
 * `init()`-ed once, so the instance is created lazily and shared. Access/refresh
 * tokens live only in this in-memory object — never in localStorage (ADR-019).
 */

let instance: Keycloak | null = null;

export function getKeycloak(): Keycloak {
  if (instance === null) {
    instance = new Keycloak({
      url: KEYCLOAK_URL,
      realm: KEYCLOAK_REALM,
      clientId: KEYCLOAK_CLIENT_ID,
    });
  }
  return instance;
}
