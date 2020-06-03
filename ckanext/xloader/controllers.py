import ckan.plugins as p

_ = p.toolkit._


class ResourceDataController(p.toolkit.BaseController):

    def resource_data(self, id, resource_id):

        if p.toolkit.request.method == 'POST':
            try:
                p.toolkit.c.pkg_dict = \
                    p.toolkit.get_action('xloader_submit')(
                        None, {'resource_id': resource_id}
                    )
            except p.toolkit.ValidationError:
                pass

            p.toolkit.redirect_to(
                controller='ckanext.xloader.controllers:ResourceDataController',
                action='resource_data',
                id=id,
                resource_id=resource_id
            )

        resource, pkg_dict = self.get_resource_and_pkg_dict(id, resource_id)

        try:
            xloader_status = p.toolkit.get_action('xloader_status')(
                None, {'resource_id': resource_id}
            )
        except p.toolkit.ObjectNotFound:
            xloader_status = {}
        except p.toolkit.NotAuthorized:
            p.toolkit.abort(403, _('Not authorized to see this page'))

        return p.toolkit.render('xloader/resource_data.html',
                                extra_vars={
                                    'status': xloader_status,
                                    'resource': resource,
                                    'pkg_dict': pkg_dict,
                                })

    def unsupported_format(self, id, resource_id):

        resource, pkg_dict = self.get_resource_and_pkg_dict(id, resource_id)
        return p.toolkit.render('xloader/unsupported_format.html',
                                extra_vars={
                                    'resource': resource,
                                    'pkg_dict': pkg_dict,
                                })

    def get_resource_and_pkg_dict(self, id, resource_id):
        try:
            p.toolkit.c.pkg_dict = p.toolkit.get_action('package_show')(
                None, {'id': id}
            )
            p.toolkit.c.resource = p.toolkit.get_action('resource_show')(
                None, {'id': resource_id}
            )
        except (p.toolkit.ObjectNotFound, p.toolkit.NotAuthorized):
            p.toolkit.abort(404, _('Resource not found'))
        return p.toolkit.c.resource, p.toolkit.c.pkg_dict
