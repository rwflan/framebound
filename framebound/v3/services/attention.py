"""Read-only attention rules. Lack of assessment or approval is not a defect."""

def evaluation_needs_intervention(evaluation):
    if not evaluation:
        return False
    return (evaluation.get('technical_status') in {'fail','error'}
            or evaluation.get('coverage') == 'partial'
            or any(r['outcome'] in {'fail','error'} or
                   (r['outcome']=='unmeasured' and r.get('required',True))
                   for r in evaluation.get('results',[])))


def run_needs_intervention(run,evaluation,open_marks):
    if run['lifecycle']=='cancelled':
        return False
    return (bool(open_marks)
            or run['creative_status'] in {'human_rejected','human_needs_changes'}
            or run['lifecycle'] in {'blocked','awaiting_input'}
            or evaluation_needs_intervention(evaluation))
