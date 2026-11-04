# -*- coding: utf-8 -*-
import os
import pytest

from decimal import Decimal
from datetime import date, datetime, time

from tabulator import Stream
from ckanext.xloader.parser import TypeConverter, to_date, to_time

csv_filepath = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "samples", "date_formats.csv")
)
date_time_filepath = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "samples", "date_time_sample.csv")
)


class TestParser(object):
    def test_simple(self):
        with Stream(csv_filepath, format='csv',
                    post_parse=[TypeConverter().convert_types]) as stream:
            assert stream.sample == [
                [
                    'date',
                    'temperature',
                    'place'
                ],
                [
                    datetime(2011, 1, 2, 0, 0),
                    Decimal('-1'),
                    'Galway'
                ],
                [
                    datetime(2011, 1, 3, 0, 0),
                    Decimal('0.5'),
                    'Galway'
                ],
                [
                    datetime(2011, 1, 2, 0, 0),
                    Decimal('5'),
                    'Berkeley'
                ],
                [
                    datetime(2003, 11, 1, 0, 0),
                    Decimal('6'),
                    'Berkeley'
                ],
            ]

    @pytest.mark.ckan_config("ckanext.xloader.parse_dates_dayfirst", True)
    def test_dayfirst(self):
        print('test_dayfirst')
        with Stream(csv_filepath, format='csv',
                    post_parse=[TypeConverter().convert_types]) as stream:
            assert stream.sample == [
                [
                    'date',
                    'temperature',
                    'place'
                ],
                [
                    datetime(2011, 1, 2, 0, 0),
                    Decimal('-1'),
                    'Galway'
                ],
                [
                    datetime(2011, 3, 1, 0, 0),
                    Decimal('0.5'),
                    'Galway'
                ],
                [
                    datetime(2011, 2, 1, 0, 0),
                    Decimal('5'),
                    'Berkeley'
                ],
                [
                    datetime(2003, 1, 11, 0, 0),
                    Decimal('6'),
                    'Berkeley'
                ],
            ]

    @pytest.mark.ckan_config("ckanext.xloader.parse_dates_yearfirst", True)
    def test_yearfirst(self):
        print('test_yearfirst')
        with Stream(csv_filepath, format='csv',
                    post_parse=[TypeConverter().convert_types]) as stream:
            assert stream.sample == [
                [
                    'date',
                    'temperature',
                    'place'
                ],
                [
                    datetime(2011, 1, 2, 0, 0),
                    Decimal('-1'),
                    'Galway'
                ],
                [
                    datetime(2011, 1, 3, 0, 0),
                    Decimal('0.5'),
                    'Galway'
                ],
                [
                    datetime(2011, 1, 2, 0, 0),
                    Decimal('5'),
                    'Berkeley'
                ],
                [
                    datetime(2011, 1, 3, 0, 0),
                    Decimal('6'),
                    'Berkeley'
                ],
            ]

    @pytest.mark.ckan_config("ckanext.xloader.parse_dates_dayfirst", True)
    @pytest.mark.ckan_config("ckanext.xloader.parse_dates_yearfirst", True)
    def test_yearfirst_dayfirst(self):
        with Stream(csv_filepath, format='csv',
                    post_parse=[TypeConverter().convert_types]) as stream:
            assert stream.sample == [
                [
                    'date',
                    'temperature',
                    'place'
                ],
                [
                    datetime(2011, 1, 2, 0, 0),
                    Decimal('-1'),
                    'Galway'
                ],
                [
                    datetime(2011, 3, 1, 0, 0),
                    Decimal('0.5'),
                    'Galway'
                ],
                [
                    datetime(2011, 2, 1, 0, 0),
                    Decimal('5'),
                    'Berkeley'
                ],
                [
                    datetime(2011, 3, 1, 0, 0),
                    Decimal('6'),
                    'Berkeley'
                ],
            ]

    def test_date_and_time_types(self):
        types = [str, Decimal, date, time]
        with Stream(date_time_filepath, format='csv',
                    post_parse=[TypeConverter(types=types).convert_types]) as stream:
            assert stream.sample == [
                ['name', 'amount', 'event_date', 'event_time'],
                ['City Hall', Decimal('1250.50'), date(2024, 3, 15), time(14, 30)],
                ['Library', Decimal('0'), date(2024, 3, 16), time(9, 5)],
                ['Park', Decimal('42'), date(2024, 11, 1), time(0, 0)],
                ['Museum', Decimal('9999.99'), date(2024, 12, 31), time(23, 59, 59)],
                ['Annex', Decimal('7'), '', ''],
            ]

    def test_to_date(self):
        assert to_date('2024-03-15') == date(2024, 3, 15)
        assert to_date('2024-03-15 14:30:00') == date(2024, 3, 15)
        assert to_date(datetime(2024, 3, 15, 14, 30)) == date(2024, 3, 15)
        assert to_date(date(2024, 3, 15)) == date(2024, 3, 15)
        assert to_date('not a date') is None

    def test_to_time(self):
        assert to_time('14:30') == time(14, 30)
        assert to_time('14:30:15') == time(14, 30, 15)
        assert to_time('2:30 PM') == time(14, 30)
        assert to_time('2024-03-15T14:30:00') == time(14, 30)
        assert to_time(datetime(2024, 3, 15, 0, 0)) == time(0, 0)
        assert to_time(time(23, 59, 59)) == time(23, 59, 59)
        assert to_time('99:99') is None
        assert to_time('not a time') is None
