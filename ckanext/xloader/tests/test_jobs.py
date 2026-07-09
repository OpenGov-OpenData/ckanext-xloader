import pytest
import io
import os
import contextlib

from datetime import datetime

from requests import Response

from ckan.cli.cli import ckan
from ckan.plugins import toolkit
from ckan.tests import helpers, factories

from unittest import mock

from ckanext.xloader import jobs
from ckanext.xloader.job_exceptions import JobError
from ckanext.xloader.utils import get_xloader_user_apitoken


_TEST_FILE_CONTENT = "x, y\n1,2\n2,4\n3,6\n4,8\n5,10"


def get_response(download_url, headers):
    """Mock jobs.get_response() method."""
    resp = Response()
    resp.raw = io.BytesIO(_TEST_FILE_CONTENT.encode())
    resp.headers = headers
    return resp


def get_large_response(download_url, headers):
    """Mock jobs.get_response() method to fake a large file."""
    resp = Response()
    resp.raw = io.BytesIO(_TEST_FILE_CONTENT.encode())
    resp.headers = {'content-length': 2000000000}
    return resp


@pytest.fixture
def apikey():
    if toolkit.check_ckan_version(min_version="2.10"):
        sysadmin = factories.SysadminWithToken()
    else:
        # To provide support with CKAN 2.9
        sysadmin = factories.Sysadmin()
        sysadmin["token"] = get_xloader_user_apitoken()

    return sysadmin["token"]


@pytest.fixture
def data(create_with_upload, apikey):
    dataset = factories.Dataset()
    resource = create_with_upload(
        _TEST_FILE_CONTENT,
        "multiplication_2.csv",
        url="http://data",
        package_id=dataset["id"]
    )
    callback_url = toolkit.url_for(
        "api.action", ver=3, logic_function="xloader_hook", qualified=True
    )
    return {
        'api_key': apikey,
        'job_type': 'xloader_to_datastore',
        'result_url': callback_url,
        'metadata': {
            'ignore_hash': True,
            'ckan_url': toolkit.config.get('ckan.site_url'),
            'resource_id': resource["id"],
            'set_url_type': False,
            'task_created': datetime.utcnow().isoformat(),
            'original_url': resource["url"],
        }
    }


@pytest.mark.usefixtures("clean_db", "with_plugins")
class TestXLoaderJobs(helpers.FunctionalRQTestBase):

    def test_xloader_data_into_datastore(self, cli, data):
        self.enqueue(jobs.xloader_data_into_datastore, [data])
        with mock.patch("ckanext.xloader.jobs.get_response", get_response):
            stdout = cli.invoke(ckan, ["jobs", "worker", "--burst"]).output
            assert "File hash: d44fa65eda3675e11710682fdb5f1648" in stdout
            assert "Fields: [{'id': 'x', 'type': 'text'}, {'id': 'y', 'type': 'text'}]" in stdout
            assert "Copying to database..." in stdout
            assert "Creating search index..." in stdout
            assert "Express Load completed" in stdout

        resource = helpers.call_action("resource_show", id=data["metadata"]["resource_id"])
        assert resource["datastore_contains_all_records_of_source_file"]

    def test_xloader_ignore_hash(self, cli, data):
        self.enqueue(jobs.xloader_data_into_datastore, [data])
        with mock.patch("ckanext.xloader.jobs.get_response", get_response):
            stdout = cli.invoke(ckan, ["jobs", "worker", "--burst"]).output
            assert "Express Load completed" in stdout

        self.enqueue(jobs.xloader_data_into_datastore, [data])
        with mock.patch("ckanext.xloader.jobs.get_response", get_response):
            stdout = cli.invoke(ckan, ["jobs", "worker", "--burst"]).output
            assert "Copying to database..." in stdout
            assert "Express Load completed" in stdout

        data["metadata"]["ignore_hash"] = False
        self.enqueue(jobs.xloader_data_into_datastore, [data])
        with mock.patch("ckanext.xloader.jobs.get_response", get_response):
            stdout = cli.invoke(ckan, ["jobs", "worker", "--burst"]).output
            assert "Ignoring resource - the file hash hasn't changed" in stdout

    def test_data_too_big_error_if_content_length_bigger_than_config(self, cli, data):
        self.enqueue(jobs.xloader_data_into_datastore, [data])
        with mock.patch("ckanext.xloader.jobs.get_response", get_large_response):
            stdout = cli.invoke(ckan, ["jobs", "worker", "--burst"]).output
            assert "Data too large to load into Datastore:" in stdout

    def test_data_max_excerpt_lines_config(self, cli, data):
        self.enqueue(jobs.xloader_data_into_datastore, [data])
        with mock.patch("ckanext.xloader.jobs.get_response", get_large_response):
            with mock.patch("ckanext.xloader.jobs.MAX_EXCERPT_LINES", 1):
                stdout = cli.invoke(ckan, ["jobs", "worker", "--burst"]).output
                assert "Loading excerpt of ~1 lines to DataStore." in stdout

        resource = helpers.call_action("resource_show", id=data["metadata"]["resource_id"])
        assert resource["datastore_contains_all_records_of_source_file"] is False


@pytest.mark.usefixtures("clean_db")
class TestSetResourceMetadata(object):
    def test_simple(self):
        resource = factories.Resource()

        jobs.set_resource_metadata(
            {
                "datastore_contains_all_records_of_source_file": True,
                "datastore_active": True,
                "ckan_url": "http://www.ckan.org/",
                "resource_id": resource["id"],
            }
        )

        resource = helpers.call_action("resource_show", id=resource["id"])
        assert resource["datastore_contains_all_records_of_source_file"]
        assert resource["datastore_active"]
        assert resource["ckan_url"] == "http://www.ckan.org/"


# Field definitions as returned by datastore_search (i.e. what
# datastore_resource_exists yields), including a type override in ``info``.
_EXISTING_FIELDS = [
    {"id": "_id", "type": "int"},
    {"id": "x", "type": "text", "info": {"type_override": "timestamp"}},
    {"id": "y", "type": "text", "info": {}},
]


class TestRecreateEmptyTableOnError(object):
    """Unit tests for the recover-on-failure path in
    ``xloader_data_into_datastore_`` (the nested
    ``recreate_empty_table_if_dropped`` helper).

    These drive the orchestrator directly with all of its collaborators
    mocked, so no database or RQ worker is required.
    """

    def _run(self, load_error, existing_before, existing_after,
             recreate_config=True, get_action=None):
        """Invoke ``xloader_data_into_datastore_`` with the load step and the
        datastore lookups stubbed.

        :param load_error: exception instance the load raises (both the direct
            COPY and the tabulator fallback fail with it), or ``None`` to let
            the load "succeed".
        :param existing_before: datastore_search result captured before the
            load (drives ``preserved_fields``).
        :param existing_after: datastore_search result seen after the load has
            been attempted (``False`` == the load dropped the table).
        :param recreate_config: value of the recreate feature flag.
        :param get_action: optional pre-configured ``get_action`` mock (e.g.
            one whose ``datastore_create`` raises); a fresh mock is used if
            omitted.
        :returns: dict with the ``get_action`` mock, the
            ``set_resource_metadata`` mock, and any re-raised exception.
        """
        input = {
            "api_key": "key",
            "result_url": "http://ckan/callback",
            "metadata": {
                "resource_id": "res-1",
                "ignore_hash": True,
                "set_url_type": False,
            },
        }
        job_dict = {"metadata": input["metadata"]}
        logger = mock.Mock()

        resource = {"id": "res-1", "format": "CSV"}
        dataset = {"name": "ds"}

        tmp_file = mock.Mock()
        tmp_file.name = "/tmp/does-not-matter.csv"

        # datastore_resource_exists reports the table state relative to the
        # load: ``existing_before`` until the load has been attempted, then
        # ``existing_after`` (so the recovery helper's re-check sees whether
        # the load dropped the table). Robust to how often it is called.
        state = {"loaded": False}

        def fake_exists(resource_id):
            return existing_after if state["loaded"] else existing_before

        def do_load(*args, **kwargs):
            state["loaded"] = True
            if load_error is not None:
                raise load_error
            return ([], False)

        if get_action is None:
            get_action = mock.Mock()

        def config_get(key, default=None):
            if key == "ckanext.xloader.recreate_empty_table_on_error":
                return recreate_config
            return default

        fake_config = mock.Mock()
        fake_config.get.side_effect = config_get

        exc = None
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(jobs, "validate_input"))
            stack.enter_context(mock.patch.object(
                jobs, "get_resource_and_dataset",
                return_value=(resource, dataset)))
            stack.enter_context(mock.patch.object(
                jobs, "_download_resource_data",
                return_value=(tmp_file, "hashvalue")))
            stack.enter_context(mock.patch.object(
                jobs, "datastore_resource_exists", side_effect=fake_exists))
            stack.enter_context(mock.patch.object(
                jobs, "get_action", get_action))
            stack.enter_context(mock.patch.object(
                jobs, "set_resource_metadata"))
            stack.enter_context(mock.patch.object(
                jobs, "set_datastore_active"))
            stack.enter_context(mock.patch.object(
                jobs, "callback_xloader_hook"))
            stack.enter_context(mock.patch.object(
                jobs, "config", fake_config))
            stack.enter_context(mock.patch.object(
                os.path, "getsize", return_value=1))
            # Both load paths use do_load: a JobError from the direct COPY
            # (load_csv) triggers the tabulator fallback (load_table), which
            # fails the same way, so the error escapes to the recovery handler
            # exactly as it would in production.
            stack.enter_context(mock.patch.object(
                jobs.loader, "load_csv", side_effect=do_load))
            stack.enter_context(mock.patch.object(
                jobs.loader, "load_table", side_effect=do_load))
            stack.enter_context(mock.patch.object(
                jobs.loader, "calculate_record_count"))
            stack.enter_context(mock.patch.object(
                jobs.loader, "create_column_indexes"))

            try:
                jobs.xloader_data_into_datastore_(input, job_dict, logger)
            except Exception as e:  # noqa: BLE001 - re-raise is expected
                exc = e

        return {
            "get_action": get_action,
            "set_resource_metadata": jobs.set_resource_metadata,
            "exc": exc,
        }

    def _datastore_create_payloads(self, get_action):
        """Return the data_dicts passed to datastore_create."""
        create_action = get_action("datastore_create")
        # c[0] == positional args tuple (works on all supported Pythons).
        return [c[0][1] for c in create_action.call_args_list]

    def test_recreates_empty_table_when_load_drops_it(self):
        """Load fails and the table was dropped -> recreate it empty with the
        preserved fields (types + type-override info)."""
        result = self._run(
            load_error=JobError("bad value for type timestamp"),
            existing_before={"fields": _EXISTING_FIELDS},
            existing_after=False,  # table gone
        )

        # The original error is preserved (re-raised).
        assert isinstance(result["exc"], JobError)

        payloads = self._datastore_create_payloads(result["get_action"])
        assert len(payloads) == 1, "expected exactly one datastore_create"
        payload = payloads[0]
        assert payload["resource_id"] == "res-1"
        assert payload["records"] is None
        assert payload["force"] is True
        # _id is excluded; the type override survives in info.
        assert payload["fields"] == [
            {"id": "x", "type": "text", "info": {"type_override": "timestamp"}},
            {"id": "y", "type": "text", "info": {}},
        ]

        # Tab reappears but the empty table is not marked as containing all
        # records, and the file hash is NOT persisted (so re-upload reloads).
        result["set_resource_metadata"].assert_called_once()
        meta = result["set_resource_metadata"].call_args[0][0]
        assert meta["datastore_active"] is True
        assert meta["datastore_contains_all_records_of_source_file"] is False
        assert "hash" not in meta

    def test_no_recreate_when_table_still_exists(self):
        """If the load failed but the table still exists (e.g. tabulator wrote
        a chunk, or it was only truncated), recovery must be a no-op."""
        result = self._run(
            load_error=JobError("some load error"),
            existing_before={"fields": _EXISTING_FIELDS},
            existing_after={"fields": _EXISTING_FIELDS},  # still there
        )

        assert isinstance(result["exc"], JobError)
        assert self._datastore_create_payloads(result["get_action"]) == []
        result["set_resource_metadata"].assert_not_called()

    def test_no_recreate_for_brand_new_resource(self):
        """A first-ever load with no prior table has nothing to preserve, so
        recovery does not fabricate a table."""
        result = self._run(
            load_error=JobError("bad first load"),
            existing_before=False,   # no table before
            existing_after=False,
        )

        assert isinstance(result["exc"], JobError)
        assert self._datastore_create_payloads(result["get_action"]) == []
        result["set_resource_metadata"].assert_not_called()

    def test_recreate_disabled_by_config(self):
        """With the feature flag off, a dropped table is left dropped."""
        result = self._run(
            load_error=JobError("bad value"),
            existing_before={"fields": _EXISTING_FIELDS},
            existing_after=False,
            recreate_config=False,
        )

        assert isinstance(result["exc"], JobError)
        assert self._datastore_create_payloads(result["get_action"]) == []
        result["set_resource_metadata"].assert_not_called()

    def test_recovery_never_masks_original_error(self):
        """If datastore_create itself fails, the original load error must still
        be the one that propagates (best-effort recovery)."""
        failing_get_action = mock.Mock()
        failing_get_action("datastore_create").side_effect = \
            RuntimeError("recovery boom")

        result = self._run(
            load_error=JobError("the real cause"),
            existing_before={"fields": _EXISTING_FIELDS},
            existing_after=False,
            get_action=failing_get_action,
        )

        # The recovery's RuntimeError is swallowed; the original load error is
        # what propagates.
        assert isinstance(result["exc"], JobError)
        assert str(result["exc"]) == "the real cause"
