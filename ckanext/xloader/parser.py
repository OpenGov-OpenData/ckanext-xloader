# -*- coding: utf-8 -*-
import datetime
from decimal import Decimal, InvalidOperation
import re
import six

from ckan.plugins.toolkit import asbool
from dateutil.parser import isoparser, parser, ParserError

from ckan.plugins.toolkit import config

CSV_SAMPLE_LINES = 1000
DATE_REGEX = re.compile(r'''^\d{1,4}[-/.\s]\S+[-/.\s]\S+''')
TIME_REGEX = re.compile(r'''^\d{1,2}:\d{2}''')


class TypeConverter:
    """ Post-process table cells to convert strings into numbers and timestamps
    as desired.
    """

    def __init__(self, types=None):
        self.types = types

    def convert_types(self, extended_rows):
        """ Try converting cells to numbers or timestamps if applicable.
        If a list of types was supplied, use that.
        If not, then try converting each column to numeric first,
        then to a timestamp. If both fail, just keep it as a string.
        """
        for row_number, headers, row in extended_rows:
            for cell_index, cell_value in enumerate(row):
                if cell_value is None:
                    row[cell_index] = ''
                if not cell_value:
                    continue
                cell_type = self.types[cell_index] if self.types else None
                if cell_type in [Decimal, None]:
                    converted_value = to_number(cell_value)
                    # Can't do a simple truthiness check,
                    # because 0 is a valid numeric result.
                    if converted_value is not None:
                        row[cell_index] = converted_value
                        continue
                if cell_type in [datetime.datetime, None]:
                    converted_value = to_timestamp(cell_value)
                    if converted_value:
                        row[cell_index] = converted_value
                elif cell_type is datetime.date:
                    converted_value = to_date(cell_value)
                    if converted_value:
                        row[cell_index] = converted_value
                elif cell_type is datetime.time:
                    converted_value = to_time(cell_value)
                    if converted_value is not None:
                        row[cell_index] = converted_value
            yield (row_number, headers, row)


def to_number(value):
    if not isinstance(value, six.string_types):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def to_timestamp(value):
    if not isinstance(value, six.string_types) or not DATE_REGEX.search(value):
        return None
    try:
        i = isoparser()
        return i.isoparse(value)
    except ValueError:
        try:
            p = parser()
            yearfirst = asbool(config.get('ckanext.xloader.parse_dates_yearfirst', False))
            dayfirst = asbool(config.get('ckanext.xloader.parse_dates_dayfirst', False))
            return p.parse(value, yearfirst=yearfirst, dayfirst=dayfirst)
        except ParserError:
            return None


def to_date(value):
    # datetime is a subclass of date, so it must be checked first
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    timestamp = to_timestamp(value)
    return timestamp.date() if timestamp else None


def to_time(value):
    if isinstance(value, datetime.datetime):
        return value.time()
    if isinstance(value, datetime.time):
        return value
    if not isinstance(value, six.string_types):
        return None
    if TIME_REGEX.search(value):
        try:
            return parser().parse(value).time()
        except (ValueError, OverflowError):
            return None
    timestamp = to_timestamp(value)
    return timestamp.time() if timestamp else None
