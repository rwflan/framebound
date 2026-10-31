"""Bounded Muse Responses specialist; no tool loop, provider retry or Modal."""
import base64
import hashlib
import json
import math
import os
import urllib.request

from .contracts import canonical
from .dispatch import Response


class MuseResponses:
    def __init__(self, *, key=None):
        from .credentials import load_key
        self.key=key or load_key()
        if not self.key: raise ValueError('Configure the local Muse key or MODEL_API_KEY for the bounded Responses adapter')

    def execute(self, request, *, timeout):
        payload=request['payload']
        wire=payload['wire']
        if wire['model'] not in {'muse-image-1.0','muse-spark-1.3'}:
            raise ValueError('only explicitly priced Muse models are supported')
        req=urllib.request.Request('https://api.meta.ai/v1/responses',data=canonical(wire),
            headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'},method='POST')
        # urllib has no automatic paid POST retries. Any possible acceptance with
        # a missing result is left unknown by the outer durable dispatch service.
        with urllib.request.urlopen(req,timeout=timeout) as response:
            raw=response.read(64*1024**2+1)
        if len(raw)>64*1024**2: raise ValueError('provider response size ceiling')
        try: body=json.loads(raw)
        except ValueError: body={}
        images=sum(item.get('type')=='image_generation_call' and bool(item.get('result')) for item in body.get('output',[]) if isinstance(item,dict))
        usage=body.get('usage') or {}
        exact=wire['model']=='muse-image-1.0' or ('input_tokens' in usage and 'output_tokens' in usage)
        if wire['model']=='muse-image-1.0': incurred=images*10000
        elif exact:
            cached=(usage.get('input_tokens_details') or {}).get('cached_tokens',0)
            incurred=math.ceil((usage['input_tokens']-cached)*1.25+cached*.15+usage['output_tokens']*4.25)
        else: incurred=request['quote']
        return Response(raw,incurred,images,dict(response_id=body.get('id'),status=body.get('status'),
            requested_model=wire['model'],observed_model=body.get('model'),observed_version=body.get('version'),
            usage=usage,cost_basis='provider usage and frozen rate' if exact else 'unreconciled conservative upper bound'))


def image_part(raw):
    return dict(type='input_image',image_url='data:image/png;base64,'+base64.b64encode(raw).decode())


def wire(model, text, images=(), *, max_output_tokens=None):
    value=dict(model=model,input=[dict(role='user',content=[dict(type='input_text',text=text),*[image_part(b) for b in images]])])
    if max_output_tokens is not None: value['max_output_tokens']=max_output_tokens
    return value


def extract_image(raw):
    from ...v2.providers.wire import parse_image_response
    parsed=parse_image_response(json.loads(raw))
    if len(parsed['images'])!=1: raise ValueError('one sheet per frozen send required')
    return parsed['images'][0]['bytes']


def extract_text(raw):
    from ...v2.providers.wire import parse_spark_response
    parsed=parse_spark_response(json.loads(raw))
    if parsed['calls']: raise ValueError('specialist tools are disabled')
    if len(parsed['text'].encode())>128*1024: raise ValueError('teacher output bound')
    return json.loads(parsed['text'])
