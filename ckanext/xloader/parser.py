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
# Drop currency letters and symbols. e/E stay only when they are an exponent:
# a digit (or separator) before them and a signed digit run after them.
# That keeps 1e3 / 1.5e2 and drops the E in 'EUR 12' and '1,200 EUR'.
MONEY_BODY_REGEX = re.compile(
    r'(?<![\d.,])[eE]|[eE](?![+-]?\d)|[^\d.,eE+\-]'
)
MONEY_SCI_REGEX = re.compile(
    r'^([+-]?)(\d[\d.,]*)[eE]([+-]?\d+)$'
)


class Money(Decimal):
    """Marker type for Currency type_override columns (Postgres money).

    Subclasses Decimal so values remain numeric, but identity checks
    distinguish it from plain Decimal for _TYPE_MAPPING.
    """
    pass


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
                elif cell_type is Money:
                    converted_value = to_money(cell_value)
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


def _normalize_decimal_separators(value):
    """Return a Decimal-friendly numeric string with '.' as the decimal mark.

    Supports US (1,250.50) and EU (1.234,56 / 12,34) grouping. A lone comma
    with exactly three following digits is treated as a thousands separator
    (1,250); otherwise a lone comma is the decimal mark (12,34).
    """
    if not value or value in ('.', ',', '-', '+', '-.', '.-', '-,', ',-'):
        return None
    has_dot = '.' in value
    has_comma = ',' in value
    if has_dot and has_comma:
        if value.rfind(',') > value.rfind('.'):
            # EU: 1.234,56
            return value.replace('.', '').replace(',', '.')
        # US: 1,234.56
        return value.replace(',', '')
    if has_comma:
        parts = value.split(',')
        if len(parts) == 2 and len(parts[1]) != 3:
            # EU decimal: 12,34 or 7,00
            return parts[0] + '.' + parts[1]
        # US/EU thousands: 1,250 or 1,234,567
        return value.replace(',', '')
    if has_dot:
        parts = value.split('.')
        if len(parts) > 2:
            # EU thousands: 1.234.567
            return ''.join(parts)
        return value
    return value


def to_money(value):
    """Parse a currency-like string into Decimal, or return None.

    Handles currency symbols and codes (EUR, USD), accounting parentheses,
    US/EU separators, and scientific notation (1e3, 1.5e2). An e/E is kept
    only when it is an exponent, so 'EUR 12' does not become 1e12.
    """
    if isinstance(value, Decimal):
        return value
    if not isinstance(value, six.string_types):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    negative = False
    if cleaned.startswith('(') and cleaned.endswith(')'):
        negative = True
        cleaned = cleaned[1:-1].strip()
    cleaned = MONEY_BODY_REGEX.sub('', cleaned)
    if not cleaned:
        return None

    sci = MONEY_SCI_REGEX.match(cleaned)
    if sci:
        sign, mantissa, exponent = sci.groups()
        mantissa = _normalize_decimal_separators(mantissa)
        if mantissa is None:
            return None
        try:
            result = Decimal(sign + mantissa + 'e' + exponent)
        except InvalidOperation:
            return None
    else:
        # Strip a single leading sign so separator logic sees the digits.
        sign = ''
        if cleaned[0] in '+-':
            sign = cleaned[0]
            cleaned = cleaned[1:]
        normalized = _normalize_decimal_separators(cleaned)
        if normalized is None:
            return None
        result = to_number(sign + normalized)
        if result is None:
            return None

    if negative:
        # Accounting parentheses always mean a negative absolute value,
        # even if the inner text already had a leading minus.
        result = -abs(result)
    return result
