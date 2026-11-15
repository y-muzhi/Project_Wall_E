"""ConfigurationOption reads from the original ResourceCatalog, under the live lease."""

from backend.app.infrastructure.resources import ConfigInvalid

from .configuration_identities import require_schema


def list_options(runtime, request):
    require_schema(runtime)
    # Hold the original read lease throughout the immutable resource snapshot.
    # Nothing in this read prepares resources, probes native state or loads secrets.
    with runtime.database.transaction():
        try:
            items = runtime.catalog.code_configuration_options(request.kind)
        except ConfigInvalid:
            return {
                'code': 'CONFIG_NOT_READY',
                'data': None,
                'details': {'capability_codes': ['Q20-CONFIG']},
            }
        total = len(items)
        start = (request.page - 1) * 20
        selected = items[start : start + 20]
    return {
        'code': 'READ_OK',
        'data': {
            'items': selected,
            'page': request.page,
            'page_size': 20,
            'total': total,
            'total_pages': (total + 19) // 20,
        },
        'details': None,
    }
