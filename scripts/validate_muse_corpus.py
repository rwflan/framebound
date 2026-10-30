"""Validate research sources, frozen split and brief coverage without calling a model."""
import json
from pathlib import Path


def validate(root):
    root = Path(root)
    corpus = json.loads((root/'docs/research/game-art/corpus/boards.json').read_text())
    games = {g['game']:g for g in json.loads((root/'docs/research/game-art/games.json').read_text())['games']}
    boards = corpus['boards']; ids = {b['board_id'] for b in boards}
    assert len(boards) == len(ids) == 8, 'eight unique boards required'
    splits = corpus['split_freeze']
    dev, held = set(splits['development']), set(splits['held_out'])
    assert not dev & held and dev | held == ids, 'board families must occupy exactly one frozen split'
    briefs = []
    for board in boards:
        assert len(board['briefs']) == 4
        assert {b['category'] for b in board['briefs']} == {'locomotion','acting','interaction','effects'}
        assert len(board['motion_studies']) >= 3
        for ref in board['references']:
            assert ref['url'] in {s['url'] for s in games[ref['game']]['screenshots']}, 'reference is not an actual source'
            assert ref['conditioning_eligibility'] == 'research_only'
        for brief in board['briefs']:
            assert brief['generation_status'] == 'pending', 'planning manifest cannot invent a generation'
            assert brief['holds_nonuniform'] and brief['counterexamples_to_test'] and brief['unsupported_measurement_limitations']
            briefs.append(brief['brief_id'])
    assert len(briefs) == len(set(briefs)) == 32
    limits = corpus['global_policy']
    assert limits['repair_policy']['max_model_repairs_per_base'] <= 2
    ceiling = limits['finite_limits_corpus_pilot']
    assert ceiling['max_total_calls'] >= 32*3 + ceiling['calibration_calls_reserved']
    assert ceiling['max_spend_usd'] > 0
    return {'boards':8,'base_briefs':32,'source_links':sum(len(b['references']) for b in boards),'generation_calls':0,'visual_review':'pending','motion_studies':'pending'}


if __name__ == '__main__':
    print(json.dumps(validate(Path(__file__).resolve().parents[1]), indent=2))
