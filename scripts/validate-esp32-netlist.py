#!/usr/bin/env python3
from pathlib import Path
import json, sys
root = Path(__file__).resolve().parents[1]
netlist = json.loads((root/'docs/esp32-breadboard/netlist.json').read_text())
nets = netlist['nets']
errors=[]
node_to_net={}
for net,nodes in nets.items():
    for node in nodes:
        if node in node_to_net:
            errors.append(f'Node {node} appears in both {node_to_net[node]} and {net}')
        node_to_net[node]=net

def assert_not_same_node_net(a,b,why):
    na=node_to_net.get(a, a if a in nets else None)
    nb=node_to_net.get(b, b if b in nets else None)
    if na is None:
        errors.append(f'Missing node/net {a}')
    if nb is None:
        errors.append(f'Missing node/net {b}')
    if na is not None and nb is not None and na == nb:
        errors.append(f'{a} and {b} share {na}: {why}')

def require(net,node):
    if node not in nets.get(net,[]):
        errors.append(f'Missing {node} from net {net}')

# Required isolation
assert_not_same_node_net('TP1_12V_PROT','TP2_5V_LOGIC','12 V protected rail must not connect to USB-derived 5 V logic rail')
assert_not_same_node_net('U1.pin3_1Y','U1.pin6_2Y','AHCT output channels must remain separate')
assert_not_same_node_net('J1.pin3_DATA','J2.pin3_DATA','J1/J2 data lines must be separate')
assert_not_same_node_net('J1.pin3_DATA','TP1_12V_PROT','Data must not connect to 12 V')
assert_not_same_node_net('J2.pin3_DATA','TP1_12V_PROT','Data must not connect to 12 V')
assert_not_same_node_net('ESP32.VIN_5V_FROM_USB_DO_NOT_BACKFEED','TP1_12V_PROT','ESP32 VIN must not connect to 12 V')

# Required connections
required = {
    'P5_LOGIC_USB': ['ESP32.VIN_5V_FROM_USB_DO_NOT_BACKFEED','U1.pin14_VCC','U1.pin10_OE3','U1.pin13_OE4'],
    'GND_COMMON': ['ESP32.GND','U1.pin7_GND','U1.pin1_OE1','U1.pin4_OE2','U1.pin9_3A','U1.pin12_4A','POWER_GND_BUS','BREADBOARD_GND_RAIL'],
    'U1_1Y_TO_R1': ['U1.pin3_1Y','R1.input'],
    'J1_DATA': ['R1.output','J1.pin3_DATA'],
    'U1_2Y_TO_R2': ['U1.pin6_2Y','R2.input'],
    'J2_DATA': ['R2.output','J2.pin3_DATA'],
    'U1_UNUSED_OUTPUTS_NC': ['U1.pin8_3Y_NC','U1.pin11_4Y_NC'],
}
for net,nodes in required.items():
    for node in nodes:
        require(net,node)

# No approved full-current 1N5822 component
for ref, comp in netlist.get('components', {}).items():
    if ref == 'D1' and '1N5822' in comp.get('part',''):
        errors.append('D1 1N5822 appears as approved component; use RP1 instead for full-current path')

if errors:
    print('FAIL')
    for e in errors:
        print('-',e)
    sys.exit(1)
print('PASS: ESP32 v6 breadboard netlist isolation and required connections verified.')
