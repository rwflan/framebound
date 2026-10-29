import type {
  ActivityEventDto,
  EvalResultDto,
  IssueDetailDto,
  PacketBundleDto,
  ReferencesDto,
} from "./api-types";
export type Bundle = PacketBundleDto;
export const revisionId = (b: Bundle) => String(b.revision.id);
export const packetId = (b: Bundle) => String(b.packet.id);
export const actionName = (b: Bundle) =>
  String((b.contract.action as { name?: string })?.name || revisionId(b));
export const scopeSlot = (r: EvalResultDto) =>
  /^slot (\d+)$/.test(r.scope) ? Number(r.scope.slice(5)) : null;
export const valueLabel = (r: EvalResultDto) =>
  r.observed_value == null
    ? "—"
    : typeof r.observed_value === "number"
      ? r.units === "fraction"
        ? (r.observed_value * 100).toFixed(1) + "%"
        : Number(r.observed_value.toFixed(2)) +
          (r.units === "native_px" || r.units === "pixels" ? " px" : "")
      : r.observed_value;
export const boundLabel = (r: EvalResultDto) =>
  r.expected_interval?.length === 2
    ? r.expected_interval
        .map((v) =>
          r.units === "fraction" ? Math.round(v * 100) + "%" : String(v),
        )
        .join("–")
    : r.outcome === "unmeasured"
      ? "Unmeasured"
      : "—";
export function projectId(b: Bundle, refs: ReferencesDto | null): string {
  return (
    refs?.character_revisions.find(
      (c) => c.id === b.contract.character_revision_id,
    )?.project_id || "unassigned"
  );
}
export function frameIssues(
  issues: IssueDetailDto[],
  b: Bundle,
  first: number,
  last: number,
) {
  const related = new Set([
    revisionId(b),
    String(b.packet.comparison_revision_id || ""),
  ]);
  return issues
    .filter(
      (i) =>
        related.has(i.clip_revision_id) &&
        (!i.frame_range ||
          (i.frame_range[0] <= last && i.frame_range[1] >= first)),
    )
    .sort(
      (a, z) =>
        Number(a.task_status === "resolved") -
        Number(z.task_status === "resolved"),
    );
}
export function needsReview(b: Bundle, issues: IssueDetailDto[]) {
  return (
    b.evaluation.technical_status !== "pass" ||
    b.evaluation.coverage_status !== "complete" ||
    b.current_decision.acceptance !== "approved" ||
    issues.some(
      (i) =>
        i.clip_revision_id === revisionId(b) &&
        !["resolved", "cancelled"].includes(i.task_status || "open"),
    )
  );
}
export function priority(b: Bundle, issues: IssueDetailDto[]) {
  if (
    issues.some(
      (i) =>
        i.clip_revision_id === revisionId(b) &&
        !["resolved", "cancelled"].includes(i.task_status || "open"),
    )
  )
    return 0;
  if (
    b.evaluation.technical_status === "incomplete" ||
    b.evaluation.coverage_status !== "complete"
  )
    return 1;
  if (b.evaluation.technical_status !== "pass") return 2;
  return 3;
}
export type DeskEvent = {
  id: string;
  at: string;
  title: string;
  actor: string;
  source: "framework" | "human";
  bundle?: Bundle;
  review?: ActivityEventDto;
  checks?: EvalResultDto[];
};
export function chronology(
  bundles: Bundle[],
  reviews: ActivityEventDto[],
): DeskEvent[] {
  const events = new Map<string, DeskEvent>();
  bundles.forEach((b) => {
    for (const [kind, raw, title] of [
      ["revision", b.revision, "Revision created"],
      ["evaluation", b.evaluation, "Evaluation recorded"],
      ["packet", b.packet, "Review requested"],
    ] as const) {
      const obj = raw as { id?: unknown; created_at?: unknown };
      if (
        typeof obj.created_at !== "string" ||
        !Number.isFinite(Date.parse(obj.created_at))
      )
        continue;
      const id = kind + ":" + String(obj.id);
      events.set(id, {
        id,
        at: obj.created_at,
        title,
        actor: "Framework",
        source: "framework",
        bundle: b,
        checks: kind === "evaluation" ? b.evaluation.results : undefined,
      });
    }
  });
  reviews.forEach((r) => {
    if (Number.isFinite(Date.parse(r.created_at)))
      events.set("review:" + r.id, {
        id: "review:" + r.id,
        at: r.created_at,
        title: r.action.replace(/_/g, " "),
        actor: r.actor_id,
        source: r.actor_type === "reviewer" ? "human" : "framework",
        review: r,
        bundle: bundles.find((b) =>
          r.packet_id
            ? b.packet.id === r.packet_id
            : b.revision.id === r.clip_revision_id,
        ),
      });
  });
  return [...events.values()].sort(
    (a, b) => a.at.localeCompare(b.at) || a.id.localeCompare(b.id),
  );
}
