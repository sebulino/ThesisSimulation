"""
SyncSimulatedPaymentSession.py
====================================
The core module of the pickhardt payment project.
An example payment is executed and statistics are run.
"""
import math

import ndjson
import networkx as nx

from .Payment import Payment, MCFSolverError
from .UncertaintyNetwork import UncertaintyNetwork
from .OracleLightningNetwork import OracleLightningNetwork

import logging
import sys

session_logger = logging.getLogger()
session_logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s.%(msecs)03d | %(levelname)s | %(message)s', datefmt='%H:%M:%S')
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setLevel(logging.INFO)
stdout_handler.setFormatter(formatter)
file_handler = logging.FileHandler('pickhardt_pay.log', mode='w')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)
session_logger.addHandler(file_handler)
session_logger.addHandler(stdout_handler)

DEFAULT_BASE_THRESHOLD = 0


class SyncSimulatedPaymentSession:
    """
    A PaymentSession is used to create the min cost flow problem from the UncertaintyNetwork

    This happens by adding several parallel arcs coming from the piece wise linearization of the
    UncertaintyChannel to the min_cost_flow object.

    The main API call is `pickhardt_pay` which invokes a sequential loop to conduct trial and error
    attempts. The loop could easily send out all onions concurrently but this does not make sense
    against the simulated OracleLightningNetwork.
    """

    def __init__(self,
                 oracle_network: OracleLightningNetwork,
                 uncertainty_network: UncertaintyNetwork,
                 prune_network: bool = True):
        self._oracle_network = oracle_network
        self._uncertainty_network = uncertainty_network
        self._uncertainty_network.prune = prune_network

    @property
    def uncertainty_network(self) -> UncertaintyNetwork:
        return self._uncertainty_network

    @property
    def oracle_network(self) -> OracleLightningNetwork:
        return self._oracle_network

    def forget_information(self):
        """
        Forgets all the information in the UncertaintyNetwork the PaymentSession
        Resets minimum liquidity to 0, max liquidity to capacity and in_flights to 0.
        """
        self._uncertainty_network.reset_uncertainty_network()

    def activate_network_wide_uncertainty_reduction(self, n):
        """
        Pipes API call to the UncertaintyNetwork
        """
        self._uncertainty_network.activate_network_wide_uncertainty_reduction(
            n, self._oracle_network)

    def pickhardt_pay(self, src, dest, amt=1, mu=1, base=DEFAULT_BASE_THRESHOLD, loglevel="error"):
        """
        Conducts one payment with the pickhardt payment methodology.

        :sub_payment.initiate(): starts the first round and calls the solver to get paths. For each path the attempt is
        registered as planned and the amount is registered in the uncertainty network as in_flight.
        :OracleLightningNetwork.send_onion(): is called on the Attempts of this first round and with this the attempts
        are then tested against the OracleNetwork. Every failed attempt from send_onion is then updated as
        AttemptStatus.FAILED and the in_flight amounts are removed from the UncertaintyNetwork.
        For every successful call of send_onion the amount is registered in the OracleNetwork as inflight and the
        AttemptStatus is set to AttemptStatus.INFLIGHT. The amounts have been allocated in the UncertaintyNetwork
        already, so no change is necessary here.
        If onions failed, the next round is started for the remaining amount.
        `evaluate attempts` sends statistics on the Attempt to the logs.
        `register_sub_payment` collects and adds all Attempts - failed and inflight - to the original Payment.

        After the total amount has been allocated on the OracleNetwork, Payment.finalize() is called. This then
        reflects the arrival of all payments at the receiver, who then passes the preimage to unlock the
        HTLCs/inflight amounts. For all Attempts of the Payment with AttemptStatus.INFLIGHT the balances of the nodes
        are updated in the OracleNetwork on both channels.
        The AttemptStatus is consequently set to SETTLED, which triggers the update of the channels in the
        UncertaintyNetwork.

        amt=1, mu=1, base=DEFAULT_BASE_THRESHOLD, loglevel="info"
        :param src: node id of the sending node
        :type: str
        :param dest: node id of the receiving node
        :type: str
        :param amt: amount in satoshi to be sent
        :type: int
        :param mu: controls the balance between uncertainty cost and fees in the solver
        :type: int
        :param base: eliminates all channels with a base fee lower than `base`
        :type: int
        :param loglevel: determines verbosity,
        :type: str

        """
        # session_logger.info('*** new pickhardt payment ***')
        probability_too_low = False

        numeric_level = logging.getLevelName(loglevel.upper())
        if not isinstance(numeric_level, int):
            raise ValueError('Invalid log level: %s' % loglevel)
        session_logger.setLevel(numeric_level)

        # Initialise Payment
        payment = Payment(self.uncertainty_network, self.oracle_network, src, dest, amt, mu, base)

        # This is the main payment loop. It is currently blocking and synchronous but may be
        # implemented in a concurrent way. Also, we stop after 10 rounds which is pretty arbitrary
        # a better stop criteria would be if we compute infeasible flows or if the probabilities
        # are too low or residual amounts decrease to slowly
        # TODO add 'expected value' to break condition for loop
        while payment.residual_amount > 0 and payment.pickhardt_payment_rounds <= 1 and not probability_too_low:
            payment.increment_pickhardt_payment_rounds()
            sub_payment = Payment(self.uncertainty_network, self.oracle_network, payment.sender, payment.receiver,
                                  payment.residual_amount, mu, base)

            # transfer to a min cost flow problem and run the solver. Attempts for payment are generated.
            try:
                sub_payment.initiate()
            except MCFSolverError as err:
                logging.warning(err)
                logging.warning("Payment failed.")
                break

            # Try to send amounts in attempts and registers if success or not
            # update our information regarding the in_flights in the UncertaintyNetwork and OracleNetwork
            sub_payment.attempt_payments()

            # run some simple statistics and depict them
            sub_payment.evaluate_attempts()

            if sub_payment.attempts[-1].probability < 0.1:
                probability_too_low = True
                logging.warning("probability in last attempt too low")

            # add attempts of sub_payment to payment
            payment.register_sub_payment(sub_payment)

        # When residual amount is 0 then settle payment.
        if payment.residual_amount == 0:
            for attempt in payment.attempts:
                logging.debug("___")
                for channel in attempt.path:
                    logging.debug("- " + channel.src + " to " + channel.dest + ", " + str(attempt.amount))
            payment.execute()
            logging.debug("Payment successful.")
        else:
            # TODO if payment fails: cleanup of inflights in Uncertainty Network
            session_logger.info("Payment failed!")
            session_logger.info("residual amount: {:>10,} sats".format(payment.residual_amount))

        # Final Stats
        payment.get_summary()

        if payment.residual_amount:
            return payment.residual_amount
        return 0
        #if payment.residual_amount:
        #    return -1
        # return 1

    # added for simulation
    def dijkstra_pay(self, src, dest, amt=1, criteria="fee", base=DEFAULT_BASE_THRESHOLD, loglevel="debug") -> int:
        """
        Conducts one payment with the 'classic' payment methodology.

        amt=1, mu=1, base=DEFAULT_BASE_THRESHOLD, loglevel="info"
        :param criteria:
        :param src: node id of the sending node
        :type: str
        :param dest: node id of the receiving node
        :type: str
        :param amt: amount in satoshi to be sent
        :type: int
        :param mu: controls the balance between uncertainty cost and fees in the solver
        :type: int
        :param base: eliminates all channels with a base fee lower than `base`
        :type: int
        :param loglevel: determines verbosity,
        :type: str
        """
        # session_logger.info('*** new classic payment ***')

        numeric_level = logging.getLevelName(loglevel.upper())
        if not isinstance(numeric_level, int):
            raise ValueError('Invalid log level: %s' % loglevel)
        session_logger.setLevel(numeric_level)

        # Initialise Payment
        payment = Payment(self.uncertainty_network, self.oracle_network, src, dest, amt, 1, base)

        G = nx.MultiDiGraph()
        for edge in self.uncertainty_network.network.edges(data="channel", keys=True):
            if edge[3].capacity > amt:
                prob = -math.log(1 - amt/edge[3].capacity)
                G.add_edge(edge[0], edge[1], fee=edge[3].ppm, probability=prob, capacity=edge[3].capacity, short_id=edge[2])

        payment.get_dijkstra_path(G, criteria)  # payment now has Attempt
        for attempt in payment.attempts:
            logging.debug("attempt: {}".format(attempt))
            for channel in attempt.path:
                # logging.info("- " + channel.src + " to " + channel.dest + ", " + str(attempt.amount))
                ch = self.oracle_network.get_channel(channel.src, channel.dest, channel.short_channel_id)
                liqui = ch.actual_liquidity
                logging.debug("- channel {}-{} with capacity {:,.0f}, liquidity {:,.0f} and fees {:,.0f}"
                              .format(channel.src[0:4], channel.dest[0:4], channel.capacity, liqui, channel.ppm))
        payment.attempt_payments()
        if payment.residual_amount:
            return payment.residual_amount
        else:
            payment.execute()
        return 0

    # def YenKSP(Graph, source, sink, K):
    #     # Determine the shortest path from the source to the sink.
    #     A[0] = dijkstra(Graph, source, sink);
    #     # Initialize the set to store the potential kth shortest path.
    #     B = [];
    #
    #     for k from 1 to K:
    #         # The spur node ranges from the first node to the next to last node in the previous k-shortest path.
    #         for i from 0 to size(A[k − 1]) − 2:
    #
    #             # Spur node is retrieved from the previous k-shortest path, k − 1.
    #             spurNode = A[k-1].node(i);
    #             # The sequence of nodes from the source to the spur node of the previous k-shortest path.
    #             rootPath = A[k-1].nodes(0, i);
    #
    #             for each path p in A:
    #                 if rootPath == p.nodes(0, i):
    #                     # Remove the links that are part of the previous shortest paths which share the same root path.
    #                     remove p.edge(i,i + 1) from Graph;
    #
    #             for each node rootPathNode in rootPath except spurNode:
    #                 remove rootPathNode from Graph;
    #
    #             # Calculate the spur path from the spur node to the sink.
    #             # Consider also checking if any spurPath found
    #             spurPath = Dijkstra(Graph, spurNode, sink);
    #
    #             # Entire path is made up of the root path and spur path.
    #             totalPath = rootPath + spurPath;
    #             # Add the potential k-shortest path to the heap.
    #             if (totalPath not in B):
    #                 B.append(totalPath);
    #
    #             # Add back the edges and nodes that were removed from the graph.
    #             restore edges to Graph;
    #             restore nodes in rootPath to Graph;
    #
    #         if B is empty:
    #             # This handles the case of there being no spur paths, or no spur paths left.
    #             # This could happen if the spur paths have already been exhausted (added to A),
    #             # or there are no spur paths at all - such as when both the source and sink vertices
    #             # lie along a "dead end".
    #             break;
    #         # Sort the potential k-shortest paths by cost.
    #         B.sort();
    #         # Add the lowest cost path becomes the k-shortest path.
    #         A[k] = B[0];
    #         # In fact we should rather use shift since we are removing the first element
    #         B.pop();
    #
    #     return A
    #
    #
