'''Rules for storing cumulative inverter energy counters in history tables.

When a cumulative counter drops by more than COUNTER_DECREASE_TOLERANCE_KWH,
the reading is treated as an inverter swap or counter reset: the period row
keeps its recorded energy by setting new_a = new_reading - (old_b - old_a)
and new_b = new_reading. Smaller decreases are ignored (previous _b kept) so
meter ordering jitter or brief stale register values are not recorded.
'''

# Absolute drop (kWh) below which a decrease is ignored, not a reset.
COUNTER_DECREASE_TOLERANCE_KWH = 0.5


def counters_should_be_skipped(produced, consumed, fed_in):
    '''Return True when all cumulative counters are zero (no sample).'''
    return produced == 0 and consumed == 0 and fed_in == 0


def _next_counter_pair(previous_a, previous_b, new_value):
    if new_value >= previous_b:
        return previous_a, new_value, False
    drop = previous_b - new_value
    if drop <= COUNTER_DECREASE_TOLERANCE_KWH:
        return previous_a, previous_b, False
    recorded_delta = previous_b - previous_a
    new_a = new_value - recorded_delta
    new_b = new_value
    return new_a, new_b, True


def next_history_counter_columns(row, produced, consumed, fed_in):
    '''Return produced_a/b, consumed_a/b, fed_in_a/b and any reset flags.'''
    pa, pb, rp = _next_counter_pair(row[1], row[2], produced)
    ca, cb, rc = _next_counter_pair(row[3], row[4], consumed)
    fa, fb, rf = _next_counter_pair(row[5], row[6], fed_in)
    return pa, pb, ca, cb, fa, fb, (rp or rc or rf)
