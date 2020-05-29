import ckan.plugins.toolkit as toolkit
try:
    from ckan.common import config
except ImportError:
    # for ckan 2.7 and earlier
    from pylons import config


def xloader_status(resource_id):
    try:
        return toolkit.get_action('xloader_status')(
            {}, {'resource_id': resource_id})
    except toolkit.ObjectNotFound:
        return {
            'status': 'unknown'
        }


def xloader_check_resource_format(res_format):
    valid_formats = config.get('ckanext.xloader.formats')
    if res_format is None:
        return False
    return res_format.lower() in valid_formats


def xloader_get_valid_formats():
    return config.get('ckanext.xloader.formats')


def xloader_status_description(status):
    _ = toolkit._

    if status.get('status'):
        captions = {
            'complete': _('Complete'),
            'pending': _('Pending'),
            'submitting': _('Submitting'),
            'error': _('Error'),
        }

        return captions.get(status['status'], status['status'].capitalize())
    else:
        return _('Not Uploaded Yet')
