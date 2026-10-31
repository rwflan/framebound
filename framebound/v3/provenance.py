"""Typed, revision-bound attribution. Claims never confer reviewer authority."""
from typing import Literal

from pydantic import Field, model_validator

from ..v2.domain import Strict
from ..v2 import storage as S
from ..v2.services.errors import InvalidInput

class ExecutionIdentity(Strict):
    provider: str = Field(min_length=1, max_length=128)
    requested_model: str = Field(min_length=1, max_length=200)
    observed_model: str | None = Field(default=None, max_length=200)
    observed_version: str | None = Field(default=None, max_length=200)
    harness: str | None = Field(default=None, max_length=200)
    harness_version: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, max_length=200)
    contributor_requested: Literal['on', 'off', 'unknown'] = 'unknown'
    contributor_effective: Literal['on', 'off', 'unknown'] = 'unknown'
    evidence_source: Literal['external_assertion', 'unknown'] = 'external_assertion'
    evidence_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')


class ReferenceBinding(Strict):
    asset_id: str = Field(min_length=1, max_length=128)
    byte_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    role: str = Field(min_length=1, max_length=128)
    conditioning_eligibility: Literal['cleared', 'original', 'research_only', 'unknown']
    eligibility_basis: str = Field(min_length=1, max_length=2000)


class StyleBoard(Strict):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=300)
    content_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class Transformation(Strict):
    operation: str = Field(min_length=1, max_length=2000)
    input_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    output_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class GenerationEvent(Strict):
    id: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=128)
    requested_model: str = Field(min_length=1, max_length=200)
    observed_model: str | None = Field(default=None, max_length=200)
    observed_version: str | None = Field(default=None, max_length=200)
    evidence_source: Literal['external_assertion', 'provider_response', 'unknown'] = 'external_assertion'
    provider_job_id: str | None = Field(default=None, max_length=128)
    request_id: str | None = Field(default=None, max_length=200)
    response_id: str | None = Field(default=None, max_length=200)
    outcome: Literal['succeeded', 'failed', 'unknown']
    prompt_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    conditioning: list[ReferenceBinding] = Field(default_factory=list, max_length=512)
    original_output_sha256: list[str] = Field(default_factory=list, max_length=512)
    output_asset_ids: list[str] = Field(default_factory=list, max_length=512)
    receipt_sha256: list[str] = Field(default_factory=list, max_length=128)
    edit_parent_event_id: str | None = Field(default=None, max_length=128)
    transformations: list[Transformation] = Field(default_factory=list, max_length=512)

    @model_validator(mode='after')
    def consistent(self):
        import re
        if any(not re.fullmatch('[0-9a-f]{64}', h) for h in self.original_output_sha256 + self.receipt_sha256):
            raise ValueError('output and receipt hashes must be SHA-256')
        if self.outcome == 'succeeded' and not (self.original_output_sha256 and self.output_asset_ids):
            raise ValueError('successful generation needs original outputs and materialized assets')
        if self.outcome != 'succeeded' and self.output_asset_ids:
            raise ValueError('failed/unknown generation cannot claim materialized outputs')
        if any(r.conditioning_eligibility not in {'original', 'cleared'} for r in self.conditioning):
            raise ValueError('supplied conditioning requires explicit original or cleared eligibility')
        return self


class RevisionProvenance(Strict):
    schema_version: Literal['1.0'] = '1.0'
    parent: ExecutionIdentity | None = None
    style_board: StyleBoard | None = None
    generations: list[GenerationEvent] = Field(default_factory=list, max_length=1024)

    @model_validator(mode='after')
    def unique_ids(self):
        ids = [e.id for e in self.generations]
        if len(ids) != len(set(ids)):
            raise ValueError('generation event IDs must be unique')
        return self


def parse(metadata):
    """Older free-form metadata has unknown attribution, never inferred identities."""
    raw = metadata.get('provenance') if isinstance(metadata, dict) else None
    return RevisionProvenance.model_validate(raw) if raw is not None else None


def blob_hashes(provenance):
    hashes = {provenance.style_board.content_sha256} if provenance.style_board else set()
    if provenance.parent and provenance.parent.evidence_sha256:
        hashes.add(provenance.parent.evidence_sha256)
    for event in provenance.generations:
        hashes.update(event.original_output_sha256 + event.receipt_sha256)
        for transform in event.transformations:
            hashes.update([transform.input_sha256, transform.output_sha256])
    return hashes


def validate_in(con, project, provenance, frame_asset_ids, ancestors):
    """Validate claimed bindings; local evidence requires a matching durable job."""
    if provenance is None:
        return
    for sha in blob_hashes(provenance):
        path = S.blob_path(project, sha)
        if not path.is_file() or S.sha256_bytes(path.read_bytes()) != sha:
            raise InvalidInput('missing or corrupt provenance blob: ' + sha)
    prior = {}
    for revision in ancestors:
        p = parse(revision.get('generation_metadata'))
        if p:
            prior.update({e.id: e for e in p.generations})
    events = dict(prior)
    for event in provenance.generations:
        if event.id in events:
            if event != events[event.id]:
                raise InvalidInput('generation event ID differs from immutable ancestry')
        if event.edit_parent_event_id and event.edit_parent_event_id not in events:
            raise InvalidInput('edit parent must precede event in this revision or its ancestry')
        for ref in event.conditioning:
            asset, _ = S.get(con, 'assets', ref.asset_id)
            if asset['byte_sha256'] != ref.byte_sha256:
                raise InvalidInput('conditioning hash differs from supplied asset')
            path = S.blob_path(project, ref.byte_sha256)
            if not path.is_file() or S.sha256_bytes(path.read_bytes()) != ref.byte_sha256:
                raise InvalidInput('conditioning bytes unavailable or corrupt')
        if not set(event.output_asset_ids) <= set(frame_asset_ids):
            raise InvalidInput('generation outputs must be bound to this revision')
        reachable = set(event.original_output_sha256)
        inherited_inputs={ref.byte_sha256 for ref in event.conditioning}
        for previous in prior.values():
            for aid in previous.output_asset_ids:
                try: inherited_inputs.add(S.get(con,'assets',aid)[0]['byte_sha256'])
                except KeyError: pass
        for transform in event.transformations:
            if transform.input_sha256 not in reachable | inherited_inputs:
                raise InvalidInput('postprocessing input is outside original-output ancestry')
            reachable.add(transform.output_sha256)
        for aid in event.output_asset_ids:
            asset, _ = S.get(con, 'assets', aid)
            if asset['byte_sha256'] not in reachable:
                raise InvalidInput('materialized output lacks original-output transformation ancestry')
        if event.provider_job_id:
            job, _ = S.get(con, 'jobs', event.provider_job_id)
            if not set(event.output_asset_ids) <= set(job.get('output_asset_ids', [])):
                raise InvalidInput('outputs differ from linked provider job')
        if event.evidence_source == 'provider_response':
            if not event.provider_job_id:
                raise InvalidInput('local observation needs a durable provider job')
            import json
            if job.get('origin') != 'live' or job.get('status') != 'succeeded':
                raise InvalidInput('local observation needs a successful live job')
            sha = job.get('response_artifact')
            if not sha or sha not in event.receipt_sha256:
                raise InvalidInput('local observation must include the actual response receipt')
            receipt = json.loads(S.blob_path(project, sha).read_bytes()).get('payload', {})
            if (receipt.get('observed_model') != event.observed_model or
                    receipt.get('model') != event.requested_model or
                    receipt.get('observed_version') != event.observed_version or
                    receipt.get('prompt_sha256') != event.prompt_sha256 or
                    receipt.get('conditioning_sha256') != [r.byte_sha256 for r in event.conditioning] or
                    receipt.get('response_id') != event.response_id or
                    receipt.get('output_bytes_sha256') not in event.original_output_sha256):
                raise InvalidInput('provider attribution differs from the locally observed receipt')
        events[event.id] = event


def summary(metadata):
    provenance = parse(metadata)
    return provenance.model_dump(mode='json') if provenance else None
