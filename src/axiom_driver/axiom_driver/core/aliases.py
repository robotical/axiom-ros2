"""Optional, unambiguous aliases for advertised sensor types."""

import re


def validate_aliases(rules):
    if not isinstance(rules, dict):
        raise ValueError('topic_aliases must be a JSON object')
    reserved = {'devices', 'device_metadata', 'diagnostics', 'raw', 'serial_console'}
    for alias, rule in rules.items():
        if (not isinstance(alias, str)
                or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]*(/[a-zA-Z][a-zA-Z0-9_]*)*', alias)
                or alias.split('/')[0] in reserved or alias.startswith('bus_')):
            raise ValueError('Aliases must be relative ROS names outside driver/device topics')
        if not isinstance(rule, dict) or set(rule) - {'type', 'source', 'bus', 'address'}:
            raise ValueError('Alias rules support type, source, bus and address')
        if not isinstance(rule.get('type'), str) or not rule['type']:
            raise ValueError('Each alias needs an advertised sensor type')
        if rule.get('source') not in (
            'imu/data_raw', 'range', 'thermal/grid', 'temperature', 'humidity',
            'battery', 'joint_states', 'sample', 'data',
        ):
            raise ValueError('Alias source must be a supported sensor topic suffix')
        for field in ('bus', 'address'):
            if field in rule and not isinstance(rule[field], str):
                raise ValueError('Alias bus and address selectors must be strings')
    return rules


def bindings(rules, devices):
    result = {}
    for alias, rule in rules.items():
        candidates = [row for row in devices
                      if row['online'] and not row['stale'] and row['metadata_ready']
                      and row['type'] == rule['type']
                      and all(row[field] == rule[field] for field in ('bus', 'address')
                              if field in rule)]
        if len(candidates) == 1:
            row = candidates[0]
            result[alias] = (row['topic'], row['revision'], rule['source'])
    return result
