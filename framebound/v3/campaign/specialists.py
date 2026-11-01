"""Bounded Muse Responses specialist; no tool loop, provider retry or Modal."""
import base64
import hashlib
import json
import math
import os
import re
import time
import urllib.request
import urllib.error

from .contracts import canonical
from .dispatch import Response, ProviderRejected, ProviderObservationError
from .ledger import ProviderPending


def validate_acceptance(request, body, *, initial=False):
    wire=request['payload']['wire']
    streaming=wire.get('stream') is True
    if (not (wire.get('background') is True or streaming) or not isinstance(body,dict)
            or not re.fullmatch(r'resp_[A-Za-z0-9_-]{1,128}',body.get('id',''))
            or (body.get('model')!=wire['model'] and not (streaming and initial and body.get('model') is None))
            or (not streaming and body.get('background') is not True)
            or (body.get('metadata')!=wire.get('metadata') and not (streaming and body.get('metadata') is None))
            or body.get('status') not in {'queued','in_progress','completed','failed','cancelled','incomplete'}):
        raise ValueError('provider acceptance does not match the frozen background request')


class MuseResponses:
    def __init__(self, *, key=None):
        from .credentials import load_key
        self.key=key or load_key()
        if not self.key: raise ValueError('Configure the local Muse key or MODEL_API_KEY for the bounded Responses adapter')

    def preflight(self, request):
        wire=request['payload']['wire']
        if wire['model'] not in {'muse-image-1.0','muse-spark-1.3'}:
            raise ValueError('only explicitly priced Muse models are supported')
        if wire.get('background') and (wire.get('stream') or len(canonical(wire))>1048576):
            raise ValueError('background body must fit 1 MiB without streaming; no paid send performed')
        if len(canonical(wire))>50*1024**2:raise ValueError('provider request body exceeds bounded inline-media limit')

    def execute(self, request, *, timeout):
        self.preflight(request)
        if request['payload']['wire'].get('background') or request['payload']['wire'].get('stream'):
            raise ValueError('background creation requires a durable acceptance callback')
        return self._result(request,self._post(request,timeout=timeout))

    def _open_post(self, request, *, timeout):
        payload=request['payload']
        wire=payload['wire']
        if wire['model'] not in {'muse-image-1.0','muse-spark-1.3'}:
            raise ValueError('only explicitly priced Muse models are supported')
        req=urllib.request.Request('https://api.meta.ai/v1/responses',data=canonical(wire),
            headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'},method='POST')
        # urllib has no automatic paid POST retries. Any possible acceptance with
        # a missing result is left unknown by the outer durable dispatch service.
        try:
            return urllib.request.urlopen(req,timeout=timeout)
        except urllib.error.HTTPError as error:
            raw=error.read(65537)
            try:body=json.loads(raw)
            except ValueError:body={}
            detail=body.get('error') if isinstance(body,dict) else None
            if (len(raw)<=65536 and isinstance(detail,dict) and
                    ((error.code==400 and detail.get('type')=='invalid_request_error') or
                     (error.code==413 and detail.get('code')=='payload_too_large'))):
                raise ProviderRejected(Response(raw,0,0,dict(http_status=error.code,not_accepted=True,
                    requested_model=wire['model'],error=detail,cost_basis='Documented pre-inference validation rejection; no output'))) from error
            raise
    def _post(self, request, *, timeout):
        with self._open_post(request,timeout=timeout) as response:raw=response.read(64*1024**2+1)
        if len(raw)>64*1024**2:raise ValueError('provider response size ceiling')
        return raw

    def execute_stream(self,request,*,timeout,on_acceptance,on_observation):
        self.preflight(request)
        if not request['payload']['wire'].get('stream'):raise ValueError('frozen streaming request required')
        transcript=bytearray();data=[];accepted=None;final=None
        def event():
            nonlocal accepted,final
            if not data:return
            raw=b'\n'.join(data);data.clear()
            if raw==b'[DONE]':return
            item=json.loads(raw);kind=item.get('type');body=item.get('response')
            if kind=='response.created':
                validate_acceptance(request,body,initial=True)
                on_observation(bytes(transcript));on_acceptance(body);accepted=body
            elif kind in {'response.completed','response.failed','response.incomplete','response.cancelled'}:
                validate_acceptance(request,body)
                if accepted and accepted['id']!=body['id']:raise ValueError('stream response identity changed')
                if not accepted:on_acceptance(body);accepted=body
                final=body
        try:
            with self._open_post(request,timeout=timeout) as response:
                while True:
                    line=response.readline(64*1024**2+1)
                    if not line:break
                    transcript.extend(line)
                    if len(transcript)>64*1024**2:raise ValueError('stream byte ceiling')
                    if not line.strip():event()
                    elif line.startswith(b'data:'):data.append(line[5:].strip())
                    if final is not None:break
                if data:event()
            on_observation(bytes(transcript))
            if final is None:raise ProviderPending('Accepted stream ended before terminal response') if accepted else ValueError('Stream has no acceptance event')
            result=self._result(request,canonical(final))
            result.receipt.update(transport='responses-sse-v1',transcript_sha256=hashlib.sha256(transcript).hexdigest(),
                normalization='Canonical response extracted from retained terminal SSE event')
            return result
        except ProviderPending:
            raise
        except (ValueError,TypeError) as error:
            raise ProviderObservationError('Unverified stream retained',bytes(transcript)) from error
        except BaseException:
            if transcript:on_observation(bytes(transcript))
            raise

    def execute_with_acceptance(self, request, *, timeout, on_acceptance):
        self.preflight(request)
        if not request['payload']['wire'].get('background'):
            raise ValueError('explicit frozen background request required')
        raw=self._post(request,timeout=timeout)
        try:body=json.loads(raw);validate_acceptance(request,body)
        except (ValueError,TypeError) as error:
            raise ProviderObservationError('Unverified provider acknowledgement retained',raw) from error
        # Commit identity before any polling. A restart may GET this ID, never
        # repeat creation. Failure before this acknowledgement remains unknown.
        on_acceptance(body)
        if body['status'] not in {'queued','in_progress'}:return self._result(request,raw)
        return self.retrieve(request,body,timeout=timeout)

    def retrieve(self, request, acceptance, *, timeout):
        validate_acceptance(request,acceptance,initial=True)
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            req=urllib.request.Request('https://api.meta.ai/v1/responses/'+acceptance['id'],
                headers={'Authorization':'Bearer '+self.key},method='GET')
            with urllib.request.urlopen(req,timeout=max(1,min(30,deadline-time.monotonic()))) as response:
                raw=response.read(64*1024**2+1)
            if len(raw)>64*1024**2:raise ValueError('provider response size ceiling')
            try:
                body=json.loads(raw);validate_acceptance(request,body)
                if body['id']!=acceptance['id']:raise ValueError('retrieved response identity differs')
            except (ValueError,TypeError) as error:
                raise ProviderObservationError('Unverified retrieved response retained',raw) from error
            if body['status'] not in {'queued','in_progress'}:return self._result(request,raw)
            time.sleep(min(2,max(0,deadline-time.monotonic())))
        raise ProviderPending('Accepted response is still pending; retrieve later')

    def _result(self, request, raw):
        wire=request['payload']['wire']
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
