import datetime
import pytest
import mock
from ckan.tests import helpers, factories
from ckan.logic import _actions

from ckanext.xloader.plugin import XLoaderFormats, DEFAULT_FORMATS


@pytest.mark.usefixtures("clean_db", "with_plugins")
@pytest.mark.ckan_config("ckan.plugins", "datastore xloader")
class TestNotify(object):
    def test_submit_on_resource_create(self, monkeypatch):
        func = mock.Mock()
        monkeypatch.setitem(_actions, "xloader_submit", func)

        dataset = factories.Dataset()

        assert not func.called

        helpers.call_action(
            "resource_create",
            {},
            package_id=dataset["id"],
            url="http://example.com/file.csv",
            format="CSV",
        )

        assert func.called

    def test_submit_when_url_changes(self, monkeypatch):
        func = mock.Mock()
        monkeypatch.setitem(_actions, "xloader_submit", func)

        dataset = factories.Dataset()

        resource = helpers.call_action(
            "resource_create",
            {},
            package_id=dataset["id"],
            url="http://example.com/file.pdf",
        )

        assert not func.called  # because of the format being PDF

        helpers.call_action(
            "resource_update",
            {},
            id=resource["id"],
            package_id=dataset["id"],
            url="http://example.com/file.csv",
            format="CSV",
        )

        assert func.called

    def _pending_task(self, resource_id):
        return {
            "entity_id": resource_id,
            "entity_type": "resource",
            "task_type": "xloader",
            "last_updated": str(datetime.datetime.utcnow()),
            "state": "pending",
            "key": "xloader",
            "value": "{}",
            "error": "{}",
        }


class TestXloaderFormatsUpload(object):

    def teardown(self):
        XLoaderFormats._formats = None

    def test_formats_config_not_setup(self):
        assert XLoaderFormats.get_xloader_formats() == DEFAULT_FORMATS

    def test_formats_config_exist(self):
        formats = u'csv tsv'
        with helpers.changed_config(u'ckanext.xloader.formats', formats):
            # Reread data from config
            XLoaderFormats.setup_formats()
            assert XLoaderFormats.get_xloader_formats() == formats.split()

    def test_format_is_an_xloader_format(self):
        formats = u'csv tsv'
        with helpers.changed_config(u'ckanext.xloader.formats', formats):
            for res_format in DEFAULT_FORMATS:
                is_valid_format = XLoaderFormats.is_it_an_xloader_format(res_format)
                if res_format in formats.split():
                    assert is_valid_format
                else:
                    assert not is_valid_format

    def test_format_is_a_default_xloader_format(self):
        formats = u'csv tsv'
        with helpers.changed_config(u'ckanext.xloader.formats', formats):
            for res_format in DEFAULT_FORMATS:
                assert XLoaderFormats.is_it_a_default_xloader_format(res_format)
