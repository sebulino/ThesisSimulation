from pickhardtpayments.pickhardtpayments import *


def remove_channels_with_min_fee(_graph: ChannelGraph, base_threshold=0):
    ebunch = []
    for edge in _graph.network.edges:
        ch = _graph.get_channel(edge[1], edge[0], edge[2])
        if ch and ch.base_fee > base_threshold:
            ebunch.append((edge[0], edge[1], edge[2]))
    _graph.network.remove_edges_from(ebunch)
    return _graph


def only_channels_with_return_channels(_graph: ChannelGraph):
    ebunch = []
    for edge in _graph.network.edges:
        return_edge = _graph.get_channel(edge[1], edge[0], edge[2])
        if not return_edge:
            ebunch.append((edge[0], edge[1], edge[2]))
    _graph.network.remove_edges_from(ebunch)
    return _graph


graph = ChannelGraph("listchannels20230114.json")
graph = remove_channels_with_min_fee(graph, 0)
graph = only_channels_with_return_channels(graph)

oracle_lightning_network = OracleLightningNetwork(graph)

min_cap = 0
max_cap = 0

for e in oracle_lightning_network.network.edges:
    if oracle_lightning_network.get_channel(e[0],e[1],e[2]).capacity > max_cap:
        max_cap = oracle_lightning_network.get_channel(e[0],e[1],e[2]).capacity
min_cap = max_cap
for e in oracle_lightning_network.network.edges:
    if oracle_lightning_network.get_channel(e[0], e[1], e[2]).capacity < min_cap:
        min_cap = oracle_lightning_network.get_channel(e[0], e[1], e[2]).capacity

print("min: {:,}".format(min_cap))
print("max:{:,}".format(max_cap))