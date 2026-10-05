import resource from '../../../backend/resources/v2/templates/catalog.v1.json' with { type: 'json' };
import { array, bool, checked, choices, distinct, id, nonempty, require, shape } from '../api/decoding.ts';
import { snapshotObject } from '../api/client.ts';
const types = ['NEW', 'CHANGE'] as const, modes = ['IDEATION', 'DESIGN'] as const;
const typeOptions = array(shape({ value: choices(types), label: nonempty }), 2, 2);
const modeOptions = array(shape({ value: choices(modes), label: nonempty }), 2, 2);
const template = shape({ template_key: nonempty, template_version: nonempty, label: nonempty,
  requirement_types: checked(array(choices(types), 2, 1), values => distinct(values)), markdown_path: nonempty,
  locked_headings: array(shape({ level: checked(id, value => require(value <= 6)), text: nonempty }), 100, 1) });
const catalog = shape({ schema_version: choices([1]), proposal: bool, requirement_types: typeOptions, initialization_modes: modeOptions, templates: array(template, 100, 1) });
const installed = catalog(snapshotObject(resource));
require(!installed.proposal); distinct(installed.requirement_types.map(option => option.value)); distinct(installed.initialization_modes.map(option => option.value));
distinct(installed.templates.map(value => value.template_key + ':' + value.template_version));
export const requirementCatalog = installed;
