import support
"""Run native dash admission with real body-contact flags and their provenance."""
import struct
import unittest
from unittest.mock import patch

import dash_contact_guard as fix
import counter_contact_fixture as base
import counter_dash_fixture as dash_tests

ACTORS=base.ACTORS


def machine(guard=True):
    c=base.machine()
    # The old dash fixture replaced this predicate with unconditional true.
    # Execute the real predicate here, including the producer's 5E/5F bits.
    c.write(0x1DEEA8,fix.NATIVE(0x1DEEA8,0xC4))
    c.callbacks.pop(0x1DEEA8,None)
    c.write(0x1DF800,fix.NATIVE(0x1DF800,0x2C))
    if guard:
        for p,b in fix.pieces():c.write(p,b)
    return c


def observe(c,source,target):
    """Enter the native confirmed-contact tail; no guessed distance threshold."""
    c.w(fix.core.TABLE+4*source,target)
    c.r[19]=ACTORS[source];c.r[20]=1
    c.run(0x1DF800,(0x1DF81C,))


def propose(c,left,right,kind=250):
    # Unlike the older fixture, do not force reciprocal targets. Asymmetric
    # selection is the regression: right can be touching a third fighter.
    c.w(fix.core.TABLE+4*left,right)
    dash_tests.flag(c,left,3);dash_tests.flag(c,left,0x47)
    dash_tests.flag(c,right,0x47 if kind==250 else 0x48)
    c.r[31]=0xFEED0000
    c.run(0x1C9010)
