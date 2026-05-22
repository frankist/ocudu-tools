#!/usr/bin/env python3
"""
Extract UE ID mappings from F1AP, NGAP, or E1AP pcap files.

Runs tshark on the given pcap and tracks how UE identifiers map to each other,
printing one line per mapping update:

    <frame>, <message>, <id1>=<val1>, <id2>=<val2>, ...

For F1AP: tracks du_ue, cu_ue, c_rnti (printed in hex).
For NGAP: tracks ran_ue, amf_ue.
For E1AP: tracks cu_cp_ue, cu_up_ue.

Usage:
    python3 map_ue_ids.py <pcap_file>

The protocol is auto-detected from the filename (ngap/f1ap/e1ap) or by
probing the first packets with tshark.
"""

import os
import subprocess
import sys

# (label, tshark_field, output_as_hex)
_ID_FIELDS = {
    'f1ap': [
        ('du_ue',   'f1ap.GNB_DU_UE_F1AP_ID', False),
        ('cu_ue',   'f1ap.GNB_CU_UE_F1AP_ID', False),
        ('c_rnti',  'f1ap.C_RNTI',             True),
    ],
    'ngap': [
        ('ran_ue',  'ngap.RAN_UE_NGAP_ID',      False),
        ('amf_ue',  'ngap.AMF_UE_NGAP_ID',      False),
    ],
    'e1ap': [
        ('cu_cp_ue', 'e1ap.GNB_CU_CP_UE_E1AP_ID', False),
        ('cu_up_ue', 'e1ap.GNB_CU_UP_UE_E1AP_ID', False),
    ],
}

# These messages always introduce a new UE context — never merge with an
# existing record even if a same ID is recycled from a released UE.
_NEW_UE_MSGS = {
    'f1ap': {'InitialULRRCMessageTransfer'},
    'ngap': {'InitialUEMessage'},
    'e1ap': {'BearerContextSetupRequest'},
}

# These messages signal that a UE context has been fully released.
# The matching record is removed so its IDs can be safely recycled.
_RELEASE_MSGS = {
    'f1ap': {'UEContextReleaseComplete'},
    'ngap': {'UEContextReleaseComplete'},
    'e1ap': {'BearerContextReleaseComplete'},
}


def _detect_protocol(pcap_file):
    name = os.path.basename(pcap_file).lower()
    for proto in _ID_FIELDS:
        if proto in name:
            return proto
    result = subprocess.run(
        ['tshark', '-r', pcap_file, '-c', '20', '-T', 'fields', '-e', 'frame.protocols'],
        capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        for proto in _ID_FIELDS:
            if proto in line.lower():
                return proto
    raise SystemExit(
        f'Cannot detect protocol in {pcap_file!r}. '
        'File name or content must contain ngap, f1ap, or e1ap.'
    )


def _run_tshark(pcap_file, fields):
    args = ['tshark', '-r', pcap_file, '-T', 'fields']
    for f in fields:
        args += ['-e', f]
    result = subprocess.run(args, capture_output=True, text=True)
    return result.stdout.splitlines()


def _parse_val(raw, as_hex):
    """Return the first value from a (possibly comma-separated) tshark field."""
    first = raw.split(',')[0].strip()
    if not first:
        return None
    if as_hex:
        return hex(int(first))
    return first


def _msg_name(info_col):
    """Extract the protocol message name from the tshark Info column."""
    # Info column format: "MessageName, optional details [optional bracketed suffix]"
    # Take the part before the first comma, then drop any " [...]" suffix.
    part = info_col.split(',')[0]
    bracket = part.find(' [')
    if bracket != -1:
        part = part[:bracket]
    return part.strip()


def _find_record(records, packet_ids):
    """Return the first active record that shares at least one ID with packet_ids."""
    for rec in records:
        for label, val in packet_ids.items():
            if rec.get(label) == val:
                return rec
    return None


def main():
    if len(sys.argv) != 2:
        print(f'Usage: {sys.argv[0]} <pcap_file>', file=sys.stderr)
        sys.exit(1)

    pcap = sys.argv[1]
    proto = _detect_protocol(pcap)
    fields_cfg = _ID_FIELDS[proto]
    labels = [f[0] for f in fields_cfg]
    new_ue_msgs = _NEW_UE_MSGS.get(proto, set())
    release_msgs = _RELEASE_MSGS.get(proto, set())

    tshark_fields = ['frame.number', '_ws.col.Info'] + [f[1] for f in fields_cfg]
    lines = _run_tshark(pcap, tshark_fields)

    active = []  # list of dicts: {label: value}

    for line in lines:
        cols = line.split('\t')
        if len(cols) < 2 + len(fields_cfg):
            continue

        frame_num = cols[0]
        name = _msg_name(cols[1])
        id_cols = cols[2:]

        pkt_ids = {}
        for i, (label, _, as_hex) in enumerate(fields_cfg):
            raw = id_cols[i] if i < len(id_cols) else ''
            val = _parse_val(raw, as_hex)
            if val is not None:
                pkt_ids[label] = val

        if not pkt_ids:
            continue

        if name in release_msgs:
            rec = _find_record(active, pkt_ids)
            if rec is not None:
                active.remove(rec)
            continue

        rec = None if name in new_ue_msgs else _find_record(active, pkt_ids)
        if rec is None:
            rec = {}
            active.append(rec)

        updated = any(rec.get(label) != val for label, val in pkt_ids.items())
        rec.update(pkt_ids)

        if updated:
            id_str = ', '.join(f'{l}={rec[l]}' for l in labels if l in rec)
            print(f'{frame_num}, {name}, {id_str}')


if __name__ == '__main__':
    main()
