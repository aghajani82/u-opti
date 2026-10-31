"use strict";
// Disposable HTTPS Passkey laboratory only. No Panel/Broker/FRP endpoints.
const $ = (id) => document.getElementById(id);
const expected = "https://passkey-lab.test";
let csrf = null;

function decodeBase64Url(encoded) {
  if (typeof encoded !== "string" || !/^[A-Za-z0-9_-]+={0,2}$/.test(encoded)) {
    throw Error("invalid binary option");
  }
  const s = encoded.replace(/-/g, "+").replace(/_/g, "/");
  const bytes = atob(s + "=".repeat((4 - s.length % 4) % 4));
  return Uint8Array.from(bytes, (x) => x.charCodeAt(0));
}
function encodeBase64Url(value) {
  const arr = new Uint8Array(value);
  let s = "";
  for (let i = 0; i < arr.length; i++) s += String.fromCharCode(arr[i]);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
}
function creationOptions(options) {
  if (!options || !options.publicKey) throw Error("missing creation options");
  const p = options.publicKey;
  p.challenge = decodeBase64Url(p.challenge);
  p.user.id = decodeBase64Url(p.user.id);
  for (const x of p.excludeCredentials || []) x.id = decodeBase64Url(x.id);
  return {publicKey:p};
}
function requestOptions(options) {
  if (!options || !options.publicKey) throw Error("missing request options");
  const p = options.publicKey;
  p.challenge = decodeBase64Url(p.challenge);
  for (const x of p.allowCredentials || []) x.id = decodeBase64Url(x.id);
  return {publicKey:p};
}
function webAuthnJSON(credential, kind) {
  const data = credential.response;
  const response = {
    clientDataJSON: encodeBase64Url(data.clientDataJSON)
  };
  if (kind === "register") {
    response.attestationObject = encodeBase64Url(data.attestationObject);
    if (typeof data.getTransports === "function") {
      response.transports = data.getTransports();
    }
  } else {
    response.authenticatorData = encodeBase64Url(data.authenticatorData);
    response.signature = encodeBase64Url(data.signature);
    response.userHandle = data.userHandle ? encodeBase64Url(data.userHandle) : null;
  }
  return {
    id: credential.id, rawId: encodeBase64Url(credential.rawId),
    type: credential.type, response,
    clientExtensionResults: credential.getClientExtensionResults()
  };
}
async function getStatus() {
  const r = await fetch("/api/status", {cache:"no-store"});
  if (!r.ok) throw Error("lab status unavailable");
  const obj = await r.json();
  csrf = obj.csrf;
  $("status").textContent =
    "Registered: " + obj.registered_credentials +
    " | Signed verifications: " + obj.verified_sign_ins +
    " | Grant: " + obj.grant_writer +
    " | Hardware independence: " + obj.independent_physical_devices;
}
async function api(path, body) {
  if (!csrf) throw Error("CSRF token missing");
  const response = await fetch(path, {
    method:"POST", cache:"no-store", credentials:"omit",
    headers: {"Content-Type":"application/json", "X-Lab-CSRF":csrf},
    body:JSON.stringify(body)
  });
  if (!response.ok) throw Error("Lab held the request (" + response.status + ")");
  return response.json();
}
async function flow(kind) {
  for (const btn of ["primary","backup","signin"]) $(btn).disabled = true;
  try {
    if (!window.isSecureContext || location.origin !== expected) {
      throw Error("trusted disposable HTTPS Origin required");
    }
    if (!window.PublicKeyCredential || !navigator.credentials) {
      throw Error("WebAuthn API unavailable in browser");
    }
    const begin = await api("/api/" + kind + "/start",{});
    $("status").textContent = "Waiting for browser authenticator prompt…";
    const credential = kind === "register"
      ? await navigator.credentials.create(creationOptions(begin.options))
      : await navigator.credentials.get(requestOptions(begin.options));
    if (!credential) throw Error("no authenticator response");
    const done = await api("/api/" + kind + "/finish",{
      ceremony:begin.ceremony,
      response:webAuthnJSON(credential,kind)
    });
    $("status").textContent = done.status + " — test-only; no grant or route changes.";
    await getStatus();
  } catch (err) {
    // Display only a generic browser exception name; never report private
    // authenticator values, challenge JSON or signed assertions.
    $("status").textContent = "HOLD: " + (err && err.name ? err.name : "error");
  } finally {
    for (const btn of ["primary","backup","signin"]) $(btn).disabled = false;
  }
}
function setup() {
  const ready=location.origin===expected && window.isSecureContext &&
    !!window.PublicKeyCredential && !!navigator.credentials;
  $("readiness").textContent = ready
    ? "WebAuthn API detected on trusted lab origin; physical UV not yet tested."
    : "HOLD: use the trusted https://passkey-lab.test Origin in a compatible browser.";
  $("primary").onclick=() => flow("register");
  $("backup").onclick=() => flow("register");
  $("signin").onclick=() => flow("authenticate");
  $("refresh").onclick=() => getStatus().catch(() => {
    $("status").textContent = "HOLD: local lab unavailable";
  });
  getStatus().catch(() => {
    $("status").textContent = "HOLD: local lab unavailable";
  });
}
document.addEventListener("DOMContentLoaded",setup);
