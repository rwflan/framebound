"""Deny-by-default feature-only wire format. No filesystem upload API exists.

Canonical JSON permits inspection of the exact bytes sent, with no archive,
image, mask, prompt, identity, provider response or arbitrary metadata lane.
"""
from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from .contracts import Strict, canonical


class FeatureRow(Strict):
    case_id: str = Field(pattern=r'^[0-9a-f]{64}$')
    family_id: str = Field(pattern=r'^[0-9a-f]{64}$')
    split: Literal['train','validation','test']
    features: list[list[float]] = Field(min_length=1,max_length=24)
    targets: list[StrictInt] = Field(min_length=9,max_length=9)
    assessed: list[StrictBool] = Field(min_length=9,max_length=9)
    challenge: StrictBool = False
    weight: float = Field(default=1.0,gt=0,le=1)

    @model_validator(mode='after')
    def numeric_only(self):
        if any(len(frame)!=8 or any(abs(v)>1000000 for v in frame) for frame in self.features):
            raise ValueError('only the frozen eight derived measurements per native frame are allowed')
        if any(t not in (0,1) for t in self.targets):
            raise ValueError('binary scoped labels required')
        if any(t and not m for t,m in zip(self.targets,self.assessed)):
            raise ValueError('unknowns must be masked, never asserted positive')
        return self


class FeatureShard(Strict):
    schema_version: Literal['feature-only-1.0'] = 'feature-only-1.0'
    extractor: Literal['native-numeric-v1'] = 'native-numeric-v1'
    rows: list[FeatureRow] = Field(min_length=1,max_length=10000)

    @model_validator(mode='after')
    def no_leakage(self):
        if len({r.case_id for r in self.rows}) != len(self.rows):
            raise ValueError('duplicate sequences')
        families = {}
        for r in self.rows:
            if r.family_id in families and families[r.family_id] != r.split:
                raise ValueError('family leakage across splits')
            families[r.family_id] = r.split
        return self


def inspect_payload(raw: bytes):
    if len(raw)>32*1024**2 or not raw.startswith(b'{'):
        raise ValueError('only bounded canonical numeric JSON is transferable; images and archives rejected')
    shard=FeatureShard.model_validate_json(raw)
    if raw!=canonical(shard):
        raise ValueError('unexpected or noncanonical payload bytes')
    return shard


def preupload(shard: FeatureShard):
    raw=canonical(shard)
    inspect_payload(raw)
    return raw,dict(schema_version='feature-transfer-manifest-1.0',sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),file_type='application/json',fields=list(FeatureShard.model_fields),
        row_fields=list(FeatureRow.model_fields),rows=len(shard.rows),contains_pixels=False,
        limitation='Derived numeric features are information-bearing, private and not anonymous.')


def transfer(raw: bytes, transport):
    """Transport sees only freshly inspected payload bytes, never local paths."""
    inspect_payload(raw)
    return transport(raw)
