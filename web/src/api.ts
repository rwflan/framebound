/** Thin typed client over the v2 review API. No policy lives here. */
import type {
  ActivityPageDto,
  CapabilitiesDto,
  ChangesDto,
  CompareBundleDto,
  CorrectionsListDto,
  EligibilityDto,
  ExportResultDto,
  IssueDetailDto,
  PacketBundleDto,
  ReferencesDto,
  TaskStatusDto,
} from "./api-types";

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

const deskHeaders = { "X-Framebound-Desk": "1" };
let deskSession: Promise<void> | null = null;
async function ensureDeskSession() {
  if (!deskSession)
    deskSession = fetch("/api/desk/session", {
      method: "POST",
      credentials: "same-origin",
      headers: deskHeaders,
    })
      .then(async (r) => {
        if (!r.ok)
          throw new ApiError(
            r.status,
            "review_unavailable",
            "Local review session could not start.",
          );
      })
      .catch((e) => {
        deskSession = null;
        throw e;
      });
  return deskSession;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    ...deskHeaders,
    ...((init?.headers as Record<string, string>) || {}),
  };
  const write = init?.method && !["GET", "HEAD"].includes(init.method);
  if (write) await ensureDeskSession();
  const hasBody = init?.body !== undefined;
  if (hasBody && !headers["Content-Type"])
    headers["Content-Type"] = "application/json";
  let r: Response;
  try {
    r = await fetch(path, { ...init, headers });
    if (r.status === 401 && write) {
      deskSession = null;
      await ensureDeskSession();
      r = await fetch(path, { ...init, headers });
    }
  } catch (e) {
    throw new ApiError(
      0,
      "network_error",
      `API unreachable (${path}): ${String(e)}. Start: python -m framebound serve --project PATH`,
    );
  }
  if (!r.ok) {
    let code = "http_error",
      detail = "";
    try {
      const body = await r.json();
      code =
        body.code || body.detail
          ? String(body.code || "http_error")
          : "http_error";
      detail = String(body.detail || JSON.stringify(body)).slice(0, 400);
    } catch {
      detail = (await r.text().catch(() => "")).slice(0, 400);
    }
    throw new ApiError(r.status, code, `${r.status} ${code}: ${detail}`);
  }
  return r.json() as Promise<T>;
}

const q = (params: Record<string, string | number | undefined>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params))
    if (v !== undefined) s.set(k, String(v));
  const str = s.toString();
  return str ? `?${str}` : "";
};

export const api = {
  changes: () => req<ChangesDto>("/api/changes"),
  references: () => req<ReferencesDto>("/api/references"),
  approveReferences: (character: string, guide: string, eventId: string) =>
    req<{ ok: boolean }>("/api/references/approve", {
      method: "POST",
      body: JSON.stringify({
        character_revision_id: character,
        motion_guide_id: guide,
        event_id: eventId,
      }),
    }),
  revokeReference: (approvalId: string, eventId: string) =>
    req<{ ok: boolean }>(
      `/api/references/${encodeURIComponent(approvalId)}/revoke`,
      {
        method: "POST",
        body: JSON.stringify({
          event_id: eventId,
          note: "Reference authority revoked from review desk.",
        }),
      },
    ),
  health: () => req<{ ok: boolean; schema_version: string }>("/api/health"),
  project: () =>
    req<{
      summary: Record<string, unknown>;
      projects: { id: string; name: string }[];
    }>("/api/project"),
  packets: () => req<{ packets: Record<string, unknown>[] }>("/api/packets"),
  packet: (id: string) =>
    req<PacketBundleDto>(`/api/packet/${encodeURIComponent(id)}`),
  compare: (base: string, other: string) =>
    req<CompareBundleDto>(`/api/compare${q({ base, other })}`),
  assetUrl: (id: string) => `/api/asset/${encodeURIComponent(id)}`,
  contactSheetUrl: (packetId: string) =>
    `/api/packet/${encodeURIComponent(packetId)}/contact-sheet`,
  previewUrl: (packetId: string) =>
    `/api/previews/${encodeURIComponent(packetId)}.mp4`,
  corrections: (status = "open") =>
    req<CorrectionsListDto>(`/api/corrections${q({ status })}`),
  correctionGet: (taskId: string) =>
    req<TaskStatusDto>(`/api/corrections/${encodeURIComponent(taskId)}`),
  claim: (taskId: string, expectedVersion: number) =>
    req<{
      task_id: string;
      status: string;
      holder: string;
      claim_token: string;
      lease: string;
      version: number;
    }>(`/api/corrections/${encodeURIComponent(taskId)}/claim`, {
      method: "POST",
      body: JSON.stringify({ expected_version: expectedVersion }),
    }),
  issues: (revision?: string, packet?: string) =>
    req<IssueDetailDto[]>(`/api/issues${q({ revision, packet })}`),
  markIssue: (body: Record<string, unknown>) =>
    req<{ event: Record<string, unknown>; task_id: string }>("/api/issues", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  decide: (body: Record<string, unknown>) =>
    req<{ ok: boolean; operation_id: string; revision_id: string | null }>(
      "/api/decisions",
      { method: "POST", body: JSON.stringify(body) },
    ),
  resolveIssue: (eventId: string, body: Record<string, unknown>) =>
    req<{ ok: boolean; resolution_event_id: string }>(
      `/api/issues/${encodeURIComponent(eventId)}/resolve`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  reopenIssue: (eventId: string, body: Record<string, unknown>) =>
    req<{ ok: boolean; task_id: string; status: string; event_id: string }>(
      `/api/issues/${encodeURIComponent(eventId)}/reopen`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  approveMask: (body: {
    issue_event_id: string;
    mask_asset_id: string;
    covered_slots: number[];
  }) =>
    req<Record<string, unknown>>("/api/masks", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  capabilities: () => req<CapabilitiesDto>("/api/capabilities"),
  eligibility: (revisionId: string) =>
    req<EligibilityDto>(`/api/eligibility/${encodeURIComponent(revisionId)}`),
  activity: (since?: string, limit?: number) =>
    req<ActivityPageDto>(`/api/activity${q({ since, limit })}`),
  buildPreview: (packetId: string) =>
    req<Record<string, unknown>>(
      `/api/packet/${encodeURIComponent(packetId)}/preview`,
      { method: "POST" },
    ),
  buildExport: (
    name: string,
    revisions: string[],
    policy: Record<string, unknown>,
  ) =>
    req<ExportResultDto>("/api/exports", {
      method: "POST",
      body: JSON.stringify({ name, revisions, policy }),
    }),
  exportGet: (name: string) =>
    req<ExportResultDto>(`/api/exports/${encodeURIComponent(name)}`),
};
