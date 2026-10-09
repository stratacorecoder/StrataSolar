'''Helpers for cumulative counter samples and derived energy display.'''


def counters_should_be_skipped(produced, consumed, fed_in):
    '''Return True when all cumulative counters are zero (no sample).'''
    return produced == 0 and consumed == 0 and fed_in == 0


def derived_energy_parts(produced, consumed, fed_in):
    '''Clamp primary deltas and derived self/grid consumption at zero.'''
    p = max(0.0, produced)
    c = max(0.0, consumed)
    f = max(0.0, fed_in)
    self_use = max(min(p - f, c), 0.0)
    grid = max(c - self_use, 0.0)
    return p, c, f, self_use, grid
