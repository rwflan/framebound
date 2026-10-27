/** Thin client over the v2 review API. No policy lives here. */
export const H = { type: 'reviewer', id: 'desk-user' };

async function req(path: string, init?: RequestInit) {
  const r = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-Actor-Type': H.type,
      'X-Actor-Id': H.id,
      ...(init?.headers || {}),
    },
  });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`${r.status} ${r.statusText}: ${body.slice(0, 300)}`);
  }
  return r.json();
}

export const api = {
  health: () => req('/api/health'),
  project: () => req('/api/project'),
  packets: () => req('/api/packets'),
  packet: (id: string) => req(`/api/packet/${id}`),
  assetUrl: (id: string) => `/api/asset/${id}`,
  markIssue: (body: object) => req('/api/issues', { method: 'POST', body: JSON.stringify(body) }),
  decide: (body: object) => req('/api/decisions', { method: 'POST', body: JSON.stringify(body) }),
  resolveIssue: (eventId: string, body: object) =>
    req(`/api/issues/${eventId}/resolve`, { method: 'POST', body: JSON.stringify(body) }),
  corrections: () => req('/api/corrections'),
};
