const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8010";

async function req(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    ...opts,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

async function upload(path, formData) {
  const res = await fetch(`${BASE}${path}`, { method: "POST", body: formData, cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const api = {
  base: BASE,
  get: (p) => req(p),
  post: (p, body) => req(p, { method: "POST", body: JSON.stringify(body || {}) }),
  upload,
};
