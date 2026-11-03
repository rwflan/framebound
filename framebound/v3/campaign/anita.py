"""Build a split-safe engineering shard from the Anita animation corpus.

Anita supplies human-authored RGBA animation layers at published timing. It
does not supply Framebound defect assessments. This module therefore limits
its labels to source-sequence continuity and artifacts introduced by a frozen
local transformation. Those labels are engineering evidence, not artistic
acceptance or human truth.
"""
from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path

import numpy as np
from PIL import Image

from ..intake import inspect
from .assessment import CATEGORIES
from .contracts import canonical
from .features import extract
from .learning import eligibility
from .transfer import FeatureRowV2, FeatureShard, preupload

VERSION = 'anita-engineering-shard-v1'
SOURCE_URL = 'https://github.com/zhenglinpan/AnitaDataset'
SOURCE_LICENSE = (
    'Mixed CC BY 4.0 and CC BY-NC-SA 4.0. This implementation treats every '
    'derived engineering checkpoint as noncommercial research evidence.'
)
FRAME_COUNT = 6
DEFAULT_TRAIN_FAMILIES = 95
DEFAULT_VALIDATION_FAMILIES = 13
DEFAULT_TEST_FAMILIES = 5
DEFAULT_TRAIN_SEQUENCES = 300
DEFAULT_WINDOWS_PER_SCENE = 8


def _id(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _scene_key(film, scene):
    return _id(['anita', film, scene])


def _frame_paths(path):
    return sorted(
        (item for item in path.iterdir() if item.is_file() and item.suffix.lower() == '.png'),
        key=lambda item: item.name,
    )


def discover(root, *, minimum_frames=FRAME_COUNT):
    """Return the exact color-scene inventory considered for the shard."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError('Anita extraction root does not exist')
    scenes = []
    for film in sorted(item for item in root.iterdir() if item.is_dir()):
        layer = film / 'color'
        if not layer.is_dir():
            continue
        for scene in sorted(item for item in layer.iterdir() if item.is_dir()):
            frames = _frame_paths(scene)
            if len(frames) < minimum_frames:
                continue
            series = {'color': frames}
            sketch = film / 'sketch' / scene.name
            if sketch.is_dir():
                sketch_frames = _frame_paths(sketch)
                if len(sketch_frames) >= minimum_frames:
                    series['sketch'] = sketch_frames
            scenes.append(dict(
                film=film.name,
                scene=scene.name,
                family=_scene_key(film.name, scene.name),
                series=series,
            ))
    required = DEFAULT_TRAIN_FAMILIES + DEFAULT_VALIDATION_FAMILIES + DEFAULT_TEST_FAMILIES
    if len(scenes) < required:
        raise ValueError('Anita extraction does not contain enough eligible scenes')
    scenes.sort(key=lambda item: item['family'])
    return scenes


def _split(scenes):
    train_end = DEFAULT_TRAIN_FAMILIES
    validation_end = train_end + DEFAULT_VALIDATION_FAMILIES
    result = []
    for index, scene in enumerate(scenes):
        row = dict(scene)
        row['split'] = (
            'train' if index < train_end
            else 'validation' if index < validation_end
            else 'test'
        )
        result.append(row)
    return result


def _starts(scene, limit):
    count = len(scene['frames'])
    stride = max(1, (count - FRAME_COUNT) // max(limit - 1, 1))
    values = [min(index * stride, count - FRAME_COUNT) for index in range(limit)]
    return sorted(set(values))


def _load_window(scene, layer, start):
    paths = scene['series'][layer][start:start + FRAME_COUNT]
    images = []
    for path in paths:
        with Image.open(path) as image:
            image.load()
            rgba = image.convert('RGBA')
            if not inspect(rgba)['eligible']:
                return None
            images.append(rgba.copy())
    return images


def _normalize(images, native_size):
    """Crop once against the union silhouette, then scale every frame equally."""
    masks = [np.asarray(image)[:, :, 3] > 32 for image in images]
    pixels = np.logical_or.reduce(masks)
    ys, xs = np.nonzero(pixels)
    if not len(xs):
        return None
    left, right = int(xs.min()), int(xs.max()) + 1
    top, bottom = int(ys.min()), int(ys.max()) + 1
    width, height = right - left, bottom - top
    if width < 8 or height < 8:
        return None
    padding = max(2, round(max(width, height) * 0.12))
    side = max(width, height) + padding * 2
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    box = (
        round(center_x - side / 2),
        round(center_y - side / 2),
        round(center_x + side / 2),
        round(center_y + side / 2),
    )
    output = []
    for image in images:
        resized = image.crop(box).resize(
            (native_size, native_size),
            Image.Resampling.LANCZOS,
        )
        if not inspect(resized)['eligible']:
            return None
        output.append(resized)
    return output


def _usable(images):
    if len(images) != FRAME_COUNT:
        return False
    arrays = [np.asarray(image) for image in images]
    distinct = len({hashlib.sha256(array.tobytes()).hexdigest() for array in arrays})
    if distinct < 3:
        return False
    centers = []
    for array in arrays:
        mask = array[:, :, 3] > 32
        ys, xs = np.nonzero(mask)
        if not len(xs):
            return False
        centers.append((xs.mean() / array.shape[1], ys.mean() / array.shape[0]))
    spread = max(x for x, _ in centers) - min(x for x, _ in centers)
    vertical = max(y for _, y in centers) - min(y for _, y in centers)
    return spread >= 0.001 or vertical >= 0.001


def _temporal_variant(images, order):
    return [images[index] for index in order]


def _artifact_variant(images, native_size):
    output = list(images)
    middle = 2
    array = np.asarray(images[middle].convert('RGBA')).copy()
    shift = max(3, native_size // 14)
    ghost = np.roll(array, (shift, -shift), axis=(0, 1))
    visible = ghost[:, :, 3] > 0
    empty = array[:, :, 3] <= 8
    array[visible & empty, :3] = ghost[visible & empty, :3]
    array[visible & empty, 3] = (ghost[visible & empty, 3] // 2).astype(np.uint8)
    # A deterministic hole also forces the alpha/support measurements to move.
    ys, xs = np.nonzero(array[:, :, 3] > 32)
    if len(xs):
        center_x = int(np.median(xs))
        center_y = int(np.median(ys))
        radius = max(2, native_size // 20)
        left = max(0, center_x - radius)
        right = min(native_size, center_x + radius)
        top = max(0, center_y - radius)
        bottom = min(native_size, center_y + radius)
        array[top:bottom, left:right, 3] = 0
    output[middle] = Image.fromarray(array, 'RGBA')
    return output


def _rows(*, scene, layer, start, images, native_size):
    temporal_index = CATEGORIES.index('temporal')
    artifacts_index = CATEGORIES.index('artifacts')
    sequence_id = _id([scene['family'], layer, start])
    variants = (
        ('source', images, (), ()),
        ('temporal-reorder', _temporal_variant(images, (0, 2, 1, 3, 4, 5)), ('temporal',), ()),
        ('temporal-delay', _temporal_variant(images, (0, 2, 3, 4, 1, 5)), ('temporal',), ()),
        ('temporal-reverse', _temporal_variant(images, (5, 4, 3, 2, 1, 0)), ('temporal',), ()),
        ('artifact-injection', _artifact_variant(images, native_size), ('artifacts',), ()),
    )
    rows = []
    for variant, frames, positives, negatives in variants:
        assessed = [False] * len(CATEGORIES)
        targets = [0] * len(CATEGORIES)
        presented = set(positives) | set(negatives)
        for category in presented:
            index = CATEGORIES.index(category)
            assessed[index] = True
            targets[index] = int(category in positives)
        if variant == 'source':
            assessed[temporal_index] = True
            assessed[artifacts_index] = True
        measurement = extract(
            frames,
            [1] * FRAME_COUNT,
            loop=False,
            extractor='native-geometry-v2',
        )
        rows.append(FeatureRowV2(
            case_id=_id([sequence_id, variant]),
            family_id=scene['family'],
            split=scene['split'],
            sequence_id=sequence_id,
            features=measurement['features'].tolist(),
            targets=targets,
            assessed=assessed,
            challenge=variant != 'source',
            weight=1.0,
            category_weights=[1.0] * len(CATEGORIES),
        ))
    return rows


def build(
    root,
    *,
    version,
    output,
    native_size=256,
    train_sequences=DEFAULT_TRAIN_SEQUENCES,
):
    """Create and persist a private feature shard plus its source manifest."""
    if not isinstance(version, str) or not version:
        raise ValueError('nonempty shard version required')
    if type(native_size) is not int or not 64 <= native_size <= 512:
        raise ValueError('native size must be between 64 and 512')
    scenes = _split(discover(root))
    rows = []
    windows = []
    counts = Counter()
    for scene in scenes:
        limit = DEFAULT_WINDOWS_PER_SCENE if scene['split'] == 'train' else 5
        for layer, frames in scene['series'].items():
            sequence_scene = dict(scene, frames=frames)
            for start in _starts(sequence_scene, limit):
                images = _load_window(scene, layer, start)
                if images is None:
                    continue
                images = _normalize(images, native_size)
                if images is None or not _usable(images):
                    continue
                windows.append(dict(
                    family=scene['family'],
                    split=scene['split'],
                    film=scene['film'],
                    layer=layer,
                    scene=scene['scene'],
                    start=start,
                    source_files=[
                        dict(
                            file=str(Path(path).relative_to(Path(root).resolve())),
                            sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                        )
                        for path in frames[start:start + FRAME_COUNT]
                    ],
                ))
                rows.extend(_rows(
                    scene=scene,
                    layer=layer,
                    start=start,
                    images=images,
                    native_size=native_size,
                ))
                counts[scene['split']] += 1
    if counts['train'] < train_sequences:
        raise ValueError(
            f'only {counts["train"]} usable training sequences; '
            f'{train_sequences} required'
        )
    shard = FeatureShard(
        schema_version='feature-only-2.0',
        extractor='native-geometry-v2',
        rows=rows,
    )
    training_gate = eligibility(shard, ['temporal', 'artifacts'])
    if not training_gate['eligible']:
        raise ValueError('generated shard does not meet the supported training gate')
    raw, transfer_manifest = preupload(shard)
    output = Path(output).resolve()
    repository = Path(__file__).resolve().parents[3]
    if output.is_relative_to(repository):
        raise ValueError('derived public-corpus data must stay outside the repository')
    output.mkdir(parents=True, exist_ok=True)
    source_manifest = dict(
        schema_version=VERSION,
        version=version,
        source_url=SOURCE_URL,
        source_license=SOURCE_LICENSE,
        source_root=str(Path(root).resolve()),
        native_size=native_size,
        frame_count=FRAME_COUNT,
        limitations=[
            'The dataset supplies scene folders, not stable character identities; scene groups prevent window leakage but do not prove unseen-character generalization.',
            'Source continuity is engineering evidence, not artistic acceptance.',
            'Temporal labels exercise declared order failures and cannot identify arbitrary motion on their own.',
        ],
        sampling=dict(
            train_families=DEFAULT_TRAIN_FAMILIES,
            validation_families=DEFAULT_VALIDATION_FAMILIES,
            test_families=DEFAULT_TEST_FAMILIES,
            windows_per_train_scene=DEFAULT_WINDOWS_PER_SCENE,
            windows_per_validation_or_test_scene=5,
        ),
        labels=dict(
            source_good='human-authored source order with temporal=0 and artifacts=0',
            temporal_positive=(
                'frozen middle-frame swap, delayed interior frame, and reversed '
                'sequence variants all retain temporal=1 under one source identity'
            ),
            artifacts_positive='frozen ghost plus support-hole injection artifacts=1',
            authority=(
                'Engineering source-continuity and injected-defect labels only; '
                'no human artistic acceptance or arbitrary animation-quality claim.'
            ),
        ),
        training_gate=training_gate,
        counts=dict(
            windows=dict(counts),
            rows=len(rows),
            families=dict(Counter(row.family_id for row in rows)),
        ),
        windows=windows,
        feature_manifest=transfer_manifest,
    )
    files = {
        'features.json': raw,
        'source-manifest.json': canonical(source_manifest),
    }
    paths = {}
    for name, content in files.items():
        path = output / name
        if path.exists() and path.read_bytes() != content:
            raise ValueError(f'{name} already exists with different contents')
        if not path.exists():
            path.write_bytes(content)
        paths[name] = str(path)
    return dict(
        version=version,
        shard=shard,
        path=paths,
        manifest=source_manifest,
        counts=dict(counts),
    )
