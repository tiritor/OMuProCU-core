
from enum import Enum


class TimeScales(Enum):
    SECONDS = 10 ** 0 
    MILLISECONDS = 10 ** 3
    MICROSECONDS = 10 ** 6
    NANOSECONDS = 10 ** 9

CURRENT_TIMEMEASUREMENT_TIMESCALE = TimeScales.NANOSECONDS