"""CLI adapter using the framework's reusable source-bound observation service."""
from framebound.v3.character_observations import propose_observation, png
from scripts.build_movement_demo import send, save


def observe(root,frame_id,image,reference,features,items,description,*,phase='measure',geometry_external=False):
    return propose_observation(root,frame_id,image,reference,features,items,description,
                               dispatch=send,persist=save,phase=phase,geometry_external=geometry_external)
