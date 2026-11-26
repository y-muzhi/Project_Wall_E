"""Read one WFP capture and identify drops on the exact WALL-E control connection."""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree

_MAX_CAPTURE_BYTES = 64 * 1024 * 1024
_TASK_SID = re.compile(r'S-1-15-2(?:-[0-9]{1,10}){7}')
_FILTER_FIELDS = ('filterKey', 'providerKey', 'layerKey', 'subLayerKey')


class _CaptureTree(ElementTree.TreeBuilder):
    def doctype(self, _name, _public_id, _system_id):
        raise ValueError('WFP captures must not contain a document type')


def _read_capture(path):
    with path.open('rb') as capture:
        raw = capture.read(_MAX_CAPTURE_BYTES + 1)
    if len(raw) > _MAX_CAPTURE_BYTES:
        raise ValueError('WFP capture exceeds the size limit')
    root = ElementTree.fromstring(raw, parser=ElementTree.XMLParser(target=_CaptureTree()))
    for node in root.iter():
        node.tag = node.tag.rsplit('}', 1)[-1]
    return root


def _drops(root, task_sid, source_port, control_port):
    port_pairs = {
        'MS_FWP_DIRECTION_IN': (str(control_port), str(source_port), 'task_inbound'),
        'MS_FWP_DIRECTION_OUT': (str(source_port), str(control_port), 'backend_outbound'),
    }
    drops = Counter()
    for event in root.iter():
        if event.tag not in ('netEvent', 'item'):
            continue
        if event.findtext('type') != 'FWPM_NET_EVENT_TYPE_CLASSIFY_DROP':
            continue
        header, drop = event.find('header'), event.find('classifyDrop')
        if header is None or drop is None:
            continue
        ports = port_pairs.get(drop.findtext('msFwpDirection'))
        if ports is None:
            continue
        local_port, remote_port, direction = ports
        if direction == 'task_inbound' and header.findtext('packageSid') != task_sid:
            continue
        fields = (
            'ipVersion',
            'ipProtocol',
            'localAddrV4',
            'remoteAddrV4',
            'localPort',
            'remotePort',
        )
        expected = ('FWP_IP_VERSION_V4', '6', '127.0.0.1', '127.0.0.1', local_port, remote_port)
        if tuple(header.findtext(field) for field in fields) != expected:
            continue
        filter_id, layer_id = drop.findtext('filterId', ''), drop.findtext('layerId', '')
        if not re.fullmatch(r'[1-9][0-9]{0,19}', filter_id) or not re.fullmatch(
            r'[0-9]{1,5}', layer_id
        ):
            raise ValueError('Matching WFP drop lacks a usable filter or layer ID')
        drops[(direction, int(filter_id), int(layer_id))] += 1
    return drops


def summarize_capture(path, task_sid, source_port, control_port):
    root = _read_capture(path)
    drops = _drops(root, task_sid, source_port, control_port)
    wanted_ids = {str(filter_id) for _, filter_id, _ in drops}
    filter_rows = defaultdict(list)
    for node in root.iter('item'):
        filter_id = node.findtext('filterId')
        if filter_id in wanted_ids and node.findtext('filterKey'):
            fields = {field: node.findtext(field) for field in _FILTER_FIELDS}
            fields['action'] = node.findtext('action/type')
            filter_rows[int(filter_id)].append(fields)

    results = []
    for (direction, filter_id, layer_id), count in sorted(drops.items()):
        rows = filter_rows[filter_id]
        status = 'missing'
        filter_details = None
        if len(rows) == 1:
            status = 'matched'
            filter_details = rows[0]
        elif len(rows) > 1:
            status = 'ambiguous'
        results.append(
            {
                'direction': direction,
                'filterId': filter_id,
                'layerId': layer_id,
                'dropCount': count,
                'filterStatus': status,
                'filter': filter_details,
            }
        )
    return results


def main(arguments=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog='Exit codes: 0 matched, 1 no drops, 2 invalid input, 3 missing or ambiguous filter.',
    )
    parser.add_argument('capture', type=Path, help='wfpdiag.xml from one short capture')
    parser.add_argument('--task-sid', required=True)
    parser.add_argument('--source-port', required=True, type=int)
    parser.add_argument('--control-port', required=True, type=int)
    args = parser.parse_args(arguments)
    if not _TASK_SID.fullmatch(args.task_sid):
        parser.error('An exact task AppContainer SID is required')
    ports = (args.source_port, args.control_port)
    if not all(1 <= port <= 65535 for port in ports) or args.source_port == args.control_port:
        parser.error('Distinct IPv4 loopback source and control ports are required')
    try:
        results = summarize_capture(args.capture, args.task_sid, *ports)
    except OSError:
        parser.error('Unable to read WFP capture')
    except (ElementTree.ParseError, ValueError):
        parser.error('Invalid or unsupported WFP capture')
    print(json.dumps({'matchingDrops': results}, indent=2))
    if not results:
        return 1
    return 3 if any(row['filterStatus'] != 'matched' for row in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
