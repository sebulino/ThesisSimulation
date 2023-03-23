import json
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


def write_central_nodes():
    oracle_lightning_network = OracleLightningNetwork(graph)
    bet_centr = nx.betweenness_centrality(oracle_lightning_network.network, normalized=True, endpoints=False)
    sorted_nodes_by_centrality = sorted(bet_centr.items(), key=lambda x: x[1], reverse=True)
    with open("data/nodes_sorted_by_betweenness_centrality_basecase.json", "w") as write_file:
        json.dump(sorted_nodes_by_centrality, write_file, indent=4)


def get_central_nodes(n: int) -> list:
    with open('data/nodes_sorted_by_betweenness_centrality_basecase.json', 'r') as f:
        nodes = json.load(f)
    return nodes[0:n]


# ===== SETUP =====
graph = ChannelGraph("listchannels20230114.json")

min_payment_amount = 10000
max_payment_amount = 1000000
payment_pairs = 10000

# remove channels with base fee
graph = remove_channels_with_min_fee(graph, 0)
graph = only_channels_with_return_channels(graph)

delete_n_central_nodes = 0
central_nodes = get_central_nodes(delete_n_central_nodes)
oln = OracleLightningNetwork(graph)

if delete_n_central_nodes > 0:
    for i in range(0, delete_n_central_nodes):
        oln.network.remove_node(central_nodes[i][0])

initial_payments_file_name = "data/random_graph_06_initial_payments.ndjson"
create_payments(oln, payment_pairs, min_payment_amount, max_payment_amount)

# eliminate_payments_between_unconnected_nodes(min_payment_amount)
logging.info("Setup finished")
logging_level = logging.ERROR
logger = logging.getLogger()
logger.setLevel(logging_level)
loglevel = "error"

# ===== UTILITY FUNCTIONS FOR SIMULATION =====
results_prefix = "random_graph"

def dijkstra_fee(_payment_set, _graph):
    logging.error("===== Dijkstra on fees =====")
    # initialisation
    _uncertainty_network = UncertaintyNetwork(_graph)
    _oracle_lightning_network = OracleLightningNetwork(_graph)
    if delete_n_central_nodes > 0:
        for i in range(0, delete_n_central_nodes):
            _oracle_lightning_network.network.remove_node(central_nodes[i][0])
            _uncertainty_network.network.remove_node(central_nodes[i][0])
    logging.warning("deleting {} most central nodes done".format(delete_n_central_nodes))

    _sim_session = SyncSimulatedPaymentSession(_oracle_lightning_network, _uncertainty_network, prune_network=False)
    c = 0
    _successful_payments = []
    _failed_payments = []
    _all_payments = []
    sent_amount = 0
    failed_amount = 0
    total_amount = 0
    total_fees = 0

    for payment in _payment_set:
        c += 1
        logging.debug(f"{c} of {len(_payment_set)}")
        _sim_session.forget_information()
        ret, fees = _sim_session.dijkstra_pay(payment["sender"], payment["receiver"], payment["amount"], "fee",
                                              loglevel=loglevel)
        total_amount += payment["amount"]
        payment["delivery_method"] = "dijkstra_fees"
        payment["fees"] = fees
        total_fees += fees
        if ret == 0:
            _successful_payments.append(payment)
            sent_amount += payment["amount"]
            payment["residual_amount"] = 0
            logging.warning("{:4d}: success: {:,} paid.".format(c, payment["amount"]))
            logging.debug("Payment {} was successful.".format(c))
            payment['success'] = "success"
        elif ret == -1:
            _failed_payments.append(payment)
            payment['success'] = "no_path_found"
            payment["residual_amount"] = payment["amount"]
            failed_amount += payment["amount"]
            logging.warning("{:4d}: no path: residual amount: {:,}, original amount {:,}".
                            format(c, payment["residual_amount"], payment["amount"]))
            logging.debug("Payment {} failed.".format(c))
        elif ret > 0:
            _failed_payments.append(payment)
            payment['success'] = "delivery_failure"
            payment["residual_amount"] = ret
            failed_amount += payment["residual_amount"]
            logging.warning("{:4d}: failed: residual amount: {:,}, original amount {:,}".
                            format(c, payment["residual_amount"], payment["amount"]))
            logging.debug("Payment {} failed.".format(c))
        _all_payments.append(payment)

    # write all payments to file
    file = "data/" + results_prefix + "_dijkstra_fee.ndjson"
    ndjson.dump(_all_payments, open(file, "w"))

    logger.setLevel(logging_level)
    logging.error(f"=== {c} payments. {len(_successful_payments)} successful, {len(_failed_payments)} failed. ===")
    if sent_amount:
        logging.error(f"=== fee paid for {len(_successful_payments)} successful payments: {total_fees:,.0f} sats; "
                      f"ppm =  {total_fees * 1000 / sent_amount :,.0f}===")
    logging.error("=== of {:,} total sats, {:,} sats successful, {:,} sats failed. ===".format(total_amount,
                                                                                               sent_amount,
                                                                                               failed_amount))


def dijkstra_probability(_payment_set, _graph):
    logging.error("===== Dijkstra on probabilities =====")
    # initialisation
    _uncertainty_network = UncertaintyNetwork(_graph)
    _oracle_lightning_network = OracleLightningNetwork(_graph)
    if delete_n_central_nodes > 0:
        for i in range(0, delete_n_central_nodes):
            _oracle_lightning_network.network.remove_node(central_nodes[i][0])
            _uncertainty_network.network.remove_node(central_nodes[i][0])
    logging.warning("deleting {} most central nodes done".format(delete_n_central_nodes))
    _sim_session = SyncSimulatedPaymentSession(_oracle_lightning_network, _uncertainty_network, prune_network=False)
    c = 0
    _successful_payments = []
    _failed_payments = []
    _all_payments = []
    sent_amount = 0
    failed_amount = 0
    total_amount = 0
    total_fees = 0

    for payment in _payment_set:
        c += 1
        logging.debug(f"{c} of {len(_payment_set)}")
        _sim_session.forget_information()
        ret, fees = _sim_session.dijkstra_pay(payment["sender"], payment["receiver"],
                                              payment["amount"], "probability", loglevel=loglevel)
        total_amount += payment["amount"]
        payment["delivery_method"] = "dijkstra_probabilities"
        payment["fees"] = fees
        total_fees += fees

        if ret == 0:
            _successful_payments.append(payment)
            payment['success'] = "success"
            payment["residual_amount"] = 0
            sent_amount += payment["amount"]
            logging.warning("{:4d}: success: {:,} paid.".format(c, payment["amount"]))
            logging.debug("Payment {} was successful.".format(c))
        elif ret == -1:
            _failed_payments.append(payment)
            payment['success'] = "no_path_found"
            payment["residual_amount"] = payment["amount"]
            failed_amount += payment["amount"]
            logging.warning("{:4d}: no path: residual amount: {:,}, original amount {:,}".
                            format(c, payment["residual_amount"], payment["amount"]))
            logging.debug("Payment {} failed.".format(c))
        elif ret > 0:
            _failed_payments.append(payment)
            payment['success'] = "delivery_failure"
            payment["residual_amount"] = ret
            failed_amount += payment["residual_amount"]
            logging.warning("{:4d}: failed: residual amount: {:,}, original amount {:,}".
                            format(c, payment["residual_amount"], payment["amount"]))
            logging.debug("Payment {} failed.".format(c))
        _all_payments.append(payment)

    # write all payments to file
    file = "data/" + results_prefix + "_dijkstra_probability.ndjson"
    ndjson.dump(_all_payments, open(file, "w"))

    logger.setLevel(logging_level)
    logging.error(f"=== {c} payments. {len(_successful_payments)} successful, {len(_failed_payments)} failed. ===")
    if sent_amount:
        logging.error(f"=== fee paid for {len(_successful_payments)} successful payments: {total_fees:,.0f} sats; "
                      f"ppm =  {total_fees * 1000 / sent_amount :,.0f}===")
    logging.error("=== of {:,} total sats, {:,} sats successful, {:,} sats failed. ===".format(total_amount,
                                                                                               sent_amount,
                                                                                               failed_amount))


def dijkstra_mixed(_payment_set, _graph):
    logging.error("===== Dijkstra mixed =====")
    # initialisation
    _uncertainty_network = UncertaintyNetwork(_graph)
    _oracle_lightning_network = OracleLightningNetwork(_graph)
    if central_nodes > 0:
        for i in range(0, delete_n_central_nodes):
            _oracle_lightning_network.network.remove_node(central_nodes[i][0])
            _uncertainty_network.network.remove_node(central_nodes[i][0])
    logging.warning("deleting {} most central nodes done".format(delete_n_central_nodes))
    _sim_session = SyncSimulatedPaymentSession(_oracle_lightning_network, _uncertainty_network, prune_network=False)
    c = 0
    _successful_payments = []
    _failed_payments = []
    _all_payments = []
    sent_amount = 0
    failed_amount = 0
    total_amount = 0
    total_fees = 0

    for payment in _payment_set:
        c += 1
        logging.debug(f"{c} of {len(_payment_set)}")
        _sim_session.forget_information()
        ret, fees = _sim_session.dijkstra_pay(payment["sender"], payment["receiver"],
                                              payment["amount"], "mixed", loglevel=loglevel)
        total_amount += payment["amount"]
        payment["delivery_method"] = "dijkstra_mixed"
        payment["fees"] = fees
        total_fees += fees

        if ret == 0:
            _successful_payments.append(payment)
            payment['success'] = "success"
            payment["residual_amount"] = 0
            sent_amount += payment["amount"]
            logging.warning("{:4d}: success: {:,} paid.".format(c, payment["amount"]))
            logging.debug("Payment {} was successful.".format(c))
        elif ret == -1:
            _failed_payments.append(payment)
            payment['success'] = "no_path_found"
            payment["residual_amount"] = payment["amount"]
            failed_amount += payment["amount"]
            logging.warning("{:4d}: no path: residual amount: {:,}, original amount {:,}".
                            format(c, payment["residual_amount"], payment["amount"]))
            logging.debug("Payment {} failed.".format(c))
        elif ret > 0:
            _failed_payments.append(payment)
            payment['success'] = "delivery_failure"
            payment["residual_amount"] = ret
            failed_amount += payment["residual_amount"]
            logging.warning("{:4d}: failed: residual amount: {:,}, original amount {:,}".
                            format(c, payment["residual_amount"], payment["amount"]))
            logging.debug("Payment {} failed.".format(c))
        _all_payments.append(payment)

    # write all payments to file
    file = "data/" + results_prefix + "_dijkstra_mixed.ndjson"
    ndjson.dump(_all_payments, open(file, "w"))

    logger.setLevel(logging_level)
    logging.error(f"=== {c} payments. {len(_successful_payments)} successful, {len(_failed_payments)} failed. ===")
    if sent_amount:
        logging.error(f"=== fee paid for {len(_successful_payments)} successful payments: {total_fees:,.0f} sats; "
                      f"ppm =  {total_fees * 1000 / sent_amount :,.0f}===")
    logging.error("=== of {:,} total sats, {:,} sats successful, {:,} sats failed. ===".format(total_amount,
                                                                                               sent_amount,
                                                                                               failed_amount))


def pickhardtpay_fee(_payment_set, _graph):
    logging.error("===== Multipart Payments - MinCostFlow on fees =====")
    # initialisation
    _uncertainty_network = UncertaintyNetwork(_graph)
    _oracle_lightning_network = OracleLightningNetwork(_graph)
    if delete_n_central_nodes > 0:
        for i in range(0, delete_n_central_nodes):
            _oracle_lightning_network.network.remove_node(central_nodes[i][0])
            _uncertainty_network.network.remove_node(central_nodes[i][0])
    logging.warning("deleting {} most central nodes done".format(delete_n_central_nodes))
    _sim_session = SyncSimulatedPaymentSession(_oracle_lightning_network, _uncertainty_network, prune_network=False)
    c = 0
    _successful_payments = []
    _failed_payments = []
    _all_payments = []
    sent_amount = 0
    failed_amount = 0
    total_amount = 0
    flow_list = []
    total_fees = 0

    for payment in _payment_set:
        c += 1
        logging.debug(f"{c} of {len(_payment_set)}")
        _sim_session.forget_information()
        ret, fees = _sim_session.pickhardt_pay(c, flow_list, payment["sender"], payment["receiver"],
                                               payment["amount"], mu=1000, loglevel=loglevel)
        total_amount += payment["amount"]
        payment["delivery_method"] = "pickhardt_pay_fees"
        payment["fees"] = fees
        total_fees += fees

        if ret == 0:
            _successful_payments.append(payment)
            sent_amount += payment["amount"]
            payment["residual_amount"] = 0
            logging.warning("{:4d}: success: {:,} paid.".format(c, payment["amount"]))
            logging.debug("Payment {} was successful.".format(c))
            payment['success'] = "success"
        elif ret == -1:
            _failed_payments.append(payment)
            payment['success'] = "no_path_found"
            payment["residual_amount"] = payment["amount"]
            failed_amount += payment["amount"]
            logging.warning("{:4d}: no path: residual amount: {:,}, original amount {:,}".
                            format(c, payment["residual_amount"], payment["amount"]))
            logging.debug("Payment {} failed.".format(c))
        elif ret > 0:
            _failed_payments.append(payment)
            payment['success'] = "delivery_failure"
            payment["residual_amount"] = ret
            failed_amount += payment["residual_amount"]
            logging.warning("{:4d}: failed: residual amount: {:,}, original amount {:,}".
                            format(c, payment["residual_amount"], payment["amount"]))
            logging.debug("Payment {} failed.".format(c))
        _all_payments.append(payment)

    # write all payments to file
    file = "data/" + results_prefix + "_pickhardtpay_fee.ndjson"
    ndjson.dump(_all_payments, open(file, "w"))
    # ndjson.dump(flow_list, open("data/pickhardtpay_fee_flow.ndjson", "w"))

    logger.setLevel(logging_level)
    logging.error(f"=== {c} payments. {len(_successful_payments)} successful, {len(_failed_payments)} failed. ===")
    if sent_amount:
        logging.error(f"=== fee paid for {len(_successful_payments)} successful payments: {total_fees:,.0f} sats; "
                      f"ppm =  {total_fees * 1000 / sent_amount :,.0f}===")
    logging.error("=== of {:,} total sats, {:,} sats successful, {:,} sats failed. ===".format(total_amount,
                                                                                               sent_amount,
                                                                                               failed_amount))


def pickhardtpay_probability(_payment_set, _graph):
    logging.error("===== Multipart Payments - MinCostFlow on probabilities =====")
    # initialisation
    _uncertainty_network = UncertaintyNetwork(_graph)
    _oracle_lightning_network = OracleLightningNetwork(_graph)
    if delete_n_central_nodes > 0:
        for i in range(0, delete_n_central_nodes):
            _oracle_lightning_network.network.remove_node(central_nodes[i][0])
            _uncertainty_network.network.remove_node(central_nodes[i][0])
    logging.warning("deleting {} most central nodes done".format(delete_n_central_nodes))
    _sim_session = SyncSimulatedPaymentSession(_oracle_lightning_network, _uncertainty_network, prune_network=False)
    c = 0
    _successful_payments = []
    _failed_payments = []
    _all_payments = []
    sent_amount = 0
    failed_amount = 0
    total_amount = 0
    flow_list = []
    total_fees = 0

    for payment in _payment_set:
        logger.setLevel(logging_level)
        c += 1
        logging.debug(f"{c} of {len(_payment_set)}")
        _sim_session.forget_information()

        ret, fees = _sim_session.pickhardt_pay(c, flow_list, payment["sender"], payment["receiver"],
                                               payment["amount"], mu=0, loglevel=loglevel)
        total_amount += payment["amount"]
        payment["delivery_method"] = "pickhardt_pay_probability"
        payment["fees"] = fees
        total_fees += fees

        if ret == 0:
            _successful_payments.append(payment)
            payment['success'] = "success"
            sent_amount += payment["amount"]
            payment["residual_amount"] = 0
            logging.warning("{:4d}: success: {:,} paid.".format(c, payment["amount"]))
            logging.info("Payment {} was successful.".format(c))
        elif ret == -1:
            _failed_payments.append(payment)
            payment['success'] = "no_path_found"
            payment["residual_amount"] = payment["amount"]
            failed_amount += payment["amount"]
            logging.warning("{:4d}: no path: residual amount: {:,}, original amount {:,}".
                            format(c, payment["residual_amount"], payment["amount"]))
            logging.info("Payment {} failed.".format(c))
        elif ret > 0:
            _failed_payments.append(payment)
            payment['success'] = "delivery_failure"
            payment["residual_amount"] = ret
            failed_amount += payment["residual_amount"]
            logging.warning("{:4d}: failed: residual amount: {:,}, original amount {:,}".
                            format(c, payment["residual_amount"], payment["amount"]))
            logging.info("Payment {} failed.".format(c))
        _all_payments.append(payment)

    # write all payments to file
    file = "data/" + results_prefix + "_pickhardtpay_prob.ndjson"
    ndjson.dump(_all_payments, open(file, "w"))
    # ndjson.dump(flow_list, open("data/pickhardtpay_prob_flow.ndjson", "w"))

    logger.setLevel(logging_level)
    logging.error(f"=== {c} payments. {len(_successful_payments)} successful, {len(_failed_payments)} failed. ===")
    if sent_amount:
        logging.error(f"=== fee paid for {len(_successful_payments)} successful payments: {total_fees:,.0f} sats; "
                      f"ppm =  {total_fees * 1000 / sent_amount :,.0f}===")
    logging.error("=== of {:,} total sats, {:,} sats successful, {:,} sats failed. ===".format(total_amount,
                                                                                               sent_amount,
                                                                                               failed_amount))


def pickhardtpay_mixed(_payment_set, _graph):
    logging.error("===== Multipart Payments - MinCostFlow mixed =====")
    # initialisation
    _uncertainty_network = UncertaintyNetwork(_graph)
    _oracle_lightning_network = OracleLightningNetwork(_graph)
    if central_nodes > 0:
        for i in range(0, delete_n_central_nodes):
            _oracle_lightning_network.network.remove_node(central_nodes[i][0])
            _uncertainty_network.network.remove_node(central_nodes[i][0])
    logging.warning("deleting {} most central nodes done".format(delete_n_central_nodes))
    _sim_session = SyncSimulatedPaymentSession(_oracle_lightning_network, _uncertainty_network, prune_network=False)
    c = 0
    _successful_payments = []
    _failed_payments = []
    _all_payments = []
    sent_amount = 0
    failed_amount = 0
    total_amount = 0
    flow_list = []
    total_fees = 0

    for payment in _payment_set:
        logger.setLevel(logging_level)
        c += 1
        logging.debug(f"{c} of {len(_payment_set)}")
        _sim_session.forget_information()

        ret, fees = _sim_session.pickhardt_pay(c, flow_list, payment["sender"], payment["receiver"],
                                               payment["amount"], mu=500, loglevel=loglevel)
        total_amount += payment["amount"]
        payment["delivery_method"] = "pickhardt_pay_mixed"
        payment["fees"] = fees
        total_fees += fees

        if ret == 0:
            _successful_payments.append(payment)
            payment['success'] = "success"
            sent_amount += payment["amount"]
            payment["residual_amount"] = 0
            logging.warning("{:4d}: success: {:,} paid.".format(c, payment["amount"]))
            logging.info("Payment {} was successful.".format(c))
        elif ret == -1:
            _failed_payments.append(payment)
            payment['success'] = "no_path_found"
            payment["residual_amount"] = payment["amount"]
            failed_amount += payment["amount"]
            logging.warning("{:4d}: no path: residual amount: {:,}, original amount {:,}".
                            format(c, payment["residual_amount"], payment["amount"]))
            logging.info("Payment {} failed.".format(c))
        elif ret > 0:
            _failed_payments.append(payment)
            payment['success'] = "delivery_failure"
            payment["residual_amount"] = ret
            failed_amount += payment["residual_amount"]
            logging.warning("{:4d}: failed: residual amount: {:,}, original amount {:,}".
                            format(c, payment["residual_amount"], payment["amount"]))
            logging.info("Payment {} failed.".format(c))
        _all_payments.append(payment)

    # write all payments to file
    file = "data/" + results_prefix + "_pickhardtpay_mixed.ndjson"
    ndjson.dump(_all_payments, open(file, "w"))
    # ndjson.dump(flow_list, open("data/pickhardtpay_prob_flow.ndjson", "w"))

    logger.setLevel(logging_level)
    logging.error(f"=== {c} payments. {len(_successful_payments)} successful, {len(_failed_payments)} failed. ===")
    if sent_amount:
        logging.error(f"=== fee paid for {len(_successful_payments)} successful payments: {total_fees:,.0f} sats; "
                      f"ppm =  {total_fees * 1000 / sent_amount :,.0f}===")
    logging.error("=== of {:,} total sats, {:,} sats successful, {:,} sats failed. ===".format(total_amount,
                                                                                               sent_amount,
                                                                                               failed_amount))


def pickhardtpay_probability_with_retained_knowledge(_payment_set, _oracle_lightning_network, _uncertainty_network):
    logging.error("===== Multipart Payments - MinCostFlow on probabilities (retained) =====")
    # initialisation
    _sim_session = SyncSimulatedPaymentSession(_oracle_lightning_network, _uncertainty_network, prune_network=False)
    c = 0
    _successful_payments = []
    _failed_payments = []
    _all_payments = []
    sent_amount = 0
    failed_amount = 0
    total_amount = 0
    flow_list = []
    total_fees = 0

    for payment in _payment_set:
        logger.setLevel(logging_level)
        c += 1
        logging.debug(f"{c} of {len(_payment_set)}")
        # _sim_session.forget_information()

        ret, fees = _sim_session.pickhardt_pay(c, flow_list, payment["sender"], payment["receiver"],
                                               payment["amount"], mu=0, loglevel=loglevel)

        total_amount += payment["amount"]
        payment["delivery_method"] = "pickhardt_pay_probability_retained"
        payment["fees"] = fees
        total_fees += fees

        if ret == 0:
            payment['success'] = "success"
            _successful_payments.append(payment)
            sent_amount += payment["amount"]
            payment["residual_amount"] = 0
            logging.warning("{:4d}: success: {:,} paid.".format(c, payment["amount"]))
            logging.info("Payment {} was successful.".format(c))
        elif ret == -1:
            payment['success'] = "no_path_found"
            _failed_payments.append(payment)
            payment["residual_amount"] = payment["amount"]
            failed_amount += payment["amount"]
            logging.warning("{:4d}: no path: residual amount: {:,}, original amount {:,}".
                            format(c, payment["residual_amount"], payment["amount"]))
            logging.info("Payment {} failed.".format(c))
        elif ret > 0:
            payment['success'] = "delivery_failure"
            _failed_payments.append(payment)
            payment["residual_amount"] = ret
            failed_amount += payment["residual_amount"]
            logging.warning("{:4d}: failed: residual amount: {:,}, original amount {:,}".
                            format(c, payment["residual_amount"], payment["amount"]))
            logging.info("Payment {} failed.".format(c))
        else:
            print("gone through else - ret = {}. ret == -1 {}; ret == 0 {}".format(ret, (ret == -1), ret == 0))
            logging.warning(
                "gone through else - ret = {}. ret == -1 {}; ret == 0 {}".format(ret, (ret == -1), ret == 0))
            payment['success'] = "no_path_found"
            payment["residual_amount"] = payment["amount"]
            logging.info("Payment {} failed.".format(c))
            logging.error("_sim_session.pickhardt_pay returns {}".format(ret))
        _all_payments.append(payment)

    # write all payments to file
    file = "data/" + results_prefix + "_retained_knowledge_pickhardtpay_prob.ndjson"
    ndjson.dump(_all_payments, open(file, "w"))
    # ndjson.dump(flow_list, open("data/_retained_knowledge_pickhardtpay_prob_flow.ndjson", "w"))

    logger.setLevel(logging_level)
    logging.error(f"=== {c} payments. {len(_successful_payments)} successful, {len(_failed_payments)} failed. ===")
    if sent_amount:
        logging.error(f"=== fee paid for {len(_successful_payments)} successful payments: {total_fees:,.0f} sats; "
                      f"ppm =  {total_fees * 1000 / sent_amount :,.0f}===")
    logging.error(
        "=== of {:,} total sats, {:,} sats successful, {:,} sats failed. ===".format(total_amount, sent_amount,
                                                                                     failed_amount))


# ===== SIMULATION =====
from datetime import datetime

logging.info("===== start simulation =====")
payment_set = ndjson.load(open(initial_payments_file_name, "r"))
# payment_set = payment_set[0:50]

dijkstra_fee(payment_set, graph)
dijkstra_probability(payment_set, graph)
# dijkstra_mixed(payment_set, graph)
pickhardtpay_fee(payment_set, graph)
pickhardtpay_probability(payment_set, graph)
# pickhardtpay_mixed(payment_set, graph)

# code that is useful for centrality calculations
oracle_network = OracleLightningNetwork(graph)
uncertainty_network = UncertaintyNetwork(graph)
print("nodes in oracle network before deletion ", len(oracle_network.network.nodes))
if delete_n_central_nodes > 0:
    for i in range(0, delete_n_central_nodes):
        oracle_network.network.remove_node(central_nodes[i][0])
        uncertainty_network.network.remove_node(central_nodes[i][0])
logging.warning("deleting {} most central nodes done".format(delete_n_central_nodes))
print("nodes in oracle network after deletion: ", len(oracle_network.network.nodes))

pickhardtpay_probability_with_retained_knowledge(payment_set, oracle_network, uncertainty_network)


## Data collection

method_all = ["_dijkstra_fee", "_dijkstra_probability", "_dijkstra_mixed", "_pickhardtpay_fee", "_pickhardtpay_prob",
              "_pickhardtpay_mixed", "_retained_knowledge_pickhardtpay_prob"]
method_short = ["_dijkstra_fee", "_dijkstra_probability", "_pickhardtpay_fee", "_pickhardtpay_prob",
                "_retained_knowledge_pickhardtpay_prob"]

all_results = []
for m in method_short:
    file = "data/" + results_prefix + m + ".ndjson"
    all_results += ndjson.load(open(file, "r"))
ndjson.dump(all_results, open(file, "w"))
