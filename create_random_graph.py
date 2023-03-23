import logging
import os
import random
import networkx as nx

from pickhardtpayments.pickhardtpayments import *


def remove_channels_with_min_fee(_graph: ChannelGraph, base_threshold=0):
    ebunch = []
    for edge in _graph.network.edges:
        ch = _graph.get_channel(edge[1], edge[0], edge[2])
        if ch and ch.base_fee > base_threshold:
            ebunch.append((edge[0], edge[1], edge[2]))
    _graph.network.remove_edges_from(ebunch)
    if len(ebunch) == 0:
        logging.info("no channels with base fee.")
    else:
        logging.info("channels with base fee removed.")
    return _graph


def only_channels_with_return_channels(_graph: ChannelGraph):
    ebunch = []
    for edge in _graph.network.edges:
        return_edge = _graph.get_channel(edge[1], edge[0], edge[2])
        if not return_edge:
            ebunch.append((edge[0], edge[1], edge[2]))
    _graph.network.remove_edges_from(ebunch)
    if len(ebunch) == 0:
        logging.info("channel graph only had channels in both directions.")
    else:
        logging.info("channel graph had unannounced channels.")
    return _graph


seed = 12345

graph = ChannelGraph("listchannels20230114.json")
graph = remove_channels_with_min_fee(graph, 0)
graph = only_channels_with_return_channels(graph)
oln = OracleLightningNetwork(graph)
print("original edges:", len(oln.network.edges))
number_of_vertices = len(oln.network.nodes)
number_of_edges = int(len(oln.network.edges) / 2)
print("random edges:", number_of_edges)

# set pool for random fees
fees = []
cap = []

for e in oln.network.edges:
    ch = oln.get_channel(e[0], e[1], e[2])
    fees.append(ch.ppm)
    cap.append(ch.capacity)

random.seed(seed)
capacity = random.sample(cap, number_of_edges)
fee = random.sample(fees, number_of_edges)

random_graph = nx.gnm_random_graph(number_of_vertices, number_of_edges, seed=seed, directed=False)
print("graph created")

file_name = 'thesis/listchannels00.json'

try:
    os.remove(file_name)
except OSError:
    pass
print("file cleared")

i = 0
with open(file_name, 'a') as f:
    f.write("{\n")
    f.write("\t\"channels\": [\n")
    f.write("\t\t{\n")

    for e in random_graph.edges:
        f.write("\t\t\t\"source\": \"{}\",\n".format(e[0]))
        f.write("\t\t\t\"destination\": \"{}\",\n".format(e[1]))
        f.write("\t\t\t\"short_channel_id\": \"{}x{}\",\n".format(e[0], e[1]))
        f.write("\t\t\t\"public\": true,\n")
        f.write("\t\t\t\"satoshis\": {},\n".format(capacity[i]))
        f.write("\t\t\t\"amount_msat\": \"{}msat\",\n".format(capacity[i] * 1000))
        f.write("\t\t\t\"base_fee_millisatoshi\": 0,\n")
        f.write("\t\t\t\"fee_per_millionth\": {}\n".format(fee[i]))
        f.write("\t\t},\n")
        f.write("\t\t{\n")
        f.write("\t\t\t\"source\": \"{}\",\n".format(e[1]))
        f.write("\t\t\t\"destination\": \"{}\",\n".format(e[0]))
        f.write("\t\t\t\"short_channel_id\": \"{}x{}\",\n".format(e[0], e[1]))
        f.write("\t\t\t\"public\": true,\n")
        f.write("\t\t\t\"satoshis\": {},\n".format(capacity[i]))
        f.write("\t\t\t\"amount_msat\": \"{}msat\",\n".format(capacity[i] * 1000))
        f.write("\t\t\t\"base_fee_millisatoshi\": 0,\n")
        f.write("\t\t\t\"fee_per_millionth\": {}\n".format(fee[i]))
        i += 1
        if not (i == number_of_edges):
            f.write("\t\t},\n")
            f.write("\t\t{\n")
        else:
            f.write("\t\t}\n")
            f.write("\t]\n")
            f.write("}\n")
f.close()

print("done")

