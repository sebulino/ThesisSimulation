import logging
import ndjson
import random
import networkx as nx
from pickhardtpayments.pickhardtpayments import *


# ===== UTILITY FUNCTIONS FOR GRAPH PREPARATION =====

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


def create_payments(_graph, _number_of_payments, min_amount, max_amount):
    logging.info("## Generating the initial payment pairs")
    random.seed(1337)
    if (len(_graph.network.nodes())) < 3:
        logging.warning("graph has less than two nodes")
        exit(-1)
    _payments = []
    while len(_payments) < _number_of_payments:
        _random_nodes = random.sample(list(_graph.network.nodes), 2)
        # additional check for existence; doing it here avoids the check in each round, improving runtime
        src_exists = _random_nodes[0] in _graph.network.nodes()
        dest_exists = _random_nodes[1] in _graph.network.nodes()
        amount = random.randint(min_amount, max_amount)
        if src_exists and dest_exists:
            p = {"sender": _random_nodes[0], "receiver": _random_nodes[1], "amount": amount}
            _payments.append(p)
    # write payments to file
    ndjson.dump(_graph.network.nodes(), open("data/nodes.ndjson", "w"))
    ndjson.dump(_payments, open(initial_payments_file_name, "w"))
    logging.info("generating {} payment pairs finished.".format(len(_payments)))


def eliminate_payments_between_unconnected_nodes(min_capacity: int):
    logging.info("## Eliminating payments between nodes that are not connected")
    G = nx.MultiDiGraph()
    for edge in graph.network.edges(data="channel", keys=True):
        if edge[3].capacity > min_capacity:
            G.add_edge(edge[0], edge[1], weight=edge[3].ppm, capacity=edge[3].capacity, short_id=edge[2])

    logging.info(f"Graph has {len(G.edges)} edges")
    successful_payments = 0
    failed_payments = 0
    payment_simulation = []

    _payment_set = ndjson.load(open(initial_payments_file_name, "r"))

    for payment in _payment_set:
        try:
            node_path = nx.dijkstra_path(G, payment["sender"], payment["receiver"])
        except:
            failed_payments += 1
            continue
        else:
            successful_payments += 1
            payment_simulation.append(payment)

    ndjson.dump(payment_simulation, open(connected_pairs_file_name, "w"))
    logging.info("{} successful, {} failed.".format(successful_payments, failed_payments))
    logging.info("A total of {} payments between connected nodes in new payment set.".format(len(payment_simulation)))
    logging.warning("eliminating disconnected payment pairs finished.")


# ===== SETUP =====

graph = ChannelGraph("./pickhardtpayments/listchannels20220412.json")

min_payment_amount = 10000
max_payment_amount = 1000000
payment_pairs = 2000
logging_level = logging.INFO
logger = logging.getLogger()
logger.setLevel(logging_level)

# # no channels with base fee
# graph = remove_channels_with_min_fee(graph, 0)
graph = only_channels_with_return_channels(graph)
oracle_lightning_network = OracleLightningNetwork(graph)

initial_payments_file_name = "data/initial_payments.ndjson"
connected_pairs_file_name = "data/connected_node_payments.ndjson"

# create_payments(oracle_lightning_network, payment_pairs, min_payment_amount, max_payment_amount)
# eliminate_payments_between_unconnected_nodes(min_payment_amount)
logging.info("Setup finished")


# ===== UTILITY FUNCTIONS FOR SIMULATION =====

def dijkstra_sim_fee(_payment_set, _graph):
    # initialisation
    _uncertainty_network = UncertaintyNetwork(_graph)
    _oracle_lightning_network = OracleLightningNetwork(_graph)
    _sim_session = SyncSimulatedPaymentSession(_oracle_lightning_network, _uncertainty_network, prune_network=False)
    c = 0
    _successful_payments = []
    _failed_payments = []
    sent_amount = 0
    failed_amount = 0
    total_amount = 0

    for payment in _payment_set:
        c += 1
        logging.debug(f"{c} of {len(_payment_set)}")
        _sim_session.forget_information()
        payment["residual_amount"] = _sim_session.dijkstra_pay(payment["sender"], payment["receiver"],
                                                               payment["amount"], "fee", loglevel="error")
        total_amount += payment["amount"]

        if payment["residual_amount"] == 0:
            _successful_payments.append(payment)
            sent_amount += payment["amount"]
            print("{:4d}: success: residual amount: {:,}, sent amount {:,}".
                  format(c, payment["residual_amount"], payment["amount"] - payment["residual_amount"]))
            logging.debug("Payment {} was successful.".format(c))
            payment['success'] = 1
        if payment["residual_amount"] > 0:
            _failed_payments.append(payment)
            failed_amount += payment["residual_amount"]
            print("{:4d}: failed: residual amount: {:,}, original amount {:,}".
                  format(c, payment["residual_amount"], payment["amount"]))
            logging.debug("Payment {} failed.".format(c))
            payment['success'] = 0

    # write successful payments to file
    ndjson.dump(_successful_payments, open("data/dijkstra_sim_fee_success.ndjson", "w"))
    ndjson.dump(_failed_payments, open("data/dijkstra_sim_fee_failure.ndjson", "w"))
    logger.setLevel(logging_level)
    logging.error(f"=== {c} payments. {len(_successful_payments)} successful, {len(_failed_payments)} failed. ===")
    logging.error("=== of {:,} total sats, {:,} sats successful, {:,} sats failed. ===".format(total_amount, sent_amount, failed_amount))


def dijkstra_sim_probability(_payment_set, _graph):
    # initialisation
    _uncertainty_network = UncertaintyNetwork(_graph)
    _oracle_lightning_network = OracleLightningNetwork(_graph)
    _sim_session = SyncSimulatedPaymentSession(_oracle_lightning_network, _uncertainty_network, prune_network=False)
    c = 0
    _successful_payments = []
    _failed_payments = []
    sent_amount = 0
    failed_amount = 0
    total_amount = 0

    for payment in _payment_set:
        c += 1
        logging.debug(f"{c} of {len(_payment_set)}")
        _sim_session.forget_information()
        payment["residual_amount"] = _sim_session.dijkstra_pay(payment["sender"], payment["receiver"],
                                                               payment["amount"], "probability", loglevel="error")
        total_amount += payment["amount"]

        if payment["residual_amount"] == 0:
            _successful_payments.append(payment)
            sent_amount += payment["amount"]
            print("{:4d}: success: residual amount: {:,}, sent amount {:,}".
                  format(c, payment["residual_amount"], payment["amount"] - payment["residual_amount"]))
            logging.debug("Payment {} was successful.".format(c))
            payment['success'] = 1
        if payment["residual_amount"] > 0:
            _failed_payments.append(payment)
            failed_amount += payment["residual_amount"]
            print("{:4d}: failed: residual amount: {:,}, original amount {:,}".
                  format(c, payment["residual_amount"], payment["amount"]))
            logging.debug("Payment {} failed.".format(c))
            payment['success'] = 0

    # write successful payments to file
    ndjson.dump(_successful_payments, open("data/dijkstra_sim_probability_success.ndjson", "w"))
    ndjson.dump(_failed_payments, open("data/dijkstra_sim_probability_failure.ndjson", "w"))
    logger.setLevel(logging_level)
    logging.error(f"=== {c} payments. {len(_successful_payments)} successful, {len(_failed_payments)} failed. ===")
    logging.error("=== of {:,} total sats, {:,} sats successful, {:,} sats failed. ===".format(total_amount, sent_amount, failed_amount))


def pickhardtpay_sim(_payment_set, _graph):
    # initialisation
    _uncertainty_network = UncertaintyNetwork(_graph)
    _oracle_lightning_network = OracleLightningNetwork(_graph)
    _sim_session = SyncSimulatedPaymentSession(_oracle_lightning_network, _uncertainty_network, prune_network=False)
    c = 0
    _successful_payments = []
    _failed_payments = []
    sent_amount = 0
    failed_amount = 0
    total_amount = 0

    for payment in _payment_set:
        c += 1
        logging.debug(f"{c} of {len(_payment_set)}")
        _sim_session.forget_information()
        payment["residual_amount"] = _sim_session.pickhardt_pay(payment["sender"], payment["receiver"],
                                                                payment["amount"], loglevel="error")
        total_amount += payment["amount"]

        if payment["residual_amount"] == 0:
            _successful_payments.append(payment)
            sent_amount += payment["amount"]
            print("{:4d}: success: residual amount: {:,}, sent amount {:,}".
                  format(c, payment["residual_amount"], payment["amount"] - payment["residual_amount"]))
            logging.debug("Payment {} was successful.".format(c))
            payment['success'] = 1
        if payment["residual_amount"] > 0:
            _failed_payments.append(payment)
            failed_amount += payment["residual_amount"]
            print("{:4d}: failed: residual amount: {:,}, original amount {:,}".
                  format(c, payment["residual_amount"], payment["amount"]))
            logging.debug("Payment {} failed.".format(c))
            payment['success'] = 0

    # write successful payments to file
    ndjson.dump(_successful_payments, open("data/pickhardtpay_sim_success.ndjson", "w"))
    ndjson.dump(_failed_payments, open("data/pickhardtpay_sim_failure.ndjson", "w"))
    logger.setLevel(logging_level)
    logging.error(f"=== {c} payments. {len(_successful_payments)} successful, {len(_failed_payments)} failed. ===")
    logging.error("=== of {:,} total sats, {:,} sats successful, {:,} sats failed. ===".format(total_amount, sent_amount, failed_amount))


# ===== SIMULATION =====

logging.info("===== start simulation =====")

# payment_set = ndjson.load(open(connected_pairs_file_name, "r"))
payment_set = ndjson.load(open(initial_payments_file_name, "r"))
#payment_set = payment_set[0:50]

logging.info("## Paying the sampled payments with dijkstra pay with fees as cost")
logging.warning("===== dijkstra pay by fee =====")
dijkstra_sim_fee(payment_set, graph)

logging.info("## Paying the sampled payments with dijkstra pay with probability as cost")
logging.warning("===== dijkstra pay by probability =====")
dijkstra_sim_probability(payment_set, graph)

logging.info("## Paying the sampled payments with pickhardt payment")
logging.warning("===== pickhardt pay (MPP) =====")
pickhardtpay_sim(payment_set, graph)
