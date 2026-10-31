"""Construct an ephemeral, feature-only Modal app after local admission.

No application, image build, deployment or network call happens at import time.
Only allowlisted generic Python modules are added to the remote image. There is
no mount, secret, corpus volume, provider client or generation entrypoint.
"""
from pathlib import Path

from .contracts import digest
from .learning import RECIPE
from .remote import Job

SOURCE_FILES=('__init__.py','contracts.py','assessment.py','transfer.py','remote.py','learning.py')


def build(job: Job):
    import modal
    if job.recipe_sha256!=digest(RECIPE): raise ValueError('unpinned training recipe')
    source=Path(__file__).resolve().parent
    image=modal.Image.from_registry('python:3.11-slim@'+job.image_digest).pip_install('numpy==2.4.0','pydantic==2.12.5','torch==2.9.0')
    # Parent package files are empty: no implicit source or local-directory copy.
    image=image.run_commands('mkdir -p /root/framebound/v3/campaign',
        'touch /root/framebound/__init__.py /root/framebound/v3/__init__.py')
    for filename in SOURCE_FILES:
        image=image.add_local_file(source/filename,'/root/framebound/v3/campaign/'+filename,copy=True)
    app=modal.App('framebound-feature-job')

    @app.function(image=image,serialized=True,gpu=job.gpu,cpu=job.cpu_physical*2,memory=job.ram_gib*1024,
        timeout=job.seconds,startup_timeout=job.startup_seconds or 120,retries=0,min_containers=0,max_containers=1,
        env={'CUBLAS_WORKSPACE_CONFIG':':4096:8'},include_source=False,block_network=True,restrict_modal_access=True,single_use_containers=True)
    def worker(payload: bytes, job_data: dict):
        from framebound.v3.campaign.learning import fit,train_temporal_torch,RECIPE
        from framebound.v3.campaign.contracts import digest
        from framebound.v3.campaign.remote import Job,execute_pure
        def execute(shard,job,key):
            if job.recipe_sha256!=digest(RECIPE): raise ValueError('recipe hash mismatch')
            # Labels with sufficient support remain experimental until calibration.
            from framebound.v3.campaign.assessment import CATEGORIES
            from framebound.v3.campaign.learning import eligibility
            if job.purpose=='profile':
                import time,torch
                started=time.monotonic()
                values=torch.tensor([r.features[0] for r in shard.rows],dtype=torch.float32,device='cuda')
                head=torch.nn.Linear(8,9,device='cuda')
                for _ in range(100):head(values)
                torch.cuda.synchronize()
                return dict(status='profile_only',cases=len(shard.rows),elapsed_seconds=time.monotonic()-started,
                    peak_vram_bytes=torch.cuda.max_memory_allocated(),promoted=False)
            categories=[c for c in CATEGORIES if eligibility(shard,[c])['eligible']]
            if not categories:raise ValueError('no supported learned categories')
            return dict(linear=fit(shard,categories=categories),
                        temporal=train_temporal_torch(shard,categories=categories),promoted=False)
        return execute_pure(payload,Job.model_validate(job_data),execute)
    return app,worker


class ModalTransport:
    """One ephemeral invocation, cancelled at the quoted wall allowance.

    Long training is disabled until a durable checkpoint/resume transport is
    configured. Current small jobs return a complete checkpoint within ten minutes.
    """
    def __call__(self,payload,job_data):
        import time
        from .transfer import inspect_payload
        inspect_payload(payload)
        job=Job.model_validate(job_data)
        if job.seconds>600:raise ValueError('jobs over ten minutes require a configured durable checkpoint transport')
        app,worker=build(job)
        start=time.monotonic();call=None
        with app.run():
            remaining=job.seconds+job.startup_seconds+job.replay_seconds-(time.monotonic()-start)
            if remaining<=0:raise TimeoutError('image/startup exceeded reserved wall allowance')
            try:
                call=worker.spawn(payload,job_data)
                return call.get(timeout=remaining)
            except BaseException:
                if call is not None:call.cancel(terminate_containers=True)
                raise
