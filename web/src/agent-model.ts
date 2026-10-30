export type Roi = { left: number; top: number; right: number; bottom: number };
export type Target = {
  id: string; check_id: string; outcome: string; slots: number[]; display_numbers: number[];
  tick_range: number[]; roi: Roi | null; desired_outcome: string; observed: unknown; expected: unknown;
  observation_source: string; evidence_assets: {id:string;byte_sha256:string;http_path?:string}[];
};
export type Feedback = { id: string; baseline_revision_id: string; disposition: string; creative_status: string;
  reason: string | null; targets: Target[]; remaining_submissions: number };
export type Task = { id:string; spec:{ intent:string; animation_id:string; canvas:{width:number;height:number};
  timing:{holds:number[];ticks_per_second:number}; loop:boolean; profile:string; appearance:string;scene?:{limitation:string}|null;
  inputs:{asset_id:string;role:string;provenance:string}[] }; requirements: {check:string;applicability:string;limitation:string}[] };
export type Mark = { id:string; run_id:string; owner:string; version:number; handoff_id:string;
  slots:number[]; roi:Roi|null; tick_range:number[]; candidate_revision_id:string|null;
  correction:{status:string;desired_outcome:string;baseline_revision_id:string} };
export type Run = { id:string; project_id:string; animation_id:string; task_id:string; task:Task;
  lifecycle:string; stop_reason:string|null; creative_status:string; current_revision_id:string|null;
  best_revision_id:string|null; submission_ids:string[]; interventions:Mark[]; needs_intervention:boolean; version:number };
export type Event = { id:string; run_id:string; project_id:string; animation_id:string; event:string;
  revision_id:string|null; source:string; created_at:string; note?:string; ordinal:number };
export type AgentDeskData = {runs:Run[]; events:Event[]; projects:{id:string;name:string}[]};
export type SourceComparison = {designation:{designated_by:string;designation_basis:string;provenance:string};
  frames:{output_slot:number;output_tick:number;source_tick:number[];source_slot:number;asset_id:string;asset_url:string;correspondence:string}[]};
export type AgentBundle = { source_comparison?:SourceComparison|null; revision:{ id:string; run_id:string; parent_revision_id:string|null; frame_asset_ids:string[] };
  evaluation:{id:string;technical_status:string;coverage:string;results:{id:string;family:string;outcome:string;slots:number[];
  observed:unknown;expected:unknown;reason:string;source:string;roi:Roi|null}[]};
  task:Task; feedback:Feedback; frames:{id:string;slot:number;asset_id:string;asset_url:string;hold_ticks:number}[];
  current_revision_id:string; best_revision_id:string };
export function firstActionable(bundle:AgentBundle):number {
  const slots=bundle.feedback.targets.flatMap(target=>target.slots);
  return slots.length ? Math.min(...slots) : 0;
}
export function formatMeasurement(value:unknown):string {
  if(value===null || value===undefined) return 'Unmeasured';
  return typeof value==='object' ? JSON.stringify(value) : String(value);
}
