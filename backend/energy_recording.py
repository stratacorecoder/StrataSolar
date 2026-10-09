'''Rules for storing cumulative inverter energy counters in history tables.'''


def counters_should_be_skipped(produced, consumed, fed_in):
    '''Return True when a sample must not be written to history tables.

    All-zero samples are skipped (no new information). A partial-zero sample
    (some cumulative counters exactly zero while others are not) is treated
    as a device/API glitch and skipped the same way — legitimate cumulative
    readings are either all still at zero on a brand-new install or all
    positive once any energy has been recorded.
    '''
    if produced == 0 and consumed == 0 and fed_in == 0:
        return True
    zeros = (produced == 0, consumed == 0, fed_in == 0)
    if any(zeros) and not all(zeros):
        return True
    return False


def _next_counter_pair(previous_a, previous_b, new_value):
    if new_value < previous_b:
        return new_value, new_value
    return previous_a, new_value


def next_history_counter_columns(row, produced, consumed, fed_in):
    '''Return produced_a/b, consumed_a/b, fed_in_a/b after applying a sample.'''
    return (
        *_next_counter_pair(row[1], row[2], produced),
        *_next_counter_pair(row[3], row[4], consumed),
        *_next_counter_pair(row[5], row[6], fed_in),
    )
