import test from "node:test";
import assert from "node:assert/strict";
import {
  chronology,
  frameIssues,
  needsReview,
  priority,
  valueLabel,
  boundLabel,
  projectId,
} from "./review-model.bundle.mjs";

const bundle = () => ({
  revision: { id: "candidate", created_at: "2026-01-02T00:00:00Z" },
  packet: {
    id: "packet",
    comparison_revision_id: "baseline",
    created_at: "2026-01-04T00:00:00Z",
  },
  evaluation: {
    id: "evaluation",
    created_at: "2026-01-03T00:00:00Z",
    technical_status: "pass",
    coverage_status: "complete",
    results: [],
  },
  contract: { character_revision_id: "character" },
  current_decision: { acceptance: "unreviewed" },
});
test("technical passes do not imply artistic acceptance or complete coverage", () => {
  const b = bundle();
  assert.equal(needsReview(b, []), true);
  b.current_decision.acceptance = "approved";
  assert.equal(needsReview(b, []), false);
  b.evaluation.coverage_status = "partial";
  assert.equal(needsReview(b, []), true);
  assert.equal(priority(b, []), 1);
  assert.equal(
    priority(b, [{ clip_revision_id: "candidate", task_status: "reopened" }]),
    0,
  );
});
test("correction bands use inclusive authored ticks and recorded comparison lineage", () => {
  const b = bundle(),
    issues = [
      {
        event_id: "resolved",
        clip_revision_id: "candidate",
        frame_range: [12, 15],
        task_status: "resolved",
      },
      {
        event_id: "source",
        clip_revision_id: "baseline",
        frame_range: [8, 12],
        task_status: "open",
      },
      {
        event_id: "outside",
        clip_revision_id: "candidate",
        frame_range: [16, 20],
      },
      {
        event_id: "unrelated",
        clip_revision_id: "other",
        frame_range: [12, 15],
      },
    ];
  assert.deepEqual(
    frameIssues(issues, b, 12, 15).map((i) => i.event_id),
    ["source", "resolved"],
  );
});
test("missing evidence stays unmeasured while observed zero remains a measured zero", () => {
  assert.equal(
    valueLabel({ observed_value: null, outcome: "unmeasured" }),
    "—",
  );
  assert.equal(valueLabel({ observed_value: 0, units: "fraction" }), "0.0%");
  assert.equal(
    valueLabel({ observed_value: 0.410488, units: "fraction" }),
    "41.0%",
  );
  assert.equal(
    boundLabel({ expected_interval: [0, 0.12], units: "fraction" }),
    "0%–12%",
  );
  assert.equal(boundLabel({ outcome: "unmeasured" }), "Unmeasured");
});
test("timeline deduplicates immutable artifacts, orders real timestamps and never invents missing ones", () => {
  const b = bundle();
  const events = chronology(
    [b, b],
    [
      {
        id: "review",
        created_at: "2026-01-01T00:00:00Z",
        action: "approve_reference",
        actor_type: "reviewer",
        actor_id: "human",
        clip_revision_id: "character",
      },
    ],
  );
  assert.deepEqual(
    events.map((e) => e.id),
    [
      "review:review",
      "revision:candidate",
      "evaluation:evaluation",
      "packet:packet",
    ],
  );
  assert.equal(events[0].source, "human");
  delete b.evaluation.created_at;
  assert.equal(chronology([b], []).length, 2);
  assert.equal(
    projectId(b, {
      character_revisions: [{ id: "character", project_id: "project" }],
    }),
    "project",
  );
  assert.equal(projectId(b, null), "unassigned");
});

test("first attention follows authored frame order, not analyzer check order", async () => {
  const { attentionSlot } = await import("./review-model.bundle.mjs");
  const b = bundle();
  b.frames = Array.from({ length: 8 }, (_, i) => ({
    hold_ticks: 4,
    frame_instance_id: `frame-${i}`,
  }));
  b.evaluation.results = [
    { scope: "slot 5", outcome: "fail" },
    { scope: "slot 2", outcome: "unmeasured" },
    { scope: "slot 1", outcome: "pass" },
    { scope: "clip", outcome: "error" },
  ];
  assert.equal(attentionSlot(b, []), 2);
  b.evaluation.results.reverse();
  assert.equal(attentionSlot(b, []), 2);
  assert.equal(
    attentionSlot(b, [
      {
        clip_revision_id: "baseline",
        frame_range: [4, 7],
        task_status: "open",
      },
    ]),
    1,
  );
  assert.equal(
    attentionSlot(b, [
      {
        clip_revision_id: "candidate",
        frame_range: [0, 3],
        task_status: "resolved",
      },
      {
        clip_revision_id: "unrelated",
        frame_range: [0, 3],
        task_status: "open",
      },
    ]),
    2,
  );
});
test("attention respects nonuniform holds, instance-only issues, coverage gaps and clean clips", async () => {
  const { attentionSlot } = await import("./review-model.bundle.mjs");
  const b = bundle();
  b.frames = [2, 7, 3, 5].map((hold_ticks, i) => ({
    hold_ticks,
    frame_instance_id: `frame-${i}`,
  }));
  assert.equal(attentionSlot(b, []), 0);
  assert.equal(
    attentionSlot(b, [
      {
        clip_revision_id: "candidate",
        frame_range: [9, 11],
        task_status: "awaiting_comparison",
      },
    ]),
    2,
  );
  assert.equal(
    attentionSlot(b, [
      {
        clip_revision_id: "candidate",
        frame_instance_id: "frame-3",
        task_status: "reopened",
      },
    ]),
    3,
  );
  b.evaluation.coverage_status = "partial";
  b.evaluation.results = [
    { scope: "slot 3", outcome: "unmeasured" },
    { scope: "slot 1", outcome: "not_applicable" },
  ];
  assert.equal(attentionSlot(b, []), 1);
});
